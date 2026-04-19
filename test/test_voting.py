#!/usr/bin/env python3
"""Tests for the voting protocol: cycle prevention, per-provider truth, and conversation control."""

import json
import sys
import unittest
from pathlib import Path

# Ensure bin/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from response import (
    Source,
    _build_bundle,
    _build_provider_query_bundle,
    _build_truth_provider_bundle,
    _build_conversation_provider_bundle,
    direct_truth_sources,
    evaluate_providers,
    resolve_provider_truth,
    static_truth,
    to_nanochat_messages,
)
from truth import (
    _normalize_trust_entry,
    _parse_root_attrs,
    get_provider_entries,
    parse_provider_block,
)


SPEC_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider_entry(name, entry_id, trust=0.8, authority_url="", conversation=False):
    """Create a (trust_entry, provider_config) pair for testing."""
    content = f'<provider api_url="http://test/{name}" model="test"'
    if conversation:
        content += ' conversation="true"'
    if authority_url:
        content += f'><authority url="{authority_url}"/></provider>'
    else:
        content += '/>'

    entry = {
        "id": entry_id,
        "title": name,
        "trust": trust,
        "time": "2026-03-01T00:00:00Z",
        "content": content,
    }
    config = {
        "api_url": f"http://test/{name}",
        "api_key": "k",
        "model": "test",
        "authority_url": authority_url,
        "conversation": conversation,
        "timeout": 30,
        "max_tokens": 1024,
    }
    return (entry, config)


def _load_truth_entries(filename):
    """Load truth entries from a spec XML file."""
    from state import load_state_file
    path = SPEC_DIR / filename
    state = load_state_file(path, strict=True)
    return state.get("truth", [])


# ---------------------------------------------------------------------------
# Cycle prevention tests
# ---------------------------------------------------------------------------

class TestVotingCyclePrevention(unittest.TestCase):
    """Verify that providers in the call chain stay silent."""

    def test_cycle_detected_direct(self):
        """Provider whose ID is in call_chain is silenced."""
        pairs = [_make_provider_entry("A", "prov_a", conversation=True)]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "response",
            call_chain=["prov_a"],
        )
        self.assertEqual(len(conv) + len(truths), 0)

    def test_cycle_detected_transitive(self):
        """Multiple providers in call_chain are all silenced."""
        pairs = [
            _make_provider_entry("A", "prov_a", conversation=True),
            _make_provider_entry("B", "prov_b", conversation=True),
        ]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "response",
            call_chain=["prov_a", "prov_b"],
        )
        self.assertEqual(len(conv) + len(truths), 0)

    def test_no_cycle_when_not_in_chain(self):
        """Provider NOT in call_chain is evaluated normally."""
        pairs = [_make_provider_entry("B", "prov_b", conversation=True)]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "response from B",
            call_chain=["prov_a"],
        )
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0].title, "B")
        self.assertIn("response from B", conv[0].content)

    def test_mixed_chain_and_free(self):
        """Only providers in the chain are silenced; others respond."""
        pairs = [
            _make_provider_entry("A", "prov_a", conversation=True),
            _make_provider_entry("B", "prov_b", conversation=True),
            _make_provider_entry("C", "prov_c", conversation=True),
        ]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: f"from {p['api_url']}",
            call_chain=["prov_a"],
        )
        self.assertEqual(len(conv), 2)
        names = {r.title for r in conv}
        self.assertEqual(names, {"B", "C"})

    def test_empty_call_chain_backward_compat(self):
        """With no call_chain, all providers are evaluated (backward compat)."""
        pairs = [_make_provider_entry("A", "prov_a", conversation=True)]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "ok",
        )
        self.assertEqual(len(conv), 1)

    def test_none_call_chain_backward_compat(self):
        """call_chain=None behaves the same as empty list."""
        pairs = [_make_provider_entry("A", "prov_a", conversation=True)]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "ok",
            call_chain=None,
        )
        self.assertEqual(len(conv), 1)

    def test_silence_not_counted_as_error(self):
        """Silenced provider produces no Source — it's not an error response."""
        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["api_url"])
            return "response"

        pairs = [_make_provider_entry("A", "prov_a", conversation=True)]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", mock_call,
            call_chain=["prov_a"],
        )
        # The call_fn should never be invoked for a silenced provider
        self.assertEqual(call_log, [])
        self.assertEqual(len(conv) + len(truths), 0)

    def test_deep_chain_exclusion(self):
        """A → B → C chain: all three excluded from a vote at depth 3."""
        pairs = [
            _make_provider_entry("A", "prov_a", conversation=True),
            _make_provider_entry("B", "prov_b", conversation=True),
            _make_provider_entry("C", "prov_c", conversation=True),
            _make_provider_entry("D", "prov_d", conversation=True),
        ]
        conv, truths = evaluate_providers(
            pairs, "", [], "q", "", lambda p, m: "ok",
            call_chain=["prov_a", "prov_b", "prov_c"],
        )
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0].title, "D")


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
        alpha = _make_provider_entry("alpha", "provider_alpha", trust=0.9, conversation=True)
        beta = _make_provider_entry("beta", "provider_beta1", trust=0.8, conversation=True)

        # Round 1: alpha initiates vote, calls beta as secondary.
        # call_chain starts empty (alpha is the root).
        conv, _ = evaluate_providers(
            [beta],  # secondaries
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Beta says: it is a tower in Paris",
        )
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0].title, "beta")

        # Round 2: beta initiates its own nested vote, tries to call alpha.
        # call_chain now includes alpha (the root) AND beta (the nested alpha).
        round2_chain = ["provider_alpha", "provider_beta1"]
        conv2, truths2 = evaluate_providers(
            [alpha],  # beta tries to call alpha as its secondary
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Alpha would respond — but should be silenced",
            call_chain=round2_chain,
        )
        # Alpha must stay silent — it's in the chain
        self.assertEqual(len(conv2) + len(truths2), 0)


