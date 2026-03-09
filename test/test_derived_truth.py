#!/usr/bin/env python3
"""Unit tests for the derived truth engine (compute_derived_truth).

Tests Strong Kleene operators (and/or/not/non), fixed-point iteration,
cycle termination, and integration with hme.xml test data.
"""

import json
import os
import sys

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

from truth import (
    compute_derived_truth,
    ensure_operator_id,
    parse_operator_block,
)


def _make_trust(id, trust, content=None, title=""):
    if content is None:
        content = '<fact>test</fact>'
    return {"type": "truth", "id": id, "trust": trust, "content": content, "title": title}


def _make_and(entry_id, refs, trust=0.0):
    title = f"and({', '.join(refs)})"
    ref_xml = "".join(f'<ref id="{r}"/>' for r in refs)
    content = f'<logic><and>{ref_xml}</and></logic>'
    return {"type": "truth", "id": entry_id, "trust": trust, "content": content, "title": title}


def _make_or(entry_id, refs, trust=0.0):
    title = f"or({', '.join(refs)})"
    ref_xml = "".join(f'<ref id="{r}"/>' for r in refs)
    content = f'<logic><or>{ref_xml}</or></logic>'
    return {"type": "truth", "id": entry_id, "trust": trust, "content": content, "title": title}


def _make_not(entry_id, ref, trust=0.0):
    title = f"not({ref})"
    content = f'<logic><not><ref id="{ref}"/></not></logic>'
    return {"type": "truth", "id": entry_id, "trust": trust, "content": content, "title": title}


def _make_non(entry_id, ref, trust=0.0):
    title = f"non({ref})"
    content = f'<logic><non><ref id="{ref}"/></non></logic>'
    return {"type": "truth", "id": entry_id, "trust": trust, "content": content, "title": title}


# ─── parse_operator_block tests ───


def test_parse_operator_block_and():
    """New format: <logic><and><ref id="..."/>...</and></logic>."""
    content = '<logic><and><ref id="a"/><ref id="b"/></and></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "and"
    assert result["refs"] == ["a", "b"]
    assert result["inline_entries"] == []


def test_parse_operator_block_or():
    content = '<logic><or><ref id="x"/><ref id="y"/><ref id="z"/></or></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "or"
    assert result["refs"] == ["x", "y", "z"]


def test_parse_operator_block_not():
    content = '<logic><not><ref id="a"/></not></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "not"
    assert result["refs"] == ["a"]


def test_parse_operator_block_non():
    content = '<logic><non><ref id="a"/></non></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "non"
    assert result["refs"] == ["a"]


def test_parse_operator_block_non_rejects_multiple():
    """NON with more than 1 child should return None."""
    content = '<logic><non><ref id="a"/><ref id="b"/></non></logic>'
    assert parse_operator_block(content) is None


def test_parse_operator_block_not_rejects_multiple():
    """NOT with more than 1 child should return None."""
    content = '<logic><not><ref id="a"/><ref id="b"/></not></logic>'
    assert parse_operator_block(content) is None


def test_parse_operator_block_and_rejects_single():
    """AND with fewer than 2 children should return None."""
    content = '<logic><and><ref id="a"/></and></logic>'
    assert parse_operator_block(content) is None


def test_parse_operator_block_not_operator():
    assert parse_operator_block('<fact>Just a fact.</fact>') is None
    assert parse_operator_block("") is None
    assert parse_operator_block("<provider />") is None


def test_parse_operator_block_legacy_ref():
    """Legacy <ref>text</ref> format should still be parsed."""
    content = "<and><ref>a</ref><ref>b</ref></and>"
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "and"
    assert result["refs"] == ["a", "b"]


def test_parse_operator_block_legacy_child():
    """Legacy <child id="..."/> format should still be parsed."""
    content = '<and><child id="a"/><child id="b"/></and>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "and"
    assert result["refs"] == ["a", "b"]


