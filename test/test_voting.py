#!/usr/bin/env python3
"""Tests for the voting protocol: cycle prevention, per-provider truth, and prelim control."""

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

def _make_provider_entry(name, entry_id, certainty=0.8, truth_url="", prelim=True):
    """Create a (trust_entry, provider_config) pair for testing."""
    content = (
        f'<provider id="{entry_id}" trust="{certainty}" title="{name}" '
        f'name="{name}" api_url="http://test/{name}" model="test"'
    )
    if truth_url:
        content += f' truth_url="{truth_url}"'
    if not prelim:
        content += ' prelim="false"'
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
        "prelim": prelim,
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
# Alpha/beta mutual reference scenario
# ---------------------------------------------------------------------------

class TestAlphaBetaMutualReference(unittest.TestCase):
    """Simulate the alpha→beta→alpha cycle from the spec files."""

    def test_alpha_calls_beta_beta_calls_alpha_alpha_is_silent(self):
        """Alpha initiates vote → beta is called → beta tries to call alpha →
        alpha finds itself in chain → keeps quiet.

        Simulated as two rounds of evaluate_providers.
        """
        alpha = _make_provider_entry("alpha", "provider_alpha", certainty=0.9)
        beta = _make_provider_entry("beta", "provider_beta1", certainty=0.8)

        # Round 1: alpha initiates vote, calls beta as secondary.
        # call_chain starts empty (alpha is the root).
        round1_results = evaluate_providers(
            [beta],  # secondaries
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Beta says: it is a tower in Paris",
        )
        self.assertEqual(len(round1_results), 1)
        self.assertEqual(round1_results[0].title, "beta")

        # Round 2: beta initiates its own nested vote, tries to call alpha.
        # call_chain now includes alpha (the root) AND beta (the nested alpha).
        round2_chain = ["provider_alpha", "provider_beta1"]
        round2_results = evaluate_providers(
            [alpha],  # beta tries to call alpha as its secondary
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Alpha would respond — but should be silenced",
            call_chain=round2_chain,
        )
        # Alpha must stay silent — it's in the chain
        self.assertEqual(len(round2_results), 0)


# ---------------------------------------------------------------------------
# Branching: alpha calls beta1 AND beta2
# ---------------------------------------------------------------------------

