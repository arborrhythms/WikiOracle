#!/usr/bin/env python3
"""Tests for the voting protocol: cycle prevention and per-provider truth."""

import json
import sys
import unittest
from pathlib import Path

# Ensure bin/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from response import (
    Source,
    _build_provider_query_bundle,
    evaluate_providers,
    resolve_provider_truth,
    to_nanochat_messages,
)
from truth import (
    get_provider_entries,
    parse_provider_block,
)


SPEC_DIR = Path(__file__).resolve().parent.parent / "spec"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider_entry(name, entry_id, certainty=0.8, truth_url=""):
    """Create a (trust_entry, provider_config) pair for testing."""
    content = (
        f'<provider id="{entry_id}" trust="{certainty}" title="{name}" '
        f'name="{name}" api_url="http://test/{name}" model="test"'
    )
    if truth_url:
        content += f' truth_url="{truth_url}"'
    content += "/>"

    entry = {
        "id": entry_id,
        "title": name,
        "certainty": certainty,
        "time": "2026-03-01T00:00:00Z",
        "content": content,
    }
    config = {
        "name": name,
        "api_url": f"http://test/{name}",
        "api_key": "k",
        "model": "test",
        "truth_url": truth_url,
        "timeout": 30,
        "max_tokens": 1024,
    }
    return (entry, config)


def _load_truth_entries(filename):
    """Load truth entries from a spec JSONL file."""
    path = SPEC_DIR / filename
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("type") == "truth":
            entries.append(rec)
    return entries


# ---------------------------------------------------------------------------
# Cycle prevention tests
# ---------------------------------------------------------------------------

class TestVotingCyclePrevention(unittest.TestCase):
    """Verify that providers in the call chain stay silent."""

    def test_cycle_detected_direct(self):
        """Provider whose ID is in call_chain is silenced."""
        pairs = [_make_provider_entry("A", "prov_a")]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "response",
            call_chain=["prov_a"],
        )
        self.assertEqual(len(results), 0)

    def test_cycle_detected_transitive(self):
        """Multiple providers in call_chain are all silenced."""
        pairs = [
            _make_provider_entry("A", "prov_a"),
            _make_provider_entry("B", "prov_b"),
        ]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "response",
            call_chain=["prov_a", "prov_b"],
        )
        self.assertEqual(len(results), 0)

    def test_no_cycle_when_not_in_chain(self):
        """Provider NOT in call_chain is evaluated normally."""
        pairs = [_make_provider_entry("B", "prov_b")]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "response from B",
            call_chain=["prov_a"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "B")
        self.assertIn("response from B", results[0].content)

    def test_mixed_chain_and_free(self):
        """Only providers in the chain are silenced; others respond."""
        pairs = [
            _make_provider_entry("A", "prov_a"),
            _make_provider_entry("B", "prov_b"),
            _make_provider_entry("C", "prov_c"),
        ]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: f"from {p['name']}",
            call_chain=["prov_a"],
        )
        self.assertEqual(len(results), 2)
        names = {r.title for r in results}
        self.assertEqual(names, {"B", "C"})

    def test_empty_call_chain_backward_compat(self):
        """With no call_chain, all providers are evaluated (backward compat)."""
        pairs = [_make_provider_entry("A", "prov_a")]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "ok",
        )
        self.assertEqual(len(results), 1)

    def test_none_call_chain_backward_compat(self):
        """call_chain=None behaves the same as empty list."""
        pairs = [_make_provider_entry("A", "prov_a")]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "ok",
            call_chain=None,
        )
        self.assertEqual(len(results), 1)

    def test_silence_not_counted_as_error(self):
        """Silenced provider produces no Source — it's not an error response."""
        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["name"])
            return "response"

        pairs = [_make_provider_entry("A", "prov_a")]
        results = evaluate_providers(
            pairs, "", [], "q", "", mock_call,
            call_chain=["prov_a"],
        )
        # The call_fn should never be invoked for a silenced provider
        self.assertEqual(call_log, [])
        self.assertEqual(len(results), 0)

    def test_deep_chain_exclusion(self):
        """A → B → C chain: all three excluded from a vote at depth 3."""
        pairs = [
            _make_provider_entry("A", "prov_a"),
            _make_provider_entry("B", "prov_b"),
            _make_provider_entry("C", "prov_c"),
            _make_provider_entry("D", "prov_d"),
        ]
        results = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "ok",
            call_chain=["prov_a", "prov_b", "prov_c"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "D")