# ---------------------------------------------------------------------------
# Branching: alpha calls beta1 AND beta2
# ---------------------------------------------------------------------------

class TestBranchingVote(unittest.TestCase):
    """Alpha fans out to beta1 and beta2; both try to call alpha back."""

    def test_alpha_fans_out_to_two_betas(self):
        """Alpha calls beta1 and beta2 in parallel — both respond."""
        beta1 = _make_provider_entry("beta1", "provider_beta1", trust=0.8, conversation=True)
        beta2 = _make_provider_entry("beta2", "provider_beta2", trust=0.7, conversation=True)

        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["api_url"])
            return f"Response from {pconfig['api_url']}"

        conv, _ = evaluate_providers(
            [beta1, beta2],
            "", [], "Tell me about Paris landmarks", "",
            mock_call,
        )
        self.assertEqual(len(conv), 2)
        names = {r.title for r in conv}
        self.assertEqual(names, {"beta1", "beta2"})
        self.assertEqual(set(call_log), {"http://test/beta1", "http://test/beta2"})

    def test_both_betas_try_to_call_alpha_back_alpha_silent(self):
        """After alpha fans out, each beta tries to call alpha — alpha stays
        silent in both cases because it's in the call chain.

        Beta1's nested vote: chain = [alpha, beta1] → alpha silenced
        Beta2's nested vote: chain = [alpha, beta2] → alpha silenced
        """
        alpha = _make_provider_entry("alpha", "provider_alpha", trust=0.9, conversation=True)

        # Beta1's nested vote tries to call alpha
        conv1, truths1 = evaluate_providers(
            [alpha],
            "", [], "q", "",
            lambda p, m: "alpha should be silent",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(conv1) + len(truths1), 0, "Alpha must be silent in beta1's vote")

        # Beta2's nested vote tries to call alpha
        conv2, truths2 = evaluate_providers(
            [alpha],
            "", [], "q", "",
            lambda p, m: "alpha should be silent",
            call_chain=["provider_alpha", "provider_beta2"],
        )
        self.assertEqual(len(conv2) + len(truths2), 0, "Alpha must be silent in beta2's vote")

    def test_beta1_can_call_beta2_in_nested_vote(self):
        """Beta1 initiates a nested vote and calls beta2 — beta2 is NOT in the
        chain (only alpha and beta1 are), so beta2 responds normally."""
        beta2 = _make_provider_entry("beta2", "provider_beta2", trust=0.7, conversation=True)

        conv, _ = evaluate_providers(
            [beta2],
            "", [], "q", "",
            lambda p, m: "beta2 responds in beta1's nested vote",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0].title, "beta2")

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
        alpha = _make_provider_entry("alpha", "provider_alpha", trust=0.9, conversation=True)
        beta1 = _make_provider_entry("beta1", "provider_beta1", trust=0.8, conversation=True)
        beta2 = _make_provider_entry("beta2", "provider_beta2", trust=0.7, conversation=True)

        call_log = []

        def mock_call(pconfig, messages):
            call_log.append(pconfig["api_url"])
            return f"Response from {pconfig['api_url']}"

        # Step 1: alpha fans out to beta1 and beta2 (no call chain yet)
        conv, _ = evaluate_providers(
            [beta1, beta2],
            "", [], "Tell me about Paris", "",
            mock_call,
        )
        self.assertEqual(len(conv), 2)

        # Step 2: beta1 initiates nested vote, tries alpha + beta2
        call_log.clear()
        conv1, _ = evaluate_providers(
            [alpha, beta2],
            "", [], "Tell me about Paris", "",
            mock_call,
            call_chain=["provider_alpha", "provider_beta1"],
        )
        # alpha is silenced; beta2 responds
        self.assertEqual(len(conv1), 1)
        self.assertEqual(conv1[0].title, "beta2")
        self.assertEqual(call_log, ["http://test/beta2"])

        # Step 3: beta2 initiates nested vote, tries alpha + beta1
        call_log.clear()
        conv2, _ = evaluate_providers(
            [alpha, beta1],
            "", [], "Tell me about Paris", "",
            mock_call,
            call_chain=["provider_alpha", "provider_beta2"],
        )
        # alpha is silenced; beta1 responds
        self.assertEqual(len(conv2), 1)
        self.assertEqual(conv2[0].title, "beta1")
        self.assertEqual(call_log, ["http://test/beta1"])


# ---------------------------------------------------------------------------
# Per-provider truth resolution
# ---------------------------------------------------------------------------