def test_parse_operator_block_inline_facts():
    """Inline <fact> operands should be extracted."""
    content = '<logic><and><fact id="f1" DoT="0.8">Sky is blue.</fact><fact id="f2" DoT="0.6">Grass is green.</fact></and></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "and"
    assert result["refs"] == ["f1", "f2"]
    assert len(result["inline_entries"]) == 2
    assert result["inline_entries"][0]["id"] == "f1"
    assert abs(result["inline_entries"][0]["trust"] - 0.8) < 1e-9


def test_parse_operator_block_inline_feeling():
    """Inline <feeling> operands should be extracted."""
    content = '<logic><not><feeling id="g1">I like cats.</feeling></not></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "not"
    assert result["refs"] == ["g1"]
    assert len(result["inline_entries"]) == 1
    assert result["inline_entries"][0]["id"] == "g1"


def test_parse_operator_block_mixed_operands():
    """Mixed refs and inline operands."""
    content = '<logic><or><ref id="existing"/><fact id="inline_f" DoT="0.5">Inline fact.</fact></or></logic>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "or"
    assert result["refs"] == ["existing", "inline_f"]
    assert len(result["inline_entries"]) == 1


# ─── ensure_operator_id tests ───


def test_ensure_operator_id_preserves_existing():
    entry = {"id": "existing_01", "content": '<logic><and><ref id="a"/><ref id="b"/></and></logic>'}
    assert ensure_operator_id(entry) == "existing_01"


def test_ensure_operator_id_generates():
    entry = {"content": '<logic><and><ref id="a"/><ref id="b"/></and></logic>'}
    oid = ensure_operator_id(entry)
    # Generated IDs are deterministic UUIDs (36 chars with dashes).
    assert len(oid) == 36 and oid.count("-") == 4
    assert entry["id"] == oid


# ─── compute_derived_truth: AND (min) ───


def test_and_min():
    """AND should derive min of operands."""
    entries = [
        _make_trust("a", 1.0),
        _make_trust("b", 0.7),
        _make_and("op", ["a", "b"]),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - 0.7) < 1e-9, f"Expected op=0.7, got {derived['op']}"


def test_and_with_negative():
    """AND with a negative operand should yield the minimum."""
    entries = [
        _make_trust("a", 1.0),
        _make_trust("b", -0.5),
        _make_and("op", ["a", "b"]),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-0.5)) < 1e-9


# ─── compute_derived_truth: OR (max) ───


def test_or_max():
    """OR should derive max of operands."""
    entries = [
        _make_trust("a", 0.3),
        _make_trust("b", 0.8),
        _make_or("op", ["a", "b"]),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - 0.8) < 1e-9


def test_or_with_negative():
    """OR with all negative operands should yield the least negative."""
    entries = [
        _make_trust("a", -0.9),
        _make_trust("b", -0.3),
        _make_or("op", ["a", "b"]),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-0.3)) < 1e-9


# ─── compute_derived_truth: NOT (negate) ───


def test_not_negate():
    """NOT should negate the operand."""
    entries = [
        _make_trust("a", 0.8),
        _make_not("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-0.8)) < 1e-9


def test_not_double_negation():
    """NOT(NOT(a)) should equal a."""
    entries = [
        _make_trust("a", 0.6),
        _make_not("op1", "a"),
        _make_not("op2", "op1"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op2"] - 0.6) < 1e-9


# ─── NON (non-affirming negation) ───


def test_non_positive():
    """NON of positive trust: 1 - 2*0.8 = -0.6"""
    entries = [
        _make_trust("a", 0.8),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-0.6)) < 1e-9


def test_non_negative():
    """NON of negative trust: 1 - 2*0.9 = -0.8"""
    entries = [
        _make_trust("a", -0.9),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-0.8)) < 1e-9


def test_non_zero():
    """NON of zero trust should be +1.0 (maximum openness)."""
    entries = [
        _make_trust("a", 0.0),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - 1.0) < 1e-9


def test_non_full_belief():
    """NON of +1.0 should be -1.0 (fully certain → fully closed)."""
    entries = [
        _make_trust("a", 1.0),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-1.0)) < 1e-9


def test_non_full_disbelief():
    """NON of -1.0 should be -1.0 (fully certain → fully closed)."""
    entries = [
        _make_trust("a", -1.0),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-1.0)) < 1e-9