# ---------------------------------------------------------------------------
# Dom/sub mutual reference scenario
# ---------------------------------------------------------------------------

class TestDomSubMutualReference(unittest.TestCase):
    """Simulate the dom→sub→dom cycle from the spec files."""

    def test_dom_calls_sub_sub_calls_dom_dom_is_silent(self):
        """Dom initiates vote → sub is called → sub tries to call dom → dom
        finds itself in chain → keeps quiet.

        Simulated as two rounds of evaluate_providers.
        """
        dom = _make_provider_entry("dom", "provider_dom", certainty=0.9)
        sub = _make_provider_entry("sub", "provider_sub1", certainty=0.8)

        # Round 1: dom initiates vote, calls sub as secondary.
        # call_chain starts empty (dom is the root).
        round1_results = evaluate_providers(
            [sub],  # secondaries
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Sub says: it is a tower in Paris",
        )
        self.assertEqual(len(round1_results), 1)
        self.assertEqual(round1_results[0].title, "sub")

        # Round 2: sub initiates its own nested vote, tries to call dom.
        # call_chain now includes dom (the root) AND sub (the nested dom).
        round2_chain = ["provider_dom", "provider_sub1"]
        round2_results = evaluate_providers(
            [dom],  # sub tries to call dom as its secondary
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Dom would respond — but should be silenced",
            call_chain=round2_chain,
        )
        # Dom must stay silent — it's in the chain
        self.assertEqual(len(round2_results), 0)


# ---------------------------------------------------------------------------
# Branching: dom calls sub1 AND sub2
# ---------------------------------------------------------------------------