class TestPerProviderTruth(unittest.TestCase):
    """Test that authority_url on <provider> entries resolves private facts."""

    def test_authority_url_parsed(self):
        """parse_provider_block extracts authority_url from nested <authority> element."""
        content = (
            '<provider api_url="http://test" model="m">'
            '<authority url="file://data/beta_truth.xml"/>'
            '</provider>'
        )
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["authority_url"], "file://data/beta_truth.xml")

    def test_authority_url_empty_when_absent(self):
        """parse_provider_block returns empty authority_url when not present."""
        content = '<provider api_url="http://test" model="m"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["authority_url"], "")

    def test_resolve_provider_truth_empty_when_no_url(self):
        """No authority_url → empty list (RAG-free behavior)."""
        entry = {"id": "prov_x", "trust": 0.9}
        config = {"authority_url": ""}
        sources = resolve_provider_truth(config, entry)
        self.assertEqual(sources, [])

    def test_provider_without_authority_url_gets_rag_free_bundle(self):
        """Provider without authority_url gets the standard messages."""
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
        self.assertIn("question", full_text)


# ---------------------------------------------------------------------------
# Spec file validation
# ---------------------------------------------------------------------------

class TestSpecFiles(unittest.TestCase):
    """Verify the alpha/beta1/beta2 spec files parse correctly."""

    def test_alpha_has_two_provider_betas(self):
        """alpha.xml contains provider entries pointing to beta1 and beta2."""
        entries = _load_truth_entries("alpha.xml")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 2)
        ids = {p[0]["id"] for p in providers}
        self.assertEqual(ids, {"provider_beta1", "provider_beta2"})

    def test_alpha_has_own_facts(self):
        """alpha.xml has facts that beta1/beta2 don't have."""
        entries = _load_truth_entries("alpha.xml")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Capital of France", fact_titles)
        self.assertIn("France is in Europe", fact_titles)

    def test_beta1_has_provider_alpha(self):
        """beta1.xml contains a provider entry pointing to alpha."""
        entries = _load_truth_entries("beta1.xml")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][0]["id"], "provider_alpha")

    def test_beta1_has_own_facts(self):
        """beta1.xml has its own facts (Eiffel Tower)."""
        entries = _load_truth_entries("beta1.xml")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Eiffel Tower location", fact_titles)
        self.assertIn("Eiffel Tower height", fact_titles)
        self.assertIn("Eiffel Tower material", fact_titles)

    def test_beta2_has_provider_alpha(self):
        """beta2.xml contains a provider entry pointing to alpha."""
        entries = _load_truth_entries("beta2.xml")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0][0]["id"], "provider_alpha")

    def test_beta2_has_own_facts(self):
        """beta2.xml has its own facts (Louvre)."""
        entries = _load_truth_entries("beta2.xml")
        fact_titles = {e["title"] for e in entries
                       if "<fact" in e.get("content", "")}
        self.assertIn("Louvre Museum location", fact_titles)
        self.assertIn("Mona Lisa location", fact_titles)

    def test_mutual_reference_cycle_scenario(self):
        """alpha→beta1, beta1→alpha: alpha is silenced when in call chain."""
        beta_entries = _load_truth_entries("beta1.xml")
        beta_providers = get_provider_entries(beta_entries)
        alpha_entry = beta_providers[0]  # beta's reference to alpha

        conv, truths = evaluate_providers(
            [alpha_entry],
            "", [], "test question", "",
            lambda p, m: "alpha should not respond",
            call_chain=["provider_alpha"],
        )
        self.assertEqual(len(conv) + len(truths), 0, "Alpha must stay silent when in call chain")

    def test_branching_cycle_from_spec_files(self):
        """Load all three spec files, verify the branching cycle scenario.

        Alpha calls beta1 and beta2. Both betas reference alpha back.
        Alpha should be silenced in both betas' nested votes.
        """
        alpha_entries = _load_truth_entries("alpha.xml")
        beta1_entries = _load_truth_entries("beta1.xml")
        beta2_entries = _load_truth_entries("beta2.xml")

        alpha_providers = get_provider_entries(alpha_entries)
        beta1_providers = get_provider_entries(beta1_entries)
        beta2_providers = get_provider_entries(beta2_entries)

        # alpha fans out to beta1 and beta2
        self.assertEqual(len(alpha_providers), 2)
        alpha_beta_ids = {p[0]["id"] for p in alpha_providers}
        self.assertEqual(alpha_beta_ids, {"provider_beta1", "provider_beta2"})

        # Both betas reference alpha back
        self.assertEqual(beta1_providers[0][0]["id"], "provider_alpha")
        self.assertEqual(beta2_providers[0][0]["id"], "provider_alpha")

        # Beta1 tries to call alpha — silenced
        conv1, truths1 = evaluate_providers(
            [beta1_providers[0]],
            "", [], "q", "",
            lambda p, m: "should be silent",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(conv1) + len(truths1), 0)

        # Beta2 tries to call alpha — silenced
        conv2, truths2 = evaluate_providers(
            [beta2_providers[0]],
            "", [], "q", "",
            lambda p, m: "should be silent",
            call_chain=["provider_alpha", "provider_beta2"],
        )
        self.assertEqual(len(conv2) + len(truths2), 0)


# ---------------------------------------------------------------------------
# Diamond voting protocol: conversation-based fan-out
# ---------------------------------------------------------------------------

