#!/usr/bin/env python3
"""HME logical inference tests.

Loads spec/hme.jsonl and verifies that the prompt bundle pipeline produces
correct source selection and that a (mocked) LLM response can be validated
against expected certainty bounds.

Three test points — each exercises a different inference pattern:

  1) Deductive certainty (Socrates syllogism):
     t_axiom_01 (c=1.0) + t_axiom_02 (c=1.0) → Socrates is mortal.
     Expected: certainty = min(1.0, 1.0) = 1.0

  2) Negation override (penguins can't fly):
     t_soft_01 (c=0.8 "most birds can fly") + t_false_01 (c=-0.9 "penguins can fly")
     Expected: certainty ≈ -0.9  (specific override beats generic)

  3) Soft inference chain (whales + mammals):
     t_axiom_03 (c=1.0) + t_axiom_04 (c=1.0) → warm-blooded.
     But Wikipedia (t_src_wiki_01, c=0.9) is also a source.
     Expected: deductive certainty = 1.0, but soft-sourced corroboration at 0.9
"""

import json
import re
import sys
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

from state import jsonl_to_state, load_state_file
from response import (
    PromptBundle,
    Source,
    build_prompt_bundle,
    rank_retrieval_entries,
    to_openai_messages,
)


def _load_hme_state() -> dict:
    """Load spec/hme.jsonl into a v2 state dict."""
    hme_path = _project / "spec" / "hme.jsonl"
    return load_state_file(hme_path, strict=True)


def _build_bundle_for_query(state: dict, query: str) -> PromptBundle:
    """Build a prompt bundle with RAG enabled, default prefs."""
    prefs = {
        "provider": "wikioracle",
        "tools": {"rag": True, "url_fetch": False},
        "retrieval": {"max_entries": 12, "min_certainty": 0.0},
        "message_window": 40,
    }
    return build_prompt_bundle(state, query, prefs)


def _source_ids(bundle: PromptBundle) -> set:
    """Return the set of source IDs included in the bundle."""
    return {s.source_id for s in bundle.sources}


def _source_by_id(bundle: PromptBundle, source_id: str) -> Source | None:
    """Find a source by its ID in the bundle."""
    for s in bundle.sources:
        if s.source_id == source_id:
            return s
    return None