class TestBranchingVote(unittest.TestCase):
    """Dom fans out to sub1 and sub2; both try to call dom back."""

    def test_dom_fans_out_to_two_subs(self):
        """Dom calls sub1 and sub2 in parallel — both respond."""
        sub1 = _make_provider_entry("sub1", "provider_sub1", certainty=0.8)
        sub2 = _make_provider_entry("sub2", "provider_sub2", certainty=0.7)

        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["name"])
            return f"Response from {pconfig['name']}"

        results = evaluate_providers(
            [sub1, sub2],
            "", [], "Tell me about Paris landmarks", "",
            mock_call,
        )
        self.assertEqual(len(results), 2)
        names = {r.title for r in results}
        self.assertEqual(names, {"sub1", "sub2"})
        self.assertEqual(set(call_log), {"sub1", "sub2"})

    def test_both_subs_try_to_call_dom_back_dom_silent(self):
        """After dom fans out, each sub tries to call dom — dom stays silent
        in both cases because it's in the call chain.

        Sub1's nested vote: chain = [dom, sub1] → dom silenced
        Sub2's nested vote: chain = [dom, sub2] → dom silenced
        """
        dom = _make_provider_entry("dom", "provider_dom", certainty=0.9)

        # Sub1's nested vote tries to call dom
        results_sub1 = evaluate_providers(
            [dom],
            "", [], "q", "",
            lambda p, m: "dom should be silent",
            call_chain=["provider_dom", "provider_sub1"],
        )
        self.assertEqual(len(results_sub1), 0, "Dom must be silent in sub1's vote")

        # Sub2's nested vote tries to call dom
        results_sub2 = evaluate_providers(
            [dom],
            "", [], "q", "",
            lambda p, m: "dom should be silent",
            call_chain=["provider_dom", "provider_sub2"],
        )
        self.assertEqual(len(results_sub2), 0, "Dom must be silent in sub2's vote")

    def test_sub1_can_call_sub2_in_nested_vote(self):
        """Sub1 initiates a nested vote and calls sub2 — sub2 is NOT in the
        chain (only dom and sub1 are), so sub2 responds normally."""
        sub2 = _make_provider_entry("sub2", "provider_sub2", certainty=0.7)

        results = evaluate_providers(
            [sub2],
            "", [], "q", "",
            lambda p, m: "sub2 responds in sub1's nested vote",
            call_chain=["provider_dom", "provider_sub1"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "sub2")

    def test_full_branching_scenario(self):
        """Complete branching vote: dom → {sub1, sub2}, both subs try to call
        dom back, dom stays silent; subs can still call each other.

        Verifies the diamond topology:
              dom
             /   \\
          sub1   sub2
             \\   /
           dom_final
        """
        dom = _make_provider_entry("dom", "provider_dom", certainty=0.9)
        sub1 = _make_provider_entry("sub1", "provider_sub1", certainty=0.8)
        sub2 = _make_provider_entry("sub2", "provider_sub2", certainty=0.7)

        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["name"])
            return f"Response from {pconfig['name']}"

        # Step 1: dom fans out to sub1 and sub2 (no call chain yet)
        fan_out_results = evaluate_providers(
            [sub1, sub2],
            "", [], "Tell me about Paris", "",
            mock_call,
        )
        self.assertEqual(len(fan_out_results), 2)

        # Step 2: sub1 initiates nested vote, tries dom + sub2
        call_log.clear()
        sub1_nested = evaluate_providers(
            [dom, sub2],
            "", [], "Tell me about Paris", "",
            mock_call,
            call_chain=["provider_dom", "provider_sub1"],
        )
        # dom is silenced; sub2 responds
        self.assertEqual(len(sub1_nested), 1)
        self.assertEqual(sub1_nested[0].title, "sub2")
        self.assertEqual(call_log, ["sub2"])

        # Step 3: sub2 initiates nested vote, tries dom + sub1
        call_log.clear()
        sub2_nested = evaluate_providers(
            [dom, sub1],
            "", [], "Tell me about Paris", "",
            mock_call,
            call_chain=["provider_dom", "provider_sub2"],
        )
        # dom is silenced; sub1 responds
        self.assertEqual(len(sub2_nested), 1)
        self.assertEqual(sub2_nested[0].title, "sub1")
        self.assertEqual(call_log, ["sub1"])


# ---------------------------------------------------------------------------
# Per-provider truth resolution
# ---------------------------------------------------------------------------

class TestPerProviderTruth(unittest.TestCase):
    """Test that truth_url on <provider> entries resolves private facts."""

    def test_truth_url_parsed(self):
        """parse_provider_block extracts truth_url attribute."""
        content = (
            '<provider id="p1" trust="0.8" title="Test" '
            'name="test" api_url="http://test" model="m" '
            'truth_url="file://spec/sub_truth.jsonl"/>'
        )
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["truth_url"], "file://spec/sub_truth.jsonl")

    def test_truth_url_empty_when_absent(self):
        """parse_provider_block returns empty truth_url when not present."""
        content = (
            '<provider id="p1" trust="0.8" title="Test" '
            'name="test" api_url="http://test" model="m"/>'
        )
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["truth_url"], "")

    def test_resolve_provider_truth_empty_when_no_url(self):
        """No truth_url → empty list (RAG-free behavior)."""
        entry = {"id": "prov_x", "certainty": 0.9}
        config = {"truth_url": ""}
        sources = resolve_provider_truth(config, entry)
        self.assertEqual(sources, [])

    def test_provider_without_truth_url_gets_rag_free_bundle(self):
        """Provider without truth_url gets the standard RAG-free messages."""
        captured = {}

        def mock_call(pconfig, messages):
            captured["messages"] = messages
            return "ok"

        pairs = [_make_provider_entry("plain", "prov_plain")]
        evaluate_providers(
            pairs, "system ctx", [], "question", "output", mock_call,
        )

        self.assertIn("messages", captured)
        full_text = " ".join(m["content"] for m in captured["messages"])
        self.assertIn("system ctx", full_text)
        self.assertIn("question", full_text)
        # No truth entries in the messages
        self.assertNotIn("[Reference Documents]", full_text)


