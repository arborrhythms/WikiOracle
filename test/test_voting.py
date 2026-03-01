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
    evaluate_providers,
    resolve_provider_truth,
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
        sub = _make_provider_entry("sub", "provider_sub", certainty=0.8)

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
        round2_chain = ["provider_dom", "provider_sub"]
        round2_results = evaluate_providers(
            [dom],  # sub tries to call dom as its secondary
            "", [], "What is the Eiffel Tower?", "",
            lambda p, m: "Dom would respond — but should be silenced",
            call_chain=round2_chain,
        )
        # Dom must stay silent — it's in the chain
        self.assertEqual(len(round2_results), 0)


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

    def test_resolve_provider_truth_with_valid_file(self):
        """resolve_provider_truth loads facts from a JSONL file."""
        truth_file = SPEC_DIR / "sub_truth.jsonl"
        if not truth_file.exists():
            self.skipTest("spec/sub_truth.jsonl not found")

        entry = {"id": "prov_sub", "certainty": 0.8, "time": "2026-03-01T00:00:00Z"}
        config = {"truth_url": f"file://{truth_file}"}

        sources = resolve_provider_truth(config, entry)
        self.assertGreater(len(sources), 0)

        # Certainty should be scaled: provider_certainty * remote_certainty
        for s in sources:
            self.assertLessEqual(abs(s.certainty), 1.0)
            self.assertTrue(s.source_id.startswith("prov_sub:"))
            self.assertEqual(s.kind, "fact")

    def test_resolve_provider_truth_empty_when_no_url(self):
        """No truth_url → empty list (RAG-free behavior)."""
        entry = {"id": "prov_x", "certainty": 0.9}
        config = {"truth_url": ""}
        sources = resolve_provider_truth(config, entry)
        self.assertEqual(sources, [])

    def test_resolve_provider_truth_scales_certainty(self):
        """Certainty = provider_certainty * remote_certainty."""
        truth_file = SPEC_DIR / "sub_truth.jsonl"
        if not truth_file.exists():
            self.skipTest("spec/sub_truth.jsonl not found")

        entry = {"id": "prov_test", "certainty": 0.5, "time": "2026-03-01T00:00:00Z"}
        config = {"truth_url": f"file://{truth_file}"}

        sources = resolve_provider_truth(config, entry)
        # sub_private_01 has trust=0.95 → scaled = 0.5 * 0.95 = 0.475
        height_source = [s for s in sources if "sub_private_01" in s.source_id]
        self.assertEqual(len(height_source), 1)
        self.assertAlmostEqual(height_source[0].certainty, 0.475)

    def test_provider_truth_injected_into_bundle(self):
        """Provider with truth_url gets its private facts in the messages."""
        truth_file = SPEC_DIR / "sub_truth.jsonl"
        if not truth_file.exists():
            self.skipTest("spec/sub_truth.jsonl not found")

        captured = {}

        def mock_call(pconfig, messages):
            captured["messages"] = messages
            return "ok"

        _, config = _make_provider_entry(
            "sub", "prov_sub", truth_url=f"file://{truth_file}",
        )
        entry = {"id": "prov_sub", "certainty": 0.8, "time": "2026-03-01T00:00:00Z",
                 "content": config.get("content", "")}
        pairs = [(entry, config)]

        evaluate_providers(
            pairs, "system ctx", [], "question", "output", mock_call,
        )

        self.assertIn("messages", captured)
        full_text = " ".join(m["content"] for m in captured["messages"])
        # The private facts should appear in the messages
        self.assertIn("330 metres", full_text)

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
    """Verify the dom/sub spec files parse correctly."""

    def _load_truth_entries(self, filename):
        """Load truth entries from a spec JSONL file."""
        path = SPEC_DIR / filename
        if not path.exists():
            self.skipTest(f"spec/{filename} not found")
        entries = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("type") == "truth":
                entries.append(rec)
        return entries

    def test_dom_has_provider_sub(self):
        """dom.jsonl contains a provider entry pointing to sub."""
        entries = self._load_truth_entries("dom.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        entry, config = providers[0]
        self.assertEqual(entry["id"], "provider_sub")
        self.assertEqual(config["name"], "sub")
        self.assertEqual(config["truth_url"], "file://spec/sub_truth.jsonl")

    def test_sub_has_provider_dom(self):
        """sub.jsonl contains a provider entry pointing to dom."""
        entries = self._load_truth_entries("sub.jsonl")
        providers = get_provider_entries(entries)
        self.assertEqual(len(providers), 1)
        entry, config = providers[0]
        self.assertEqual(entry["id"], "provider_dom")
        self.assertEqual(config["name"], "dom")

    def test_sub_truth_file_has_private_facts(self):
        """sub_truth.jsonl contains private facts for the sub."""
        entries = self._load_truth_entries("sub_truth.jsonl")
        self.assertGreater(len(entries), 0)
        titles = {e.get("title", "") for e in entries}
        self.assertIn("Eiffel Tower height", titles)

    def test_mutual_reference_cycle_scenario(self):
        """dom→sub and sub→dom: confirm the cycle setup is correct."""
        dom_entries = self._load_truth_entries("dom.jsonl")
        sub_entries = self._load_truth_entries("sub.jsonl")

        dom_providers = get_provider_entries(dom_entries)
        sub_providers = get_provider_entries(sub_entries)

        # dom references sub
        self.assertEqual(dom_providers[0][1]["name"], "sub")
        # sub references dom
        self.assertEqual(sub_providers[0][1]["name"], "dom")

        # Simulate: dom initiates, sub called, sub tries to call dom
        # dom should be silenced because it's in the call chain
        dom_entry = sub_providers[0]  # sub's reference to dom
        results = evaluate_providers(
            [dom_entry],
            "", [], "test question", "",
            lambda p, m: "dom should not respond",
            call_chain=["provider_dom"],  # dom is in the chain
        )
        self.assertEqual(len(results), 0, "Dom must stay silent when in call chain")


if __name__ == "__main__":
    unittest.main()