class TestDiamondVoting(unittest.TestCase):
    """Verify the beta fan-out → alpha final diamond."""

    def test_build_truth_provider_bundle(self):
        """_build_truth_provider_bundle creates a bundle with sources but no history."""
        sources = [Source("s1", "fact 1", 0.9, "Paris is the capital.", "fact")]
        bundle = _build_truth_provider_bundle(
            "system ctx", sources, "What is Paris?", "output fmt",
        )
        self.assertEqual(bundle.system, "system ctx")
        self.assertEqual(len(bundle.history), 0)
        self.assertEqual(len(bundle.sources), 1)
        self.assertEqual(bundle.query, "What is Paris?")

    def test_build_conversation_provider_bundle(self):
        """_build_conversation_provider_bundle creates a bundle with history and sources."""
        sources = [Source("s1", "fact 1", 0.9, "Paris is the capital.", "fact")]
        history = [{"role": "user", "content": "old msg"}]
        bundle = _build_conversation_provider_bundle(
            "system ctx", history, sources, "What is Paris?", "output fmt",
        )
        self.assertEqual(len(bundle.history), 1)
        self.assertEqual(bundle.history[0]["content"], "old msg")
        self.assertEqual(len(bundle.sources), 1)

    def test_conversation_bundle_does_not_mutate_original_history(self):
        """_build_conversation_provider_bundle must not mutate the original history."""
        original_history = [{"role": "user", "content": "hello"}]
        history_copy = list(original_history)

        _build_conversation_provider_bundle(
            "sys", original_history, [], "q", "out",
        )

        # Original should be unchanged
        self.assertEqual(original_history, history_copy)

    def test_conversation_betas_produce_conversation_sources(self):
        """conversation=True betas produce conversation_sources."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["api_url"]] = messages
            return f"<conversation>Beta response</conversation>"

        beta1 = _make_provider_entry("beta1", "prov_beta1", conversation=True)
        beta2 = _make_provider_entry("beta2", "prov_beta2", conversation=True)

        conv, truths = evaluate_providers(
            [beta1, beta2],
            "system context", [], "What is Paris?", "",
            mock_call,
        )

        self.assertEqual(len(conv), 2)
        # Both betas should have been called
        self.assertIn("http://test/beta1", captured_messages)
        self.assertIn("http://test/beta2", captured_messages)

        # Each beta's messages should contain the query
        for name in ("beta1", "beta2"):
            msgs = captured_messages[f"http://test/{name}"]
            all_text = " ".join(m["content"] for m in msgs)
            self.assertIn("What is Paris?", all_text,
                          f"{name} should see the query")

    def test_truth_only_betas_produce_truth_contributions(self):
        """conversation=False betas produce truth_contributions, not conversation_sources."""
        def mock_call(pconfig, messages):
            return "<fact>A response fact.</fact>"

        beta = _make_provider_entry("beta1", "prov_beta1", conversation=False)

        conv, truths = evaluate_providers(
            [beta],
            "system context", [], "question", "",
            mock_call,
        )

        self.assertEqual(len(conv), 0, "conversation=false betas should not produce conversation_sources")
        self.assertEqual(len(truths), 1, "conversation=false betas should produce truth_contributions")
        self.assertEqual(truths[0].kind, "fact")

    def test_diamond_full_sequence(self):
        """Simulate the complete diamond: beta fan-out → alpha final.

        Topology:
              root (query)
             / \\
          beta1   beta2
             \\ /
           alpha_final

        Verifies:
        1. Betas are called with the query
        2. Alpha is called with beta contributions
        """
        call_sequence = []

        beta1 = _make_provider_entry("beta1", "provider_beta1", trust=0.8, conversation=True)
        beta2 = _make_provider_entry("beta2", "provider_beta2", trust=0.7, conversation=True)

        # Fan out to betas
        captured_beta_msgs = {}

        def mock_beta_call(pconfig, messages):
            name = pconfig["api_url"]
            call_sequence.append((name, "beta_response"))
            captured_beta_msgs[name] = messages
            return f"<conversation>{name}: I agree about Paris</conversation>"

        conv, truths = evaluate_providers(
            [beta1, beta2],
            "system", [], "What is the capital of France?", "",
            mock_beta_call,
            call_chain=["provider_alpha"],
        )

        # Both betas responded (neither is in call chain)
        self.assertEqual(len(conv), 2)

        # Both betas saw the query in their messages
        for name in ("beta1", "beta2"):
            all_text = " ".join(m["content"] for m in captured_beta_msgs[f"http://test/{name}"])
            self.assertIn("What is the capital of France?", all_text)

        # Betas were called
        beta_calls = [c for c in call_sequence if c[1] == "beta_response"]
        self.assertEqual(len(beta_calls), 2)

    def test_diamond_with_cycle_prevention(self):
        """In the diamond, betas try to call alpha back — alpha stays silent due
        to cycle prevention, but betas still produce their own responses."""
        alpha = _make_provider_entry("alpha", "provider_alpha", trust=0.9, conversation=True)
        beta1 = _make_provider_entry("beta1", "provider_beta1", trust=0.8, conversation=True)

        # beta1 is called with alpha in call chain
        conv, _ = evaluate_providers(
            [beta1],
            "system", [], "query", "",
            lambda p, m: "beta1 responds normally",
            call_chain=["provider_alpha"],
        )
        # beta1 is NOT in the chain, so it responds
        self.assertEqual(len(conv), 1)

        # Beta1 tries to call alpha in a nested vote — alpha is silenced
        conv2, truths2 = evaluate_providers(
            [alpha],
            "system", [], "query", "",
            lambda p, m: "alpha should NOT be called",
            call_chain=["provider_alpha", "provider_beta1"],
        )
        self.assertEqual(len(conv2) + len(truths2), 0)


# ---------------------------------------------------------------------------
# Per-provider conversation control
# ---------------------------------------------------------------------------

class TestConversationControl(unittest.TestCase):
    """Verify that conversation attribute controls per-beta behavior."""

    def test_parse_provider_block_conversation_default_false(self):
        """parse_provider_block defaults conversation to False when absent."""
        content = '<provider api_url="http://test" model="m"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertFalse(result["conversation"])

    def test_parse_provider_block_conversation_explicit_true(self):
        """parse_provider_block reads conversation="true"."""
        content = '<provider api_url="http://test" model="m" conversation="true"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertTrue(result["conversation"])

    def test_parse_provider_block_conversation_false(self):
        """parse_provider_block reads conversation="false"."""
        content = '<provider api_url="http://test" model="m" conversation="false"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertFalse(result["conversation"])

    def test_parse_provider_block_conversation_one(self):
        """parse_provider_block treats conversation="1" as True."""
        content = '<provider api_url="http://test" model="m" conversation="1"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertTrue(result["conversation"])

    def test_parse_provider_block_conversation_yes(self):
        """parse_provider_block treats conversation="yes" as True."""
        content = '<provider api_url="http://test" model="m" conversation="yes"/>'
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertTrue(result["conversation"])

    def test_truth_only_beta_gets_truth_context(self):
        """Beta with conversation=False gets truth_context in system message."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["api_url"]] = messages
            return "<fact>Some fact.</fact>"

        truth_beta = _make_provider_entry("truth", "prov_truth", conversation=False)

        evaluate_providers(
            [truth_beta],
            "system", [], "question", "",
            mock_call,
        )

        msgs = captured_messages["http://test/truth"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("distributed truth system", all_text)

    def test_truth_only_beta_uses_custom_truth_context(self):
        """Custom truth_context should override the built-in fallback."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["api_url"]] = messages
            return "<fact>Some fact.</fact>"

        truth_beta = _make_provider_entry("truth", "prov_truth", conversation=False)

        evaluate_providers(
            [truth_beta],
            "system", [], "question", "",
            mock_call,
            truth_context="TRUTH XML RULES",
        )

        msgs = captured_messages["http://test/truth"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("TRUTH XML RULES", all_text)
        self.assertNotIn("distributed truth system", all_text)

    def test_conversation_beta_gets_conversation_context(self):
        """Beta with conversation=True gets conversation_context in system message."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["api_url"]] = messages
            return "<conversation>A response.</conversation>"

        conv_beta = _make_provider_entry("conv", "prov_conv", conversation=True)

        evaluate_providers(
            [conv_beta],
            "system", [], "question", "",
            mock_call,
        )

        msgs = captured_messages["http://test/conv"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("distributed truth system", all_text)

    def test_conversation_beta_uses_custom_conversation_context(self):
        """Custom conversation_context should override the built-in fallback."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["api_url"]] = messages
            return "<conversation>A response.</conversation>"

        conv_beta = _make_provider_entry("conv", "prov_conv", conversation=True)

        evaluate_providers(
            [conv_beta],
            "system", [], "question", "",
            mock_call,
            conversation_context="CONVERSATION XML RULES",
        )

        msgs = captured_messages["http://test/conv"]
        all_text = " ".join(m["content"] for m in msgs)
        self.assertIn("CONVERSATION XML RULES", all_text)
        self.assertNotIn("distributed truth system", all_text)

    def test_mixed_conversation_betas(self):
        """When betas have different conversation settings, only conversation=True
        betas produce conversation_sources."""
        captured_messages = {}

        def mock_call(pconfig, messages):
            captured_messages[pconfig["api_url"]] = messages
            return "<fact>A fact.</fact><conversation>An answer.</conversation>"

        conv_beta = _make_provider_entry("conv", "prov_conv", conversation=True)
        truth_beta = _make_provider_entry("truth", "prov_truth", conversation=False)

        conv, truths = evaluate_providers(
            [conv_beta, truth_beta],
            "system", [], "question", "",
            mock_call,
        )

        # Only conversation=True beta produces conversation_sources
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv[0].title, "conv")

        # Both produce truth_contributions (both returned <fact>)
        self.assertGreaterEqual(len(truths), 2)


# ---------------------------------------------------------------------------
# <feeling> truth type
# ---------------------------------------------------------------------------

class TestFeelingTruthType(unittest.TestCase):
    """Verify that <feeling> is recognized as a truth type and handled correctly."""

    def test_feeling_recognized_by_parse_root_attrs(self):
        """_parse_root_attrs recognizes <feeling> as a valid root tag."""
        content = '<feeling>Just a guess.</feeling>'
        parsed = _parse_root_attrs(content)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["tag"], "feeling")

    def test_feeling_normalized_as_truth_entry(self):
        """_normalize_trust_entry preserves <feeling> content and syncs envelope."""
        raw = {
            "type": "truth",
            "id": "feel_01",
            "title": "Subjective opinion",
            "trust": 0.4,
            "content": '<feeling>I think this is nice.</feeling>',
            "time": "2026-03-01T00:00:00Z",
        }
        entry = _normalize_trust_entry(raw)
        self.assertEqual(entry["id"], "feel_01")
        self.assertAlmostEqual(entry["trust"], 0.4)
        self.assertIn("<feeling", entry["content"])

    def test_feeling_not_filtered_by_static_truth(self):
        """static_truth() includes <feeling> entries (they are propositional content)."""
        entries = [
            {"id": "fact_01", "content": '<fact>A fact.</fact>'},
            {"id": "feel_01", "content": '<feeling>A feeling.</feeling>'},
            {"id": "prov_01", "content": '<provider api_url="http://x" model="m"/>'},
        ]
        result = static_truth(entries)
        ids = [e["id"] for e in result]
        self.assertIn("fact_01", ids)
        self.assertIn("feel_01", ids)
        self.assertNotIn("prov_01", ids)

    def test_feeling_gets_kind_feeling_in_bundle(self):
        """When building a bundle, <feeling> entries get kind='feeling'."""
        from state import ensure_minimal_state
        state = ensure_minimal_state({}, strict=False)
        state["truth"] = [
            {
                "type": "truth",
                "id": "feel_01",
                "title": "A feeling",
                "trust": 0.5,
                "content": '<feeling>Just vibes.</feeling>',
                "time": "2026-03-01T00:00:00Z",
            },
            {
                "type": "truth",
                "id": "fact_01",
                "title": "A fact",
                "trust": 0.9,
                "content": '<fact>The sky is blue.</fact>',
                "time": "2026-03-01T00:00:00Z",
            },
        ]
        bundle = _build_bundle(state, "Hello", {"rag": True})
        feeling_sources = [s for s in bundle.sources if s.kind == "feeling"]
        fact_sources = [s for s in bundle.sources if s.kind == "fact"]
        self.assertEqual(len(feeling_sources), 1)
        self.assertEqual(feeling_sources[0].source_id, "feel_01")
        self.assertGreaterEqual(len(fact_sources), 1)

    def test_feeling_in_spec_file(self):
        """hme.xml contains a <feeling> entry that normalizes correctly."""
        from state import load_state_file
        spec_file = SPEC_DIR / "hme.xml"
        self.assertTrue(spec_file.exists(), f"{spec_file} must exist")
        state = load_state_file(spec_file, strict=True)
        found_feeling = False
        for rec in state.get("truth", []):
                content = rec.get("content", "")
                if "<feeling" in content:
                    found_feeling = True
                    entry = _normalize_trust_entry(dict(rec))
                    parsed = _parse_root_attrs(entry["content"])
                    self.assertIsNotNone(parsed)
                    self.assertEqual(parsed["tag"], "feeling")
                    break
        self.assertTrue(found_feeling, "hme.xml should contain at least one <feeling> entry")


# ---------------------------------------------------------------------------
# <feeling> truth type
# ---------------------------------------------------------------------------

class TestFeelingTruthType(unittest.TestCase):
    """Verify that <feeling> entries are recognized, normalized, and classified."""

    def test_parse_root_attrs_recognizes_feeling(self):
        """_parse_root_attrs should recognize <feeling> as a valid root tag."""
        content = '<feeling>Some intuition.</feeling>'
        parsed = _parse_root_attrs(content)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["tag"], "feeling")

    def test_normalize_trust_entry_preserves_feeling(self):
        """_normalize_trust_entry should preserve <feeling> content as-is."""
        entry = {
            "type": "truth",
            "id": "f1",
            "title": "Intuition",
            "trust": 0.5,
            "content": '<feeling>Some intuition.</feeling>',
            "time": "2026-03-01T00:00:00Z",
        }
        result = _normalize_trust_entry(entry)
        self.assertEqual(result["id"], "f1")
        # Valid XML feelings never carry trust; if one arrives with trust
        # it passes through unchanged (normalization does not strip it).
        self.assertEqual(result["trust"], 0.5)
        self.assertIn("<feeling", result["content"])

    def test_static_truth_includes_feeling(self):
        """static_truth should include <feeling> entries (they are content, not structure)."""
        entries = [
            {"id": "f1", "content": '<fact>A.</fact>'},
            {"id": "f2", "content": '<feeling>B.</feeling>'},
            {"id": "p1", "content": '<provider api_url="http://x" model="m"/>'},
        ]
        result = static_truth(entries)
        ids = [e["id"] for e in result]
        self.assertIn("f1", ids)
        self.assertIn("f2", ids)
        self.assertNotIn("p1", ids)

    def test_feeling_kind_in_build_bundle(self):
        """_build_bundle should classify <feeling> entries as kind='feeling'."""
        from state import ensure_minimal_state
        state = ensure_minimal_state({}, strict=False)
        state["truth"] = [
            {
                "type": "truth",
                "id": "f1",
                "title": "Intuition",
                "trust": 0.5,
                "content": '<feeling>Some opinion.</feeling>',
                "time": "2026-03-01T00:00:00Z",
            },
            {
                "type": "truth",
                "id": "fact1",
                "title": "A fact",
                "trust": 0.9,
                "content": '<fact>Verified claim.</fact>',
                "time": "2026-03-01T00:00:01Z",
            },
        ]
        bundle = _build_bundle(
            state, "test question",
            {"rag": True, "temperature": 0.7},
            conversation_id=None,
        )
        feeling_sources = [s for s in bundle.sources if s.kind == "feeling"]
        fact_sources = [s for s in bundle.sources if s.kind == "fact"]
        self.assertEqual(len(feeling_sources), 1)
        self.assertEqual(feeling_sources[0].source_id, "f1")
        self.assertGreaterEqual(len(fact_sources), 1)

    def test_feeling_not_filtered_by_static_truth(self):
        """Feelings should pass through static_truth just like facts."""
        entries = [
            {"id": "feel", "content": '<feeling>A hunch.</feeling>'},
            {"id": "op1", "content": '<logic><and><ref id="a"/><ref id="b"/></and></logic>'},
            {"id": "auth1", "content": '<authority url="http://x"/>'},
        ]
        result = static_truth(entries)
        ids = [e["id"] for e in result]
        self.assertIn("feel", ids)
        self.assertNotIn("op1", ids)
        self.assertNotIn("auth1", ids)

    def test_feeling_in_spec_file(self):
        """The hme.xml spec should contain at least one <feeling> entry."""
        from state import load_state_file
        hme_path = SPEC_DIR / "hme.xml"
        self.assertTrue(hme_path.exists(), "hme.xml should exist")
        state = load_state_file(hme_path, strict=True)
        entries = state.get("truth", [])
        feeling_entries = [e for e in entries if "<feeling" in e.get("content", "")]
        self.assertGreaterEqual(len(feeling_entries), 1,
                                "hme.xml should have at least one <feeling> entry")


class TestDiamondConversationTree(unittest.TestCase):
    """Verify process_chat produces a diamond conversation tree during votes."""

    def test_vote_creates_diamond_structure(self):
        """When conversation=true providers exist, process_chat should create:
          vote_root: [user_query]
            ├── beta1_conv: [beta1_response]
            ├── beta2_conv: [beta2_response]
            └── final_conv: [alpha_final]  ← selected
        """
        from state import ensure_minimal_state
        from response import process_chat
        from config import Config
        import unittest.mock as mock

        state = ensure_minimal_state({}, strict=False)
        state["truth"] = [
            {"type": "truth", "id": "fact_01", "title": "Fact", "trust": 0.9,
             "content": "<fact>Paris is the capital.</fact>",
             "time": "2026-03-01T00:00:00Z"},
            {"type": "truth", "id": "prov_b1", "title": "Beta1", "trust": 0.8,
             "content": '<provider api_url="http://test/b1" model="m" conversation="true"/>',
             "time": "2026-03-01T00:00:01Z"},
            {"type": "truth", "id": "prov_b2", "title": "Beta2", "trust": 0.7,
             "content": '<provider api_url="http://test/b2" model="m" conversation="true"/>',
             "time": "2026-03-01T00:00:02Z"},
        ]

        cfg = Config(state_file=Path("/tmp/test.xml"))
        body = {"message": "Should we raise taxes?"}
        runtime_cfg = {
            "server": {"evaluation": {}, "truthset": {"truth_weight": 0.7}},
            "providers": {"default": "Gemini"},
        }

        call_count = {"n": 0}
        def mock_provider_call(url, **kwargs):
            call_count["n"] += 1
            resp = mock.MagicMock()
            resp.status_code = 200
            content = f"Response #{call_count['n']}"
            if kwargs.get("stream"):
                # NanoChat SSE streaming format
                lines = [
                    f'data: {{"token": "{content}"}}',
                    'data: {"done": true}',
                ]
                resp.iter_lines.return_value = iter(lines)
            else:
                resp.json.return_value = {
                    "choices": [{"message": {"content": content}}]
                }
            return resp

        with mock.patch("response.requests.post", side_effect=mock_provider_call), \
             mock.patch("response.PROVIDERS", {
                "Gemini": {
                    "type": "gemini",
                    "api_key": "k",
                    "url": "http://test/alpha",
                    "model": "test",
                },
             }), \
             mock.patch("config.STATELESS_MODE", True), \
             mock.patch("config.is_url_allowed", return_value=True):
            text, result_state, _rejected = process_chat(cfg, state, body, runtime_cfg)

        convs = result_state.get("conversations", [])
        # 1 root conversation with nested children
        self.assertEqual(len(convs), 1, "Should have exactly one root conversation")

        root = convs[0]
        self.assertEqual(len(root["messages"]), 1,
                         "Root should have user query only (no prelim)")
        self.assertEqual(root["messages"][0]["role"], "user")
        self.assertIsNone(root.get("parentId"),
                          "Root parentId should be None")

        # Root has only betas as direct children (not final)
        betas = root.get("children", [])
        self.assertGreaterEqual(len(betas), 2,
                                f"Root should have >=2 beta children, got {len(betas)}")

        # Each beta has 1 assistant message and final as its child
        for beta in betas:
            self.assertEqual(len(beta["messages"]), 1)
            self.assertEqual(beta["messages"][0]["role"], "assistant")
            beta_children = beta.get("children", [])
            self.assertGreaterEqual(len(beta_children), 1,
                                    f"Beta '{beta['id']}' should have final as child")

        # Final is the same node under every beta (shared object)
        finals = [b["children"][-1] for b in betas]
        final_ids = set(f["id"] for f in finals)
        self.assertEqual(len(final_ids), 1,
                         f"All betas should share the same final node, got {final_ids}")

        final = finals[0]
        self.assertEqual(result_state["selected_conversation"], final["id"],
                         "Selected conversation should be the final node")
        self.assertEqual(len(final["messages"]), 1)
        self.assertEqual(final["messages"][0]["role"], "assistant")

        # Final has two parents (both betas) — true diamond
        self.assertIsInstance(final["parentId"], list,
                              "Final parentId should be a list (diamond merge)")
        beta_ids = [b["id"] for b in betas]
        self.assertEqual(sorted(final["parentId"]), sorted(beta_ids),
                         "Final parentId should list all beta IDs")

        # No message content should be an error — verify providers returned real content
        self.assertFalse(text.startswith("[Error"),
                         f"Final response should not be an error: {text[:200]}")
        for msg in root["messages"]:
            self.assertFalse(
                (msg.get("content") or "").startswith("[Error"),
                f"Root message should not be an error: {(msg.get('content') or '')[:200]}")
        for beta in betas:
            for msg in beta["messages"]:
                self.assertFalse(
                    (msg.get("content") or "").startswith("[Error"),
                    f"Beta message should not be an error: {(msg.get('content') or '')[:200]}")
        for msg in final["messages"]:
            self.assertFalse(
                (msg.get("content") or "").startswith("[Error"),
                f"Final message should not be an error: {(msg.get('content') or '')[:200]}")

    def test_truth_only_betas_no_diamond(self):
        """When all betas have conversation=false, no diamond is created."""
        from state import ensure_minimal_state
        from response import process_chat
        from config import Config
        import unittest.mock as mock

        state = ensure_minimal_state({}, strict=False)
        state["truth"] = [
            {"type": "truth", "id": "fact_01", "title": "Fact", "trust": 0.9,
             "content": "<fact>Paris is the capital.</fact>",
             "time": "2026-03-01T00:00:00Z"},
            {"type": "truth", "id": "prov_b1", "title": "Beta1", "trust": 0.8,
             "content": '<provider api_url="http://test/b1" model="m"/>',
             "time": "2026-03-01T00:00:01Z"},
        ]

        cfg = Config(state_file=Path("/tmp/test.xml"))
        body = {"message": "Hello"}
        runtime_cfg = {
            "server": {"evaluation": {}, "truthset": {"truth_weight": 0.7}},
            "providers": {"default": "Gemini"},
        }

        def mock_call(url, **kwargs):
            resp = mock.MagicMock()
            resp.status_code = 200
            if kwargs.get("stream"):
                resp.iter_lines.return_value = iter([
                    'data: {"token": "Hi there!"}',
                    'data: {"done": true}',
                ])
            else:
                resp.json.return_value = {
                    "choices": [{"message": {"content": "Hi there!"}}]
                }
            return resp

        with mock.patch("response.requests.post", side_effect=mock_call), \
             mock.patch("response.PROVIDERS", {
                "Gemini": {
                    "type": "gemini",
                    "api_key": "k",
                    "url": "http://test/alpha",
                    "model": "test",
                },
             }), \
             mock.patch("config.STATELESS_MODE", True), \
             mock.patch("config.is_url_allowed", return_value=True):
            text, result_state, _rejected = process_chat(cfg, state, body, runtime_cfg)

        convs = result_state.get("conversations", [])
        self.assertEqual(len(convs), 1)
        root = convs[0]
        # No diamond — flat conversation with user + assistant
        self.assertEqual(len(root["messages"]), 2)
        self.assertEqual(root["messages"][0]["role"], "user")
        self.assertEqual(root["messages"][1]["role"], "assistant")
        self.assertEqual(root.get("children", []), [])
        self.assertFalse(text.startswith("[Error"),
                         f"Response should not be an error: {text[:200]}")

    def test_no_vote_creates_flat_conversation(self):
        """Without providers, process_chat creates a simple linear conversation."""
        from state import ensure_minimal_state
        from response import process_chat
        from config import Config
        import unittest.mock as mock

        state = ensure_minimal_state({}, strict=False)
        state["truth"] = [
            {"type": "truth", "id": "fact_01", "title": "Fact", "trust": 0.9,
             "content": "<fact>Paris is the capital.</fact>",
             "time": "2026-03-01T00:00:00Z"},
        ]

        cfg = Config(state_file=Path("/tmp/test.xml"))
        body = {"message": "Hello"}
        runtime_cfg = {
            "server": {"evaluation": {}, "truthset": {"truth_weight": 0.7}},
            "providers": {"default": "Gemini"},
        }

        def mock_call(url, **kwargs):
            resp = mock.MagicMock()
            resp.status_code = 200
            if kwargs.get("stream"):
                # NanoChat SSE streaming format
                resp.iter_lines.return_value = iter([
                    'data: {"token": "Hi there!"}',
                    'data: {"done": true}',
                ])
            else:
                resp.json.return_value = {
                    "choices": [{"message": {"content": "Hi there!"}}]
                }
            return resp

        with mock.patch("response.requests.post", side_effect=mock_call), \
             mock.patch("response.PROVIDERS", {
                "Gemini": {
                    "type": "gemini",
                    "api_key": "k",
                    "url": "http://test/alpha",
                    "model": "test",
                },
             }), \
             mock.patch("config.STATELESS_MODE", True), \
             mock.patch("config.is_url_allowed", return_value=True):
            text, result_state, _rejected = process_chat(cfg, state, body, runtime_cfg)

        convs = result_state.get("conversations", [])
        self.assertEqual(len(convs), 1)
        root = convs[0]
        # No voting — flat conversation with user + assistant
        self.assertEqual(len(root["messages"]), 2)
        self.assertEqual(root["messages"][0]["role"], "user")
        self.assertEqual(root["messages"][1]["role"], "assistant")
        self.assertEqual(root.get("children", []), [])
        # Response must not be an error message
        self.assertFalse(text.startswith("[Error"),
                         f"Response should not be an error: {text[:200]}")


# Diamond integration test moved to test/test_online_vote.py
# (isolated from this module to avoid global state pollution)


if __name__ == "__main__":
    unittest.main()
