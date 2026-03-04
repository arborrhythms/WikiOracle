#!/usr/bin/env python3
"""Alpha state file tests.

Copies spec/alpha.jsonl to the project root (alpha.jsonl) and verifies:
  - Round-trip integrity (load → serialize → reload)
  - Correct structure: 2 facts + 1 feeling + 2 providers
  - Provider entries are valid and sorted by trust (descending)
  - Facts and feelings carry correct trust values
  - XHTML content is well-formed and self-describing
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

from state import (
    atomic_write_jsonl,
    ensure_minimal_state,
    load_state_file,
    state_to_jsonl,
    jsonl_to_state,
)
from truth import (
    get_provider_entries,
    parse_provider_block,
)

# Working copies live in output/; spec/ originals are never modified.
_SPEC_DIR = _project / "spec"
_OUTPUT_DIR = _project / "output"
_ALPHA_SRC = _SPEC_DIR / "alpha.jsonl"
_ALPHA_COPY = _OUTPUT_DIR / "alpha.jsonl"
_BETA_NAMES = ("beta1", "beta2")


def _ensure_vote_copies() -> Path:
    """Copy spec/{alpha,beta1,beta2}.jsonl → output/ (overwrite each)."""
    _OUTPUT_DIR.mkdir(exist_ok=True)
    shutil.copy2(_ALPHA_SRC, _ALPHA_COPY)
    for name in _BETA_NAMES:
        shutil.copy2(_SPEC_DIR / f"{name}.jsonl", _OUTPUT_DIR / f"{name}.jsonl")
    return _ALPHA_COPY


class TestAlphaStateLoad(unittest.TestCase):
    """Verify spec/alpha.jsonl loads correctly from a root-level copy."""

    @classmethod
    def setUpClass(cls):
        cls.alpha_path = _ensure_vote_copies()
        cls.state = load_state_file(cls.alpha_path, strict=True)

    def test_loads_from_copy(self):
        """alpha.jsonl should load from the project-root copy without error."""
        self.assertIsInstance(self.state, dict)
        self.assertIn("truth", self.state)
        self.assertIn("conversations", self.state)

    def test_title(self):
        """Header title should be 'Alpha Vote Test'."""
        self.assertEqual(self.state.get("title"), "Alpha Vote Test")

    def test_context_mentions_voting(self):
        """Context should describe a voting participant."""
        ctx = self.state.get("context", "")
        self.assertIn("voting", ctx.lower())

    def test_truth_entry_count(self):
        """alpha.jsonl has 5 trust entries: 2 facts + 1 feeling + 2 providers."""
        truth = self.state.get("truth", [])
        self.assertEqual(len(truth), 5)

    def test_fact_entries(self):
        """Two fact entries with correct IDs and trust values."""
        by_id = {e["id"]: e for e in self.state["truth"]}
        self.assertIn("alpha_fact_01", by_id)
        self.assertIn("alpha_fact_02", by_id)
        self.assertAlmostEqual(by_id["alpha_fact_01"]["trust"], 1.0)
        self.assertAlmostEqual(by_id["alpha_fact_02"]["trust"], 0.95)

    def test_feeling_entry(self):
        """One feeling entry with trust 0.5."""
        by_id = {e["id"]: e for e in self.state["truth"]}
        self.assertIn("alpha_feeling_01", by_id)
        self.assertAlmostEqual(by_id["alpha_feeling_01"]["trust"], 0.5)
        self.assertIn("<feeling", by_id["alpha_feeling_01"]["content"])

    def test_provider_entries(self):
        """Two provider entries (beta1 and beta2) with correct trust."""
        by_id = {e["id"]: e for e in self.state["truth"]}
        self.assertIn("provider_beta1", by_id)
        self.assertIn("provider_beta2", by_id)
        self.assertAlmostEqual(by_id["provider_beta1"]["trust"], 0.8)
        self.assertAlmostEqual(by_id["provider_beta2"]["trust"], 0.7)


class TestAlphaProviders(unittest.TestCase):
    """Verify provider parsing from alpha.jsonl."""

    @classmethod
    def setUpClass(cls):
        cls.alpha_path = _ensure_vote_copies()
        cls.state = load_state_file(cls.alpha_path, strict=True)
        cls.provider_entries = get_provider_entries(cls.state.get("truth", []))

    def test_two_providers_found(self):
        """get_provider_entries should find exactly 2 providers."""
        self.assertEqual(len(self.provider_entries), 2)

    def test_providers_sorted_by_trust_desc(self):
        """Providers should be sorted by trust descending (beta1=0.8 first)."""
        trusts = [e[0].get("trust", 0) for e in self.provider_entries]
        self.assertEqual(trusts, sorted(trusts, reverse=True))

    def test_provider_configs_have_api_url(self):
        """Each parsed provider config should have an api_url."""
        for _entry, config in self.provider_entries:
            self.assertIn("api_url", config)
            self.assertIn("googleapis.com", config["api_url"])

    def test_provider_configs_have_model(self):
        """Each parsed provider config should have a model."""
        for _entry, config in self.provider_entries:
            self.assertIn("model", config)
            self.assertIn("gemini", config["model"])

    def test_provider_configs_have_authority_url(self):
        """Each beta provider should reference its own state file via authority_url."""
        for _entry, config in self.provider_entries:
            self.assertTrue(config.get("authority_url"),
                            f"Provider missing authority_url")
            self.assertIn("beta", config["authority_url"])

    def test_beta_state_files_exist(self):
        """spec/beta1.jsonl and spec/beta2.jsonl should exist and be loadable."""
        for name in ("beta1", "beta2"):
            path = _project / "spec" / f"{name}.jsonl"
            self.assertTrue(path.exists(), f"Missing {path}")
            state = load_state_file(path, strict=True)
            self.assertGreaterEqual(len(state.get("truth", [])), 2,
                                    f"{name}.jsonl should have ≥2 truth entries")

    def test_provider_xhtml_is_parseable(self):
        """Provider XHTML content should be parseable by parse_provider_block."""
        for entry, _config in self.provider_entries:
            parsed = parse_provider_block(entry.get("content", ""))
            self.assertIsNotNone(parsed)
            self.assertIn("api_url", parsed)


class TestAlphaRoundTrip(unittest.TestCase):
    """Verify alpha.jsonl survives load → serialize → reload."""

    @classmethod
    def setUpClass(cls):
        cls.alpha_path = _ensure_vote_copies()
        cls.original = load_state_file(cls.alpha_path, strict=True)

    def test_in_memory_roundtrip(self):
        """state → JSONL text → state preserves all trust entry IDs."""
        jsonl_text = state_to_jsonl(self.original)
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored, strict=True)

        orig_ids = {e["id"] for e in self.original["truth"]}
        restored_ids = {e["id"] for e in restored["truth"]}
        self.assertEqual(orig_ids, restored_ids)

    def test_disk_roundtrip(self):
        """state → disk → reload preserves trust values."""
        rt_path = _OUTPUT_DIR / "alpha_roundtrip.jsonl"
        try:
            atomic_write_jsonl(rt_path, self.original)
            reloaded = load_state_file(rt_path, strict=True)

            orig_by_id = {e["id"]: e for e in self.original["truth"]}
            reload_by_id = {e["id"]: e for e in reloaded["truth"]}

            for eid, orig_entry in orig_by_id.items():
                self.assertIn(eid, reload_by_id)
                self.assertAlmostEqual(
                    orig_entry["trust"],
                    reload_by_id[eid]["trust"],
                    msg=f"Trust mismatch for {eid}",
                )
        finally:
            rt_path.unlink(missing_ok=True)

    def test_context_preserved(self):
        """Context string should survive round-trip."""
        jsonl_text = state_to_jsonl(self.original)
        restored = jsonl_to_state(jsonl_text)
        self.assertIn("voting", restored.get("context", "").lower())

    def test_copy_matches_spec(self):
        """The root alpha.jsonl should match spec/alpha.jsonl."""
        spec_state = load_state_file(_ALPHA_SRC, strict=True)
        spec_ids = {e["id"] for e in spec_state["truth"]}
        orig_ids = {e["id"] for e in self.original["truth"]}
        self.assertEqual(spec_ids, orig_ids)

    def test_beta_copies_in_output(self):
        """output/beta1.jsonl and output/beta2.jsonl should exist and be loadable."""
        for name in _BETA_NAMES:
            path = _OUTPUT_DIR / f"{name}.jsonl"
            self.assertTrue(path.exists(), f"Missing output/{name}.jsonl")
            state = load_state_file(path, strict=True)
            self.assertGreaterEqual(len(state.get("truth", [])), 2,
                                    f"output/{name}.jsonl should have ≥2 truth entries")


if __name__ == "__main__":
    unittest.main()