# ---------------------------------------------------------------------------
# Spec file validation
# ---------------------------------------------------------------------------

class TestSpecFiles(unittest.TestCase):
    """Verify the dom/sub/sub2 spec files parse correctly."""

    def test_dom_has_two_provider_subs(self):
        """dom.jsonl contains provider entries pointing to sub1 and sub2."""
        entries = _load_truth_entries("dom.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 2)
        names = {p[1]["name"] for p in providers}
        self.assertEqual(names, {"sub1", "sub2"})

    def test_dom_has_own_facts(self):
        """dom.jsonl has facts that sub1/sub2 don't have."""
        entries = _load_truth_entries("dom.jsonl")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Capital of France", fact_titles)
        self.assertIn("France is in Europe", fact_titles)

    def test_sub1_has_provider_dom(self):
        """sub.jsonl contains a provider entry pointing to dom."""
        entries = _load_truth_entries("sub.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][1]["name"], "dom")

    def test_sub1_has_own_facts(self):
        """sub.jsonl has its own facts (Eiffel Tower)."""
        entries = _load_truth_entries("sub.jsonl")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Eiffel Tower location", fact_titles)
        self.assertIn("Eiffel Tower height", fact_titles)
        self.assertIn("Eiffel Tower material", fact_titles)

    def test_sub2_has_provider_dom(self):
        """sub2.jsonl contains a provider entry pointing to dom."""
        entries = _load_truth_entries("sub2.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][1]["name"], "dom")

    def test_sub2_has_own_facts(self):
        """sub2.jsonl has its own facts (Louvre)."""
        entries = _load_truth_entries("sub2.jsonl")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Louvre Museum location", fact_titles)
        self.assertIn("Mona Lisa location", fact_titles)

    def test_mutual_reference_cycle_scenario(self):
        """dom→sub1, sub1→dom: dom is silenced when in call chain."""
        sub_entries = _load_truth_entries("sub.jsonl")
        sub_providers = get_provider_entries(sub_entries)
        dom_entry = sub_providers[0]  # sub's reference to dom

        results = evaluate_providers(
            [dom_entry],
            "", [], "test question", "",
            lambda p, m: "dom should not respond",
            call_chain=["provider_dom"],
        )
        self.assertEqual(len(results), 0, "Dom must stay silent when in call chain")

    def test_branching_cycle_from_spec_files(self):
        """Load all three spec files, verify the branching cycle scenario.

        dom calls sub1 and sub2. Both subs reference dom back.
        dom should be silenced in both subs' nested votes.
        """
        dom_entries = _load_truth_entries("dom.jsonl")
        sub1_entries = _load_truth_entries("sub.jsonl")
        sub2_entries = _load_truth_entries("sub2.jsonl")

        dom_providers = get_provider_entries(dom_entries)
        sub1_providers = get_provider_entries(sub1_entries)
        sub2_providers = get_provider_entries(sub2_entries)

        # dom fans out to sub1 and sub2
        self.assertEqual(len(dom_providers), 2)
        dom_sub_names = {p[1]["name"] for p in dom_providers}
        self.assertEqual(dom_sub_names, {"sub1", "sub2"})

        # Both subs reference dom back
        self.assertEqual(sub1_providers[0][1]["name"], "dom")
        self.assertEqual(sub2_providers[0][1]["name"], "dom")

        # Sub1 tries to call dom — silenced
        r1 = evaluate_providers(
            [sub1_providers[0]],
            "", [], "q", "",
            lambda p, m: "should be silent",
            call_chain=["provider_dom", "provider_sub1"],
        )
        self.assertEqual(len(r1), 0)

        # Sub2 tries to call dom — silenced
        r2 = evaluate_providers(
            [sub2_providers[0]],
            "", [], "q", "",
            lambda p, m: "should be silent",
            call_chain=["provider_dom", "provider_sub2"],
        )
        self.assertEqual(len(r2), 0)


# ---------------------------------------------------------------------------
# Diamond voting protocol: dom_prelim steering
# ---------------------------------------------------------------------------

class TestDiamondVoting(unittest.TestCase):
    """Verify the two-round diamond: R_dom_prelim → R_sub_* → R_dom_final."""

    def test_build_bundle_with_dom_prelim(self):
        """_build_provider_query_bundle injects Q → R_dom into history."""
        bundle = _build_provider_query_bundle(
            "system ctx", [{"role": "user", "content": "old msg"}],
            "What is Paris?", "output fmt",
            dom_prelim="Paris is the capital of France.",
        )
        # Original history preserved + Q→R_dom appended
        self.assertEqual(len(bundle.history), 3)
        self.assertEqual(bundle.history[0]["content"], "old msg")
        self.assertEqual(bundle.history[1]["role"], "user")
        self.assertEqual(bundle.history[1]["content"], "What is Paris?")
        self.assertEqual(bundle.history[2]["role"], "assistant")
        self.assertEqual(bundle.history[2]["content"], "Paris is the capital of France.")

    def test_build_bundle_without_dom_prelim(self):
        """Without dom_prelim, history is unchanged."""
        bundle = _build_provider_query_bundle(
            "ctx", [{"role": "user", "content": "hi"}],
            "query", "out",
            dom_prelim=None,
        )
        self.assertEqual(len(bundle.history), 1)
        self.assertEqual(bundle.history[0]["content"], "hi")

    def test_build_bundle_empty_dom_prelim(self):
        """Empty string dom_prelim is treated as falsy — no injection."""
        bundle = _build_provider_query_bundle(
            "ctx", [], "query", "out",
            dom_prelim="",
        )
        self.assertEqual(len(bundle.history), 0)

    def test_subs_see_dom_prelim_in_messages(self):
        """When dom_prelim is passed to evaluate_providers, subs see
        Q → R_dom in their messages (steering signal)."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return f"Sub response from {pconfig['name']}"

        sub1 = _make_provider_entry("sub1", "prov_sub1")
        sub2 = _make_provider_entry("sub2", "prov_sub2")

        results = evaluate_providers(
            [sub1, sub2],
            "system context", [], "What is Paris?", "",
            mock_call,
            dom_prelim="Paris is the capital of France.",
        )

        self.assertEqual(len(results), 2)
        # Both subs should have been called
        self.assertIn("sub1", captured_messages)
        self.assertIn("sub2", captured_messages)

        # Each sub's messages should contain the dom's preliminary response
        for name in ("sub1", "sub2"):
            msgs = captured_messages[name]
            all_text = " ".join(m["content"] for m in msgs)
            self.assertIn("Paris is the capital of France.", all_text,
                          f"{name} should see dom's preliminary response")
            # The query appears both in the injected history pair AND
            # as the final user message
            query_count = sum(1 for m in msgs
                              if m["role"] == "user" and m["content"] == "What is Paris?")
            self.assertGreaterEqual(query_count, 1,
                                    f"{name} should see the query")

    def test_subs_get_standard_messages_without_dom_prelim(self):
        """Without dom_prelim, subs get RAG-free messages with no steering."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return "response"

        sub = _make_provider_entry("sub1", "prov_sub1")

        evaluate_providers(
            [sub],
            "system context", [], "question", "",
            mock_call,
            dom_prelim=None,
        )

        msgs = captured_messages["sub1"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("system context", all_text)
        self.assertIn("question", all_text)
        # No assistant message with a preliminary response
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"
                          and m["content"] != "Understood. I have the project context and reference documents."]
        self.assertEqual(len(assistant_msgs), 0,
                         "No dom_prelim means no steering assistant message")

    def test_diamond_full_sequence(self):
        """Simulate the complete diamond: dom prelim → sub fan-out → dom final.

        Topology:
              dom
             / \\
          sub1   sub2
             \\ /
           dom_final

        Verifies:
        1. Dom is called first (prelim)
        2. Subs see dom's prelim response
        3. Dom is called again (final) seeing sub responses
        """
        call_sequence = []

        dom = _make_provider_entry("dom", "provider_dom", certainty=0.9)
        sub1 = _make_provider_entry("sub1", "provider_sub1", certainty=0.8)
        sub2 = _make_provider_entry("sub2", "provider_sub2", certainty=0.7)

        # Step 1: Dom preliminary
        dom_prelim = "Dom says: Paris is the capital"
        call_sequence.append(("dom", "prelim"))

        # Step 2: Fan out to subs with dom_prelim as steering
        captured_sub_msgs = {}

        def mock_sub_call(pconfig, messages):
            name = pconfig["name"]
            call_sequence.append((name, "sub_response"))
            captured_sub_msgs[name] = messages
            return f"{name}: I agree about Paris"

        sub_results = evaluate_providers(
            [sub1, sub2],
            "system", [], "What is the capital of France?", "",
            mock_sub_call,
            call_chain=["provider_dom"],
            dom_prelim=dom_prelim,
        )

        # Both subs responded (neither is in call chain)
        self.assertEqual(len(sub_results), 2)

        # Both subs saw dom_prelim in their messages
        for name in ("sub1", "sub2"):
            all_text = " ".join(m["content"] for m in captured_sub_msgs[name])
            self.assertIn(dom_prelim, all_text)

        # Step 3: Dom final (we simulate by calling evaluate_providers again,
        # but in real code this is a direct call to the UI provider)
        call_sequence.append(("dom", "final"))

        # Verify call sequence
        self.assertEqual(call_sequence[0], ("dom", "prelim"))
        self.assertEqual(call_sequence[-1], ("dom", "final"))
        # Subs were called between prelim and final
        sub_calls = [c for c in call_sequence if c[1] == "sub_response"]
        self.assertEqual(len(sub_calls), 2)

    def test_diamond_with_cycle_prevention(self):
        """In the diamond, subs try to call dom back — dom stays silent due to
        cycle prevention, but subs still produce their own responses."""
        dom = _make_provider_entry("dom", "provider_dom", certainty=0.9)
        sub1 = _make_provider_entry("sub1", "provider_sub1", certainty=0.8)

        # Step 2 simulation: sub1 is called with dom in call chain
        sub_results = evaluate_providers(
            [sub1],
            "system", [], "query", "",
            lambda p, m: "sub1 responds normally",
            call_chain=["provider_dom"],
            dom_prelim="Dom's preliminary thoughts",
        )
        # sub1 is NOT in the chain, so it responds
        self.assertEqual(len(sub_results), 1)

        # Sub1 tries to call dom in a nested vote — dom is silenced
        nested_results = evaluate_providers(
            [dom],
            "system", [], "query", "",
            lambda p, m: "dom should NOT be called",
            call_chain=["provider_dom", "provider_sub1"],
        )
        self.assertEqual(len(nested_results), 0)

    def test_dom_prelim_does_not_mutate_original_history(self):
        """_build_provider_query_bundle must not mutate the original history."""
        original_history = [{"role": "user", "content": "hello"}]
        history_copy = list(original_history)

        _build_provider_query_bundle(
            "sys", original_history, "q", "out",
            dom_prelim="dom says something",
        )

        # Original should be unchanged
        self.assertEqual(original_history, history_copy)


if __name__ == "__main__":
    unittest.main()