def test_non_symmetry():
    """NON should be symmetric: non(+x) == non(-x) for any x."""
    entries = [
        _make_trust("pos", 0.7),
        _make_trust("neg", -0.7),
        _make_non("op_pos", "pos"),
        _make_non("op_neg", "neg"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op_pos"] - derived["op_neg"]) < 1e-9


# ─── Chaining ───


def test_chain_and_or():
    """AND feeding into OR should propagate through fixed-point iteration."""
    entries = [
        _make_trust("a", 1.0),
        _make_trust("b", 0.5),
        _make_trust("c", -0.3),
        _make_and("op_and", ["a", "b"]),  # min(1.0, 0.5) = 0.5
        _make_or("op_or", ["op_and", "c"]),  # max(0.5, -0.3) = 0.5
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op_and"] - 0.5) < 1e-9
    assert abs(derived["op_or"] - 0.5) < 1e-9


# ─── Cycle termination ───


def test_cycle_terminates():
    """Operators referencing each other should converge, not loop."""
    # op1 = and(a, op2), op2 = or(b, op1)
    # With a=1.0, b=0.5, initial op1=0, op2=0:
    # Iter 1: op1 = min(1.0, 0.0) = 0.0;  op2 = max(0.5, 0.0) = 0.5
    # Iter 2: op1 = min(1.0, 0.5) = 0.5;  op2 = max(0.5, 0.5) = 0.5
    # Iter 3: op1 = min(1.0, 0.5) = 0.5;  op2 = max(0.5, 0.5) = 0.5  → stable
    entries = [
        _make_trust("a", 1.0),
        _make_trust("b", 0.5),
        _make_and("op1", ["a", "op2"]),
        _make_or("op2", ["b", "op1"]),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op1"] - 0.5) < 1e-9
    assert abs(derived["op2"] - 0.5) < 1e-9


# ─── No operators ───


def test_no_operators():
    """Without operator entries, certainties pass through unchanged."""
    entries = [
        _make_trust("a", 0.8),
        _make_trust("b", -0.5),
    ]
    derived = compute_derived_truth(entries)
    assert derived["a"] == 0.8
    assert derived["b"] == -0.5


# ─── Integration with hme.xml ───


def test_hme_xml_operators():
    """Load test/hme.xml and verify derived truth for operator entries."""
    hme_path = os.path.join(os.path.dirname(__file__), "hme.xml")
    if not os.path.exists(hme_path):
        return  # skip if file not present

    from state import load_state_file
    state = load_state_file(hme_path, strict=True)
    entries = state.get("truth", [])

    derived = compute_derived_truth(entries)

    # op_socrates_mortal: and(axiom_01=1.0, axiom_02=1.0) → min = 1.0
    assert derived.get("op_socrates_mortal") == 1.0, \
        f"Socrates operator failed: got {derived.get('op_socrates_mortal')}"

    # op_whales_warm: and(axiom_03=1.0, axiom_04=1.0) → min = 1.0
    assert derived.get("op_whales_warm") == 1.0, \
        f"Whales operator failed: got {derived.get('op_whales_warm')}"

    # op_penguin_flight: and(soft_01=0.8, axiom_05=1.0) → min = 0.8
    assert abs(derived.get("op_penguin_flight") - 0.8) < 1e-9, \
        f"Penguin flight AND failed: got {derived.get('op_penguin_flight')}"

    # op_not_penguin_fly: not(false_01=-0.9) → 0.9
    assert abs(derived.get("op_not_penguin_fly") - 0.9) < 1e-9, \
        f"Penguin NOT failed: got {derived.get('op_not_penguin_fly')}"

    # Axioms should remain unchanged
    assert derived.get("axiom_01") == 1.0
    assert derived.get("axiom_02") == 1.0


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