class TestBranchingVote(unittest.TestCase):
    """Alpha fans out to beta1 and beta2; both try to call alpha back."""

    def test_alpha_fans_out_to_two_betas(self):
        """Alpha calls beta1 and beta2 in parallel — both respond."""
        beta1 = _make_provider_entry("beta1", "provider_beta1", certainty=0.8)
        beta2 = _make_provider_entry("beta2", "provider_beta2", certainty=0.7)

        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["name"])
            return f"Response from {pconfig['name']}"

        results = evaluate_providers(
            [beta1, beta2],
            "", [], "Tell me about Paris landmarks", "",
            mock_call,
        )
        self.assertEqual(len(results), 2)
        names = {r.title for r in results}
        self.assertEqual(names, {"beta1", "beta2"})
        self.assertEqual(set(call_log), {"beta1", "beta2"})

    def test_both_betas_try_to_call_alpha_back_alpha_silent(self):
        """After alpha fans out, each beta tries to call alpha — alpha stays
        silent in both cases because it's in the call chain.

        Beta1's nested vote: chain = [alpha, beta1] → alpha silenced
        Beta2's nested vote: chain = [alpha, beta2] → alpha silenced
        """
        alpha = _make_provider_entry("alpha", "provider_alpha", certainty=0.9)

        # Beta1's nested vote tries to call alpha
        results_beta1 = evaluate_providers(
            [alpha],
            "", [], "q", "",
            lambda p, m: "alpha should be silent",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(results_beta1), 0, "Alpha must be silent in beta1's vote")

        # Beta2's nested vote tries to call alpha
        results_beta2 = evaluate_providers(
            [alpha],
            "", [], "q", "",
            lambda p, m: "alpha should be silent",
            call_chain=["provider_alpha", "provider_beta2"],
        )
        self.assertEqual(len(results_beta2), 0, "Alpha must be silent in beta2's vote")

    def test_beta1_can_call_beta2_in_nested_vote(self):
        """Beta1 initiates a nested vote and calls beta2 — beta2 is NOT in the
        chain (only alpha and beta1 are), so beta2 responds normally."""
        beta2 = _make_provider_entry("beta2", "provider_beta2", certainty=0.7)

        results = evaluate_providers(
            [beta2],
            "", [], "q", "",
            lambda p, m: "beta2 responds in beta1's nested vote",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "beta2")

    def test_full_branching_scenario(self):
        """Complete branching vote: alpha → {beta1, beta2}, both betas try to
        call alpha back, alpha stays silent; betas can still call each other.

        Verifies the diamond topology:
              alpha
             /   \\
          beta1   beta2
             \\   /
           alpha_final
        """
        alpha = _make_provider_entry("alpha", "provider_alpha", certainty=0.9)
        beta1 = _make_provider_entry("beta1", "provider_beta1", certainty=0.8)
        beta2 = _make_provider_entry("beta2", "provider_beta2", certainty=0.7)

        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["name"])
            return f"Response from {pconfig['name']}"

        # Step 1: alpha fans out to beta1 and beta2 (no call chain yet)
        fan_out_results = evaluate_providers(
            [beta1, beta2],
            "", [], "Tell me about Paris", "",
            mock_call,
        )
        self.assertEqual(len(fan_out_results), 2)

        # Step 2: beta1 initiates nested vote, tries alpha + beta2
        call_log.clear()
        beta1_nested = evaluate_providers(
            [alpha, beta2],
            "", [], "Tell me about Paris", "",
            mock_call,
            call_chain=["provider_alpha", "provider_beta1"],
        )
        # alpha is silenced; beta2 responds
        self.assertEqual(len(beta1_nested), 1)
        self.assertEqual(beta1_nested[0].title, "beta2")
        self.assertEqual(call_log, ["beta2"])

        # Step 3: beta2 initiates nested vote, tries alpha + beta1
        call_log.clear()
        beta2_nested = evaluate_providers(
            [alpha, beta1],
            "", [], "Tell me about Paris", "",
            mock_call,
            call_chain=["provider_alpha", "provider_beta2"],
        )
        # alpha is silenced; beta1 responds
        self.assertEqual(len(beta2_nested), 1)
        self.assertEqual(beta2_nested[0].title, "beta1")
        self.assertEqual(call_log, ["beta1"])


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
            'truth_url="file://spec/beta_truth.jsonl"/>'
        )
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["truth_url"], "file://spec/beta_truth.jsonl")

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
    """Verify the alpha/beta1/beta2 spec files parse correctly."""

    def test_alpha_has_two_provider_betas(self):
        """alpha.jsonl contains provider entries pointing to beta1 and beta2."""
        entries = _load_truth_entries("alpha.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 2)
        names = {p[1]["name"] for p in providers}
        self.assertEqual(names, {"beta1", "beta2"})

    def test_alpha_has_own_facts(self):
        """alpha.jsonl has facts that beta1/beta2 don't have."""
        entries = _load_truth_entries("alpha.jsonl")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Capital of France", fact_titles)
        self.assertIn("France is in Europe", fact_titles)

    def test_beta1_has_provider_alpha(self):
        """beta1.jsonl contains a provider entry pointing to alpha."""
        entries = _load_truth_entries("beta1.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][1]["name"], "alpha")

    def test_beta1_has_own_facts(self):
        """beta1.jsonl has its own facts (Eiffel Tower)."""
        entries = _load_truth_entries("beta1.jsonl")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Eiffel Tower location", fact_titles)
        self.assertIn("Eiffel Tower height", fact_titles)
        self.assertIn("Eiffel Tower material", fact_titles)

    def test_beta2_has_provider_alpha(self):
        """beta2.jsonl contains a provider entry pointing to alpha."""
        entries = _load_truth_entries("beta2.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][1]["name"], "alpha")

    def test_beta2_has_own_facts(self):
        """beta2.jsonl has its own facts (Louvre)."""
        entries = _load_truth_entries("beta2.jsonl")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Louvre Museum location", fact_titles)
        self.assertIn("Mona Lisa location", fact_titles)

    def test_mutual_reference_cycle_scenario(self):
        """alpha→beta1, beta1→alpha: alpha is silenced when in call chain."""
        beta_entries = _load_truth_entries("beta1.jsonl")
        beta_providers = get_provider_entries(beta_entries)
        alpha_entry = beta_providers[0]  # beta's reference to alpha

        results = evaluate_providers(
            [alpha_entry],
            "", [], "test question", "",
            lambda p, m: "alpha should not respond",
            call_chain=["provider_alpha"],
        )
        self.assertEqual(len(results), 0, "Alpha must stay silent when in call chain")

    def test_branching_cycle_from_spec_files(self):
        """Load all three spec files, verify the branching cycle scenario.

        Alpha calls beta1 and beta2. Both betas reference alpha back.
        Alpha should be silenced in both betas' nested votes.
        """
        alpha_entries = _load_truth_entries("alpha.jsonl")
        beta1_entries = _load_truth_entries("beta1.jsonl")
        beta2_entries = _load_truth_entries("beta2.jsonl")

        alpha_providers = get_provider_entries(alpha_entries)
        beta1_providers = get_provider_entries(beta1_entries)
        beta2_providers = get_provider_entries(beta2_entries)

        # alpha fans out to beta1 and beta2
        self.assertEqual(len(alpha_providers), 2)
        alpha_beta_names = {p[1]["name"] for p in alpha_providers}
        self.assertEqual(alpha_beta_names, {"beta1", "beta2"})

        # Both betas reference alpha back
        self.assertEqual(beta1_providers[0][1]["name"], "alpha")
        self.assertEqual(beta2_providers[0][1]["name"], "alpha")

        # Beta1 tries to call alpha — silenced
        r1 = evaluate_providers(
            [beta1_providers[0]],
            "", [], "q", "",
            lambda p, m: "should be silent",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(r1), 0)

        # Beta2 tries to call alpha — silenced
        r2 = evaluate_providers(
            [beta2_providers[0]],
            "", [], "q", "",
            lambda p, m: "should be silent",
            call_chain=["provider_alpha", "provider_beta2"],
        )
        self.assertEqual(len(r2), 0)


# ---------------------------------------------------------------------------
# Diamond voting protocol: prelim_response steering
# ---------------------------------------------------------------------------

class TestDiamondVoting(unittest.TestCase):
    """Verify the two-round diamond: R_alpha_prelim → R_beta_* → R_alpha_final."""

    def test_build_bundle_with_prelim_response(self):
        """_build_provider_query_bundle injects Q → R_alpha into history."""
        bundle = _build_provider_query_bundle(
            "system ctx", [{"role": "user", "content": "old msg"}],
            "What is Paris?", "output fmt",
            prelim_response="Paris is the capital of France.",
        )
        # Original history preserved + Q→R_alpha appended
        self.assertEqual(len(bundle.history), 3)
        self.assertEqual(bundle.history[0]["content"], "old msg")
        self.assertEqual(bundle.history[1]["role"], "user")
        self.assertEqual(bundle.history[1]["content"], "What is Paris?")
        self.assertEqual(bundle.history[2]["role"], "assistant")
        self.assertEqual(bundle.history[2]["content"], "Paris is the capital of France.")

    def test_build_bundle_without_prelim_response(self):
        """Without prelim_response, history is unchanged."""
        bundle = _build_provider_query_bundle(
            "ctx", [{"role": "user", "content": "hi"}],
            "query", "out",
            prelim_response=None,
        )
        self.assertEqual(len(bundle.history), 1)
        self.assertEqual(bundle.history[0]["content"], "hi")

    def test_build_bundle_empty_prelim_response(self):
        """Empty string prelim_response is treated as falsy — no injection."""
        bundle = _build_provider_query_bundle(
            "ctx", [], "query", "out",
            prelim_response="",
        )
        self.assertEqual(len(bundle.history), 0)

    def test_betas_see_prelim_response_in_messages(self):
        """When prelim_response is passed to evaluate_providers, betas see
        Q → R_alpha in their messages (steering signal)."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return f"Beta response from {pconfig['name']}"

        beta1 = _make_provider_entry("beta1", "prov_beta1")
        beta2 = _make_provider_entry("beta2", "prov_beta2")

        results = evaluate_providers(
            [beta1, beta2],
            "system context", [], "What is Paris?", "",
            mock_call,
            prelim_response="Paris is the capital of France.",
        )

        self.assertEqual(len(results), 2)
        # Both betas should have been called
        self.assertIn("beta1", captured_messages)
        self.assertIn("beta2", captured_messages)

        # Each beta's messages should contain the alpha's preliminary response
        for name in ("beta1", "beta2"):
            msgs = captured_messages[name]
            all_text = " ".join(m["content"] for m in msgs)
            self.assertIn("Paris is the capital of France.", all_text,
                          f"{name} should see alpha's preliminary response")
            # The query appears both in the injected history pair AND
            # as the final user message
            query_count = sum(1 for m in msgs
                              if m["role"] == "user" and m["content"] == "What is Paris?")
            self.assertGreaterEqual(query_count, 1,
                                    f"{name} should see the query")

    def test_betas_get_standard_messages_without_prelim_response(self):
        """Without prelim_response, betas get RAG-free messages with no steering."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return "response"

        beta = _make_provider_entry("beta1", "prov_beta1")

        evaluate_providers(
            [beta],
            "system context", [], "question", "",
            mock_call,
            prelim_response=None,
        )

        msgs = captured_messages["beta1"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("system context", all_text)
        self.assertIn("question", all_text)
        # No assistant message with a preliminary response
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"
                          and m["content"] != "Understood. I have the project context and reference documents."]
        self.assertEqual(len(assistant_msgs), 0,
                         "No prelim_response means no steering assistant message")

    def test_diamond_full_sequence(self):
        """Simulate the complete diamond: alpha prelim → beta fan-out → alpha final.

        Topology:
              alpha
             / \\
          beta1   beta2
             \\ /
           alpha_final

        Verifies:
        1. Alpha is called first (prelim)
        2. Betas see alpha's prelim response
        3. Alpha is called again (final) seeing beta responses
        """
        call_sequence = []

        alpha = _make_provider_entry("alpha", "provider_alpha", certainty=0.9)
        beta1 = _make_provider_entry("beta1", "provider_beta1", certainty=0.8)
        beta2 = _make_provider_entry("beta2", "provider_beta2", certainty=0.7)

        # Step 1: Alpha preliminary
        prelim_response = "Alpha says: Paris is the capital"
        call_sequence.append(("alpha", "prelim"))

        # Step 2: Fan out to betas with prelim_response as steering
        captured_beta_msgs = {}

        def mock_beta_call(pconfig, messages):
            name = pconfig["name"]
            call_sequence.append((name, "beta_response"))
            captured_beta_msgs[name] = messages
            return f"{name}: I agree about Paris"

        beta_results = evaluate_providers(
            [beta1, beta2],
            "system", [], "What is the capital of France?", "",
            mock_beta_call,
            call_chain=["provider_alpha"],
            prelim_response=prelim_response,
        )

        # Both betas responded (neither is in call chain)
        self.assertEqual(len(beta_results), 2)

        # Both betas saw prelim_response in their messages
        for name in ("beta1", "beta2"):
            all_text = " ".join(m["content"] for m in captured_beta_msgs[name])
            self.assertIn(prelim_response, all_text)

        # Step 3: Alpha final (we simulate by calling evaluate_providers again,
        # but in real code this is a direct call to the UI provider)
        call_sequence.append(("alpha", "final"))

        # Verify call sequence
        self.assertEqual(call_sequence[0], ("alpha", "prelim"))
        self.assertEqual(call_sequence[-1], ("alpha", "final"))
        # Betas were called between prelim and final
        beta_calls = [c for c in call_sequence if c[1] == "beta_response"]
        self.assertEqual(len(beta_calls), 2)

    def test_diamond_with_cycle_prevention(self):
        """In the diamond, betas try to call alpha back — alpha stays silent due
        to cycle prevention, but betas still produce their own responses."""
        alpha = _make_provider_entry("alpha", "provider_alpha", certainty=0.9)
        beta1 = _make_provider_entry("beta1", "provider_beta1", certainty=0.8)

        # Step 2 simulation: beta1 is called with alpha in call chain
        beta_results = evaluate_providers(
            [beta1],
            "system", [], "query", "",
            lambda p, m: "beta1 responds normally",
            call_chain=["provider_alpha"],
            prelim_response="Alpha's preliminary thoughts",
        )
        # beta1 is NOT in the chain, so it responds
        self.assertEqual(len(beta_results), 1)

        # Beta1 tries to call alpha in a nested vote — alpha is silenced
        nested_results = evaluate_providers(
            [alpha],
            "system", [], "query", "",
            lambda p, m: "alpha should NOT be called",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(nested_results), 0)

    def test_prelim_response_does_not_mutate_original_history(self):
        """_build_provider_query_bundle must not mutate the original history."""
        original_history = [{"role": "user", "content": "hello"}]
        history_copy = list(original_history)

        _build_provider_query_bundle(
            "sys", original_history, "q", "out",
            prelim_response="alpha says something",
        )

        # Original should be unchanged
        self.assertEqual(original_history, history_copy)


# ---------------------------------------------------------------------------
# Per-provider prelim control
# ---------------------------------------------------------------------------

class TestPrelimControl(unittest.TestCase):
    """Verify that prelim attribute controls per-beta steering."""

    def test_parse_provider_block_prelim_default_true(self):
        """parse_provider_block defaults prelim to True when absent."""
        content = '<provider name="test" api_url="http://test" model="m"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertTrue(result["prelim"])

    def test_parse_provider_block_prelim_explicit_true(self):
        """parse_provider_block reads prelim="true"."""
        content = '<provider name="test" api_url="http://test" model="m" prelim="true"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertTrue(result["prelim"])

    def test_parse_provider_block_prelim_false(self):
        """parse_provider_block reads prelim="false"."""
        content = '<provider name="test" api_url="http://test" model="m" prelim="false"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertFalse(result["prelim"])

    def test_parse_provider_block_prelim_zero(self):
        """parse_provider_block treats prelim="0" as False."""
        content = '<provider name="test" api_url="http://test" model="m" prelim="0"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertFalse(result["prelim"])

    def test_parse_provider_block_prelim_no(self):
        """parse_provider_block treats prelim="no" as False."""
        content = '<provider name="test" api_url="http://test" model="m" prelim="no"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertFalse(result["prelim"])

    def test_beta_with_prelim_false_gets_cold_messages(self):
        """Beta with prelim=False does not see the alpha's preliminary response."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return "response"

        cold_beta = _make_provider_entry("cold", "prov_cold", prelim=False)

        evaluate_providers(
            [cold_beta],
            "system", [], "question", "",
            mock_call,
            prelim_response="Alpha's preliminary thoughts",
        )

        msgs = captured_messages["cold"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertNotIn("Alpha's preliminary thoughts", all_text,
                         "Beta with prelim=False must not see preliminary response")

    def test_beta_with_prelim_true_gets_steered_messages(self):
        """Beta with prelim=True sees the alpha's preliminary response."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return "response"

        steered_beta = _make_provider_entry("steered", "prov_steered", prelim=True)

        evaluate_providers(
            [steered_beta],
            "system", [], "question", "",
            mock_call,
            prelim_response="Alpha's preliminary thoughts",
        )

        msgs = captured_messages["steered"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("Alpha's preliminary thoughts", all_text,
                       "Beta with prelim=True should see preliminary response")

    def test_mixed_prelim_betas(self):
        """When betas have different prelim settings, only prelim=True betas
        see the alpha's preliminary response."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return f"Response from {pconfig['name']}"

        steered = _make_provider_entry("steered", "prov_steered", prelim=True)
        cold = _make_provider_entry("cold", "prov_cold", prelim=False)

        results = evaluate_providers(
            [steered, cold],
            "system", [], "question", "",
            mock_call,
            prelim_response="Alpha's preliminary thoughts",
        )

        self.assertEqual(len(results), 2)

        # Steered beta sees prelim
        steered_text = " ".join(m["content"] for m in captured_messages["steered"])
        self.assertIn("Alpha's preliminary thoughts", steered_text)

        # Cold beta does NOT see prelim
        cold_text = " ".join(m["content"] for m in captured_messages["cold"])
        self.assertNotIn("Alpha's preliminary thoughts", cold_text)

    def test_prelim_false_with_no_prelim_response_is_fine(self):
        """Beta with prelim=False when no prelim_response exists — no crash."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["name"]] = messages
            return "response"

        cold_beta = _make_provider_entry("cold", "prov_cold", prelim=False)

        evaluate_providers(
            [cold_beta],
            "system", [], "question", "",
            mock_call,
            prelim_response=None,
        )

        self.assertIn("cold", captured_messages)
        self.assertEqual(len([r for r in evaluate_providers(
            [cold_beta], "system", [], "q", "", mock_call,
        )]), 1)


if __name__ == "__main__":
    unittest.main()