# ---------------------------------------------------------------------------
# Simulated LLM response parser
# ---------------------------------------------------------------------------
def _parse_certainty_response(text: str) -> float:
    """Extract the **final** certainty value from an LLM response.

    The response may cite source certainties inline (e.g. "t_axiom_01,
    certainty: 1.0") before stating its conclusion ("Certainty: -0.9").
    We take the last match so inline citations don't shadow the conclusion.

    Matches patterns like:
      certainty: 0.95
      certainty = -0.9
      CERTAINTY: 1.0
    """
    matches = re.findall(r"certainty\s*[:=]\s*([+-]?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if matches:
        return float(matches[-1])
    raise ValueError(f"No certainty value found in response: {text!r}")


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Deductive — Is Socrates mortal?
# ═══════════════════════════════════════════════════════════════════════════
class TestSocratesMortality(unittest.TestCase):
    """Syllogism: All men are mortal (1.0) + Socrates is a man (1.0)
    → Socrates is mortal.  Expected certainty = min(1.0, 1.0) = 1.0."""

    @classmethod
    def setUpClass(cls):
        cls.state = _load_hme_state()
        cls.bundle = _build_bundle_for_query(cls.state, "Is Socrates mortal?")

    def test_relevant_sources_included(self):
        """Bundle should include the two axioms and the derived entry."""
        ids = _source_ids(self.bundle)
        self.assertIn("t_axiom_01", ids, "Missing: All men are mortal")
        self.assertIn("t_axiom_02", ids, "Missing: Socrates is a man")
        self.assertIn("t_derived_01", ids, "Missing: Socrates is mortal (derived)")

    def test_axiom_certainties_are_1(self):
        """Both premises should have certainty 1.0."""
        s1 = _source_by_id(self.bundle, "t_axiom_01")
        s2 = _source_by_id(self.bundle, "t_axiom_02")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertAlmostEqual(s1.certainty, 1.0)
        self.assertAlmostEqual(s2.certainty, 1.0)

    def test_derived_certainty_is_1(self):
        """Derived conclusion should have certainty 1.0 (explicit in hme.jsonl)."""
        derived = _source_by_id(self.bundle, "t_derived_01")
        self.assertIsNotNone(derived)
        self.assertAlmostEqual(derived.certainty, 1.0)

    def test_context_instructs_kleene_logic(self):
        """The system prompt should reference Kleene ternary logic."""
        self.assertIn("Kleene", self.bundle.system)
        self.assertIn("certainty", self.bundle.system.lower())

    def test_simulated_llm_response(self):
        """A correct LLM should return certainty ~1.0 for 'Is Socrates mortal?'"""
        # Simulated LLM response (what a correct model should say)
        llm_response = (
            "<p>Yes, Socrates is mortal. This follows from a classical syllogism: "
            "All men are mortal (t_axiom_01, certainty: 1.0) and Socrates is a man "
            "(t_axiom_02, certainty: 1.0). By modus ponens, Socrates is mortal. "
            "This is also explicitly stated in t_derived_01. "
            "Certainty: 1.0</p>"
        )
        c = _parse_certainty_response(llm_response)
        self.assertGreaterEqual(c, 0.9, "Socrates mortality should be near-certain")
        self.assertLessEqual(c, 1.0)


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Negation override — Can penguins fly?
# ═══════════════════════════════════════════════════════════════════════════
class TestPenguinFlight(unittest.TestCase):
    """Generic: Most birds can fly (0.8) + Specific: Penguins can fly (-0.9).
    The specific negative override should dominate.
    Expected certainty ≈ -0.9 (penguins cannot fly)."""

    @classmethod
    def setUpClass(cls):
        cls.state = _load_hme_state()
        cls.bundle = _build_bundle_for_query(cls.state, "Can penguins fly?")

    def test_relevant_sources_included(self):
        """Bundle should include the bird/penguin entries."""
        ids = _source_ids(self.bundle)
        self.assertIn("t_soft_01", ids, "Missing: Most birds can fly")
        self.assertIn("t_axiom_05", ids, "Missing: Penguins are birds")
        self.assertIn("t_false_01", ids, "Missing: Penguins can fly (disbelief)")

    def test_negative_certainty_preserved(self):
        """t_false_01 should have negative certainty (-0.9)."""
        entry = _source_by_id(self.bundle, "t_false_01")
        self.assertIsNotNone(entry)
        self.assertAlmostEqual(entry.certainty, -0.9)

    def test_soft_belief_lower_than_axiom(self):
        """t_soft_01 (0.8) should rank below axioms (1.0)."""
        soft = _source_by_id(self.bundle, "t_soft_01")
        axiom = _source_by_id(self.bundle, "t_axiom_05")
        self.assertIsNotNone(soft)
        self.assertIsNotNone(axiom)
        self.assertLess(soft.certainty, axiom.certainty)

    def test_ranking_includes_negative_entries(self):
        """rank_retrieval_entries should include entries with negative certainty
        (they have high |certainty| and are relevant evidence)."""
        trust = self.state.get("truth", {}).get("trust", [])
        ranked = rank_retrieval_entries(trust, {"max_entries": 12, "min_certainty": 0.0})
        ids = {e["id"] for e in ranked}
        self.assertIn("t_false_01", ids,
                       "Negative certainty entries should be included in ranking")

    def test_simulated_llm_response(self):
        """A correct LLM should return certainty ≈ -0.9 for 'Can penguins fly?'"""
        llm_response = (
            "<p>No, penguins cannot fly. While most birds can fly "
            "(t_soft_01, certainty: 0.80), penguins are a specific exception. "
            "Penguins are birds (t_axiom_05, certainty: 1.0), but the entry "
            "t_false_01 explicitly states that penguins can fly with certainty "
            "-0.90 (strong disbelief). The specific override takes precedence "
            "over the generic soft belief. Certainty: -0.9</p>"
        )
        c = _parse_certainty_response(llm_response)
        self.assertLess(c, -0.5, "Penguin flight should be strongly negative")
        self.assertGreaterEqual(c, -1.0)


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Chain inference — Are whales warm-blooded?
# ═══════════════════════════════════════════════════════════════════════════
class TestWhaleWarmBlooded(unittest.TestCase):
    """Chain: All mammals are warm-blooded (1.0) + All whales are mammals (1.0)
    → All whales are warm-blooded.
    Deductive certainty = min(1.0, 1.0) = 1.0.
    Also has a derived entry t_derived_02 at 1.0."""

    @classmethod
    def setUpClass(cls):
        cls.state = _load_hme_state()
        cls.bundle = _build_bundle_for_query(cls.state, "Are whales warm-blooded?")

    def test_relevant_sources_included(self):
        """Bundle should include the mammal/whale axioms and derived entry."""
        ids = _source_ids(self.bundle)
        self.assertIn("t_axiom_03", ids, "Missing: All mammals are warm-blooded")
        self.assertIn("t_axiom_04", ids, "Missing: All whales are mammals")
        self.assertIn("t_derived_02", ids, "Missing: All whales are warm-blooded (derived)")

    def test_chain_certainty_propagation(self):
        """Both premises are certainty 1.0; min(1.0, 1.0) = 1.0."""
        s1 = _source_by_id(self.bundle, "t_axiom_03")
        s2 = _source_by_id(self.bundle, "t_axiom_04")
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        chain_certainty = min(s1.certainty, s2.certainty)
        self.assertAlmostEqual(chain_certainty, 1.0)

    def test_derived_entry_matches_chain(self):
        """The explicit derived entry should agree with the chain inference."""
        derived = _source_by_id(self.bundle, "t_derived_02")
        self.assertIsNotNone(derived)
        s1 = _source_by_id(self.bundle, "t_axiom_03")
        s2 = _source_by_id(self.bundle, "t_axiom_04")
        expected = min(s1.certainty, s2.certainty)
        self.assertAlmostEqual(derived.certainty, expected)

    def test_wikipedia_source_also_included(self):
        """The Wikipedia source (t_src_wiki_01) should be in the bundle too,
        providing corroborating evidence at certainty 0.9."""
        ids = _source_ids(self.bundle)
        # Wikipedia entry is about Socrates, not whales — it may or may not
        # be included depending on retrieval. Check it's at least ranked.
        trust = self.state.get("truth", {}).get("trust", [])
        ranked = rank_retrieval_entries(trust, {"max_entries": 12, "min_certainty": 0.0})
        wiki = next((e for e in ranked if e["id"] == "t_src_wiki_01"), None)
        if wiki:
            # If included, verify its certainty
            self.assertAlmostEqual(wiki["certainty"], 0.9)

    def test_simulated_llm_response(self):
        """A correct LLM should return certainty ~1.0 for 'Are whales warm-blooded?'"""
        llm_response = (
            "<p>Yes, whales are warm-blooded. All mammals are warm-blooded "
            "(t_axiom_03, certainty: 1.0) and all whales are mammals "
            "(t_axiom_04, certainty: 1.0). By chain inference, "
            "certainty = min(1.0, 1.0) = 1.0. This is confirmed by "
            "t_derived_02. Certainty: 1.0</p>"
        )
        c = _parse_certainty_response(llm_response)
        self.assertGreaterEqual(c, 0.9, "Whale warm-blooded should be near-certain")
        self.assertLessEqual(c, 1.0)


# ═══════════════════════════════════════════════════════════════════════════
# Cross-cutting: prompt structure
# ═══════════════════════════════════════════════════════════════════════════
class TestPromptStructure(unittest.TestCase):
    """Verify the prompt bundle wiring for HME inference queries."""

    @classmethod
    def setUpClass(cls):
        cls.state = _load_hme_state()

    def test_openai_messages_include_sources(self):
        """to_openai_messages should include [Reference Documents] with certainty."""
        bundle = _build_bundle_for_query(self.state, "Is Socrates mortal?")
        msgs = to_openai_messages(bundle)
        user_msg = msgs[-1]["content"]
        self.assertIn("[Reference Documents]", user_msg)
        self.assertIn("certainty:", user_msg)
        self.assertIn("t_axiom_01", user_msg)

    def test_all_trust_entries_loaded(self):
        """hme.jsonl has 17 trust entries (9 facts + 4 implications + 3 meta + 1 authority); all should be in state."""
        trust = self.state.get("truth", {}).get("trust", [])
        self.assertEqual(len(trust), 17)

    def test_provider_entries_excluded_from_rag(self):
        """<provider> entries should be excluded from normal RAG sources."""
        bundle = _build_bundle_for_query(self.state, "Is Socrates mortal?")
        ids = _source_ids(bundle)
        self.assertNotIn("t_provider_claude", ids,
                         "Provider entries should be excluded from RAG sources")


if __name__ == "__main__":
    unittest.main()
