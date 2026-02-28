#!/usr/bin/env python3
"""Unit tests for the derived truth engine (compute_derived_truth).

Tests Strong Kleene operators (and/or/not/non), fixed-point iteration,
cycle termination, and integration with hme.jsonl test data.
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


def _make_trust(id, certainty, content=None, title=""):
    if content is None:
        content = f'<fact id="{id}" certainty="{certainty}" title="{title}">test</fact>'
    return {"type": "truth", "id": id, "certainty": certainty, "content": content, "title": title}


def _make_and(entry_id, refs, certainty=0.0):
    title = f"and({', '.join(refs)})"
    child_xml = "".join(f'<child id="{r}"/>' for r in refs)
    content = f'<and id="{entry_id}" certainty="{certainty}" title="{title}">{child_xml}</and>'
    return {"type": "truth", "id": entry_id, "certainty": certainty, "content": content, "title": title}


def _make_or(entry_id, refs, certainty=0.0):
    title = f"or({', '.join(refs)})"
    child_xml = "".join(f'<child id="{r}"/>' for r in refs)
    content = f'<or id="{entry_id}" certainty="{certainty}" title="{title}">{child_xml}</or>'
    return {"type": "truth", "id": entry_id, "certainty": certainty, "content": content, "title": title}


def _make_not(entry_id, ref, certainty=0.0):
    title = f"not({ref})"
    content = f'<not id="{entry_id}" certainty="{certainty}" title="{title}"><child id="{ref}"/></not>'
    return {"type": "truth", "id": entry_id, "certainty": certainty, "content": content, "title": title}


def _make_non(entry_id, ref, certainty=0.0):
    title = f"non({ref})"
    content = f'<non id="{entry_id}" certainty="{certainty}" title="{title}"><child id="{ref}"/></non>'
    return {"type": "truth", "id": entry_id, "certainty": certainty, "content": content, "title": title}


# ─── parse_operator_block tests ───


def test_parse_operator_block_and():
    content = '<and id="op" certainty="0.0"><child id="a"/><child id="b"/></and>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "and"
    assert result["refs"] == ["a", "b"]


def test_parse_operator_block_or():
    content = '<or id="op" certainty="0.0"><child id="x"/><child id="y"/><child id="z"/></or>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "or"
    assert result["refs"] == ["x", "y", "z"]


def test_parse_operator_block_not():
    content = '<not id="op" certainty="0.0"><child id="a"/></not>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "not"
    assert result["refs"] == ["a"]


def test_parse_operator_block_non():
    content = '<non id="op" certainty="0.0"><child id="a"/></non>'
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "non"
    assert result["refs"] == ["a"]


def test_parse_operator_block_non_rejects_multiple():
    """NON with more than 1 child should return None."""
    content = '<non id="op" certainty="0.0"><child id="a"/><child id="b"/></non>'
    assert parse_operator_block(content) is None


def test_parse_operator_block_not_rejects_multiple():
    """NOT with more than 1 child should return None."""
    content = '<not id="op" certainty="0.0"><child id="a"/><child id="b"/></not>'
    assert parse_operator_block(content) is None


def test_parse_operator_block_and_rejects_single():
    """AND with fewer than 2 children should return None."""
    content = '<and id="op" certainty="0.0"><child id="a"/></and>'
    assert parse_operator_block(content) is None


def test_parse_operator_block_not_operator():
    assert parse_operator_block('<fact id="x" certainty="1.0">Just a fact.</fact>') is None
    assert parse_operator_block("") is None
    assert parse_operator_block("<provider name='x' />") is None


def test_parse_operator_block_legacy_ref():
    """Legacy <ref>text</ref> format should still be parsed."""
    content = "<and><ref>a</ref><ref>b</ref></and>"
    result = parse_operator_block(content)
    assert result is not None
    assert result["operator"] == "and"
    assert result["refs"] == ["a", "b"]


# ─── ensure_operator_id tests ───


def test_ensure_operator_id_preserves_existing():
    entry = {"id": "existing_01", "content": '<and id="existing_01" certainty="0.0"><child id="a"/><child id="b"/></and>'}
    assert ensure_operator_id(entry) == "existing_01"


def test_ensure_operator_id_generates():
    entry = {"content": '<and certainty="0.0"><child id="a"/><child id="b"/></and>'}
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
    """NON of positive certainty: sign(0.8)*(1-0.8) = 0.2"""
    entries = [
        _make_trust("a", 0.8),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - 0.2) < 1e-9


def test_non_negative():
    """NON of negative certainty: sign(-0.9)*(1-0.9) = -0.1"""
    entries = [
        _make_trust("a", -0.9),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - (-0.1)) < 1e-9


def test_non_zero():
    """NON of zero certainty should be zero."""
    entries = [
        _make_trust("a", 0.0),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - 0.0) < 1e-9


def test_non_full_belief():
    """NON of +1.0 should be 0.0 (fully believed → no residual doubt)."""
    entries = [
        _make_trust("a", 1.0),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"] - 0.0) < 1e-9


def test_non_full_disbelief():
    """NON of -1.0 should be -0.0 (magnitude 0, sign negative)."""
    entries = [
        _make_trust("a", -1.0),
        _make_non("op", "a"),
    ]
    derived = compute_derived_truth(entries)
    assert abs(derived["op"]) < 1e-9


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


# ─── Integration with hme.jsonl ───


def test_hme_jsonl_operators():
    """Load spec/hme.jsonl and verify derived truth for operator entries."""
    hme_path = os.path.join(os.path.dirname(__file__), "..", "spec", "hme.jsonl")
    if not os.path.exists(hme_path):
        return  # skip if file not present

    with open(hme_path) as f:
        entries = []
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if rec.get("type") in ("truth", "trust"):
                    entries.append(rec)

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
