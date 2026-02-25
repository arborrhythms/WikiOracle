#!/usr/bin/env python3
"""Unit tests for the derived truth engine (compute_derived_truth).

Tests Strong Kleene material implication, fixed-point iteration,
cycle termination, and integration with hme.jsonl test data.
"""

import json
import os
import sys

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

from wikioracle_state import (
    compute_derived_truth,
    ensure_implication_id,
    parse_implication_block,
)


def _make_trust(id, certainty, content="<p>test</p>", title=""):
    return {"type": "trust", "id": id, "certainty": certainty, "content": content, "title": title}


def _make_impl(ant, con, impl_type="material"):
    content = f"<implication><antecedent>{ant}</antecedent><consequent>{con}</consequent><type>{impl_type}</type></implication>"
    return {"type": "trust", "id": f"i_test_{ant}_{con}", "certainty": 0.0, "content": content, "title": f"{ant} -> {con}"}


# ─── parse_implication_block tests ───


def test_parse_implication_block_basic():
    content = "<implication><antecedent>t_a</antecedent><consequent>t_b</consequent><type>material</type></implication>"
    result = parse_implication_block(content)
    assert result is not None
    assert result["antecedent"] == "t_a"
    assert result["consequent"] == "t_b"
    assert result["type"] == "material"


def test_parse_implication_block_default_type():
    content = "<implication><antecedent>t_a</antecedent><consequent>t_b</consequent></implication>"
    result = parse_implication_block(content)
    assert result is not None
    assert result["type"] == "material"


def test_parse_implication_block_not_implication():
    assert parse_implication_block("<p>Just a fact.</p>") is None
    assert parse_implication_block("") is None
    assert parse_implication_block("<provider name='x' />") is None


# ─── ensure_implication_id tests ───


def test_ensure_implication_id_preserves_existing():
    entry = {"id": "i_existing_01", "content": "<implication><antecedent>a</antecedent><consequent>b</consequent></implication>"}
    assert ensure_implication_id(entry) == "i_existing_01"


def test_ensure_implication_id_generates():
    entry = {"content": "<implication><antecedent>t_a</antecedent><consequent>t_b</consequent><type>material</type></implication>"}
    iid = ensure_implication_id(entry)
    assert iid.startswith("i_")
    assert len(iid) == 18  # "i_" + 16 hex chars
    assert entry["id"] == iid


# ─── compute_derived_truth: basic modus ponens ───


def test_basic_modus_ponens():
    """If A is true and A→B exists, B should become true."""
    entries = [
        _make_trust("t_a", 1.0),
        _make_trust("t_b", 0.0),
        _make_impl("t_a", "t_b"),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_b"] == 1.0, f"Expected t_b=1.0, got {derived['t_b']}"


def test_modus_ponens_soft_antecedent():
    """Soft antecedent (0.7) should raise consequent to 0.7."""
    entries = [
        _make_trust("t_a", 0.7),
        _make_trust("t_b", 0.0),
        _make_impl("t_a", "t_b"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["t_b"] - 0.7) < 1e-9, f"Expected t_b=0.7, got {derived['t_b']}"


def test_negative_antecedent_no_propagation():
    """Disbelieved antecedent should not modify consequent."""
    entries = [
        _make_trust("t_a", -0.8),
        _make_trust("t_b", 0.0),
        _make_impl("t_a", "t_b"),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_b"] == 0.0, f"Expected t_b=0.0, got {derived['t_b']}"


def test_zero_antecedent_no_propagation():
    """Unknown antecedent (0) should not modify consequent."""
    entries = [
        _make_trust("t_a", 0.0),
        _make_trust("t_b", 0.0),
        _make_impl("t_a", "t_b"),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_b"] == 0.0


def test_consequent_already_higher():
    """If consequent is already higher than antecedent, no change."""
    entries = [
        _make_trust("t_a", 0.5),
        _make_trust("t_b", 0.9),
        _make_impl("t_a", "t_b"),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_b"] == 0.9


# ─── Fixed-point iteration (chains) ───


def test_chain_propagation():
    """A→B→C should propagate through two iterations."""
    entries = [
        _make_trust("t_a", 1.0),
        _make_trust("t_b", 0.0),
        _make_trust("t_c", 0.0),
        _make_impl("t_a", "t_b"),
        _make_impl("t_b", "t_c"),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_b"] == 1.0
    assert derived["t_c"] == 1.0


def test_long_chain():
    """A→B→C→D→E should propagate through four iterations."""
    entries = [_make_trust("t_a", 1.0)]
    for label in ["t_b", "t_c", "t_d", "t_e"]:
        entries.append(_make_trust(label, 0.0))
    entries.append(_make_impl("t_a", "t_b"))
    entries.append(_make_impl("t_b", "t_c"))
    entries.append(_make_impl("t_c", "t_d"))
    entries.append(_make_impl("t_d", "t_e"))

    derived = compute_derived_truth(entries)
    for label in ["t_b", "t_c", "t_d", "t_e"]:
        assert derived[label] == 1.0, f"Expected {label}=1.0, got {derived[label]}"


# ─── Cycle termination ───


def test_cycle_terminates():
    """A→B, B→A should not cause infinite loop."""
    entries = [
        _make_trust("t_a", 0.5),
        _make_trust("t_b", 0.3),
        _make_impl("t_a", "t_b"),
        _make_impl("t_b", "t_a"),
    ]
    derived = compute_derived_truth(entries)
    # Both should settle at 0.5 (the max of the two)
    assert derived["t_a"] == 0.5
    assert derived["t_b"] == 0.5


def test_cycle_both_zero():
    """Cycle with both at 0 should stay at 0."""
    entries = [
        _make_trust("t_a", 0.0),
        _make_trust("t_b", 0.0),
        _make_impl("t_a", "t_b"),
        _make_impl("t_b", "t_a"),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_a"] == 0.0
    assert derived["t_b"] == 0.0


# ─── No implications ───


def test_no_implications():
    """Without implication entries, certainties pass through unchanged."""
    entries = [
        _make_trust("t_a", 0.8),
        _make_trust("t_b", -0.5),
    ]
    derived = compute_derived_truth(entries)
    assert derived["t_a"] == 0.8
    assert derived["t_b"] == -0.5


# ─── Integration with hme.jsonl ───


def test_hme_jsonl_syllogisms():
    """Load spec/hme.jsonl and verify derived truth for syllogisms."""
    hme_path = os.path.join(os.path.dirname(__file__), "..", "spec", "hme.jsonl")
    if not os.path.exists(hme_path):
        return  # skip if file not present

    with open(hme_path) as f:
        entries = []
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if rec.get("type") == "trust":
                    entries.append(rec)

    derived = compute_derived_truth(entries)

    # t_derived_01 (Socrates is mortal): stored=0.0, should derive to 1.0
    assert derived.get("t_derived_01") == 1.0, \
        f"Socrates syllogism failed: got {derived.get('t_derived_01')}"

    # t_derived_02 (Whales are warm-blooded): stored=0.0, should derive to 1.0
    assert derived.get("t_derived_02") == 1.0, \
        f"Whales syllogism failed: got {derived.get('t_derived_02')}"

    # Axioms should remain unchanged
    assert derived.get("t_axiom_01") == 1.0
    assert derived.get("t_axiom_02") == 1.0


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {test.__name__}: {e}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed out of {passed + failed} tests")
    sys.exit(1 if failed else 0)
