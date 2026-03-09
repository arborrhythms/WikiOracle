#!/usr/bin/env python3
"""Unit tests for DegreeOfTruth computation and server truth table operations.

Tests:
  - compute_degree_of_truth: agreement scoring between server and client
  - merge_client_truth: slow-moving average merge of client entries
  - load_server_truth / save_server_truth: XML persistence
  - _is_server_storable: filter out feelings and providers
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

from truth import (
    compute_degree_of_truth,
    load_server_truth,
    merge_client_truth,
    resolve_entries,
    resolve_reference,
    resolve_provider,
    save_server_truth,
    validate_operator_operands,
    _is_server_storable,
    _normalize_trust_entry,
)
from sensation import strip_feelings_from_training


def _fact(id, trust, title="test"):
    return {"type": "truth", "id": id, "trust": trust, "title": title,
            "content": f"<fact>{title}</fact>", "time": "2025-01-01T00:00:00Z"}


def _feeling(id, trust, title="feeling"):
    return {"type": "truth", "id": id, "trust": trust, "title": title,
            "content": f"<feeling>{title}</feeling>", "time": "2025-01-01T00:00:00Z"}


def _provider(id, trust, title="prov"):
    return {"type": "truth", "id": id, "trust": trust, "title": title,
            "content": f'<provider><api_url>http://test</api_url></provider>',
            "time": "2025-01-01T00:00:00Z"}


def _reference(id, trust, title="ref"):
    return {"type": "truth", "id": id, "trust": trust, "title": title,
            "content": f'<reference href="http://test">{title}</reference>',
            "time": "2025-01-01T00:00:00Z"}


# ---------------------------------------------------------------------------
# compute_degree_of_truth
# ---------------------------------------------------------------------------
class TestDegreeOfTruth(unittest.TestCase):

    def test_identical_tables_return_1(self):
        """When server and client have identical trust values, DoT = +1.0."""
        server = [_fact("a", 0.8), _fact("b", -0.5)]
        client = [_fact("a", 0.8), _fact("b", -0.5)]
        assert compute_degree_of_truth(server, client) == 1.0

    def test_maximally_different_return_neg1(self):
        """When trust values are maximally opposed (-1 vs +1), DoT = -1.0."""
        server = [_fact("a", 1.0)]
        client = [_fact("a", -1.0)]
        assert compute_degree_of_truth(server, client) == -1.0

    def test_disjoint_tables_return_0(self):
        """When no entries are shared, DoT = 0.0 (no signal)."""
        server = [_fact("a", 0.8)]
        client = [_fact("b", 0.5)]
        assert compute_degree_of_truth(server, client) == 0.0

    def test_partial_agreement(self):
        """Partial agreement produces a value between -1 and +1."""
        server = [_fact("a", 0.8), _fact("b", 0.0)]
        client = [_fact("a", 0.4), _fact("b", 0.0)]
        dot = compute_degree_of_truth(server, client)
        # agreement for a: 1 - |0.8 - 0.4|/2 = 0.8
        # agreement for b: 1 - |0 - 0|/2 = 1.0
        # mean agreement: (0.8 + 1.0) / 2 = 0.9
        # DoT = 2 * 0.9 - 1 = 0.8
        assert abs(dot - 0.8) < 1e-9

    def test_empty_server_returns_0(self):
        """Empty server truth → no shared entries → 0.0."""
        server = []
        client = [_fact("a", 0.8)]
        assert compute_degree_of_truth(server, client) == 0.0

    def test_empty_client_returns_0(self):
        """Empty client truth → no shared entries → 0.0."""
        server = [_fact("a", 0.8)]
        client = []
        assert compute_degree_of_truth(server, client) == 0.0

    def test_single_shared_entry(self):
        """Single entry partial agreement."""
        server = [_fact("x", 0.6)]
        client = [_fact("x", 0.2)]
        dot = compute_degree_of_truth(server, client)
        # agreement = 1 - |0.6 - 0.2|/2 = 0.8
        # DoT = 2 * 0.8 - 1 = 0.6
        expected = 0.6
        assert abs(dot - expected) < 1e-9


# ---------------------------------------------------------------------------
# merge_client_truth
# ---------------------------------------------------------------------------
class TestMergeClientTruth(unittest.TestCase):

    def test_new_entry_inserted(self):
        """An entry not on the server gets inserted."""
        server = [_fact("a", 0.8)]
        client = [_fact("b", 0.5)]
        result = merge_client_truth(server, client, merge_rate=0.1, author="user1")
        ids = {e["id"] for e in result}
        assert "a" in ids
        assert "b" in ids
        b = next(e for e in result if e["id"] == "b")
        assert b["author"] == "user1"

    def test_existing_entry_slow_averaged(self):
        """An existing entry is nudged toward the client value."""
        server = [_fact("a", 0.0)]
        client = [_fact("a", 1.0)]
        result = merge_client_truth(server, client, merge_rate=0.1)
        a = next(e for e in result if e["id"] == "a")
        # 0.0 + 0.1 * (1.0 - 0.0) = 0.1
        assert abs(a["trust"] - 0.1) < 1e-9

    def test_merge_rate_controls_speed(self):
        """Higher merge_rate → faster convergence."""
        server = [_fact("a", 0.0)]
        client = [_fact("a", 1.0)]
        result = merge_client_truth(server, client, merge_rate=0.5)
        a = next(e for e in result if e["id"] == "a")
        assert abs(a["trust"] - 0.5) < 1e-9

    def test_skip_feelings(self):
        """Feelings should not be stored in the server truth table."""
        server = [_fact("a", 0.8)]
        client = [_feeling("f1", 0.5)]
        result = merge_client_truth(server, client, merge_rate=0.1)
        ids = {e["id"] for e in result}
        assert "f1" not in ids

    def test_skip_providers(self):
        """Providers should not be stored in the server truth table."""
        server = [_fact("a", 0.8)]
        client = [_provider("p1", 0.9)]
        result = merge_client_truth(server, client, merge_rate=0.1)
        ids = {e["id"] for e in result}
        assert "p1" not in ids

    def test_raw_references_not_stored(self):
        """Raw references should not be stored (must be resolved first)."""
        server = []
        client = [_reference("r1", 0.7)]
        result = merge_client_truth(server, client, merge_rate=0.1, author="u1")
        ids = {e["id"] for e in result}
        assert "r1" not in ids

    def test_resolved_references_stored(self):
        """References resolved to facts should be stored."""
        server = []
        ref = _reference("r1", 0.7, title="claim")
        resolved = resolve_entries([ref])
        result = merge_client_truth(server, resolved, merge_rate=0.1, author="u1")
        # Should have the resolved fact
        assert len(result) == 1
        assert "<fact" in result[0].get("content", "")

    def test_trust_clamped(self):
        """Trust values are clamped to [-1, 1]."""
        server = [_fact("a", 0.9)]
        client = [_fact("a", 1.5)]  # out of range
        result = merge_client_truth(server, client, merge_rate=1.0)
        a = next(e for e in result if e["id"] == "a")
        assert a["trust"] <= 1.0


# ---------------------------------------------------------------------------
# Server truth persistence
# ---------------------------------------------------------------------------
class TestServerTruthPersistence(unittest.TestCase):

    def test_save_and_load(self):
        """Round-trip save/load preserves entries."""
        entries = [_fact("a", 0.8), _fact("b", -0.3)]
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            path = Path(f.name)
        try:
            save_server_truth(path, entries)
            loaded = load_server_truth(path)
            ids = {e["id"] for e in loaded}
            assert "a" in ids
            assert "b" in ids
            a = next(e for e in loaded if e["id"] == "a")
            assert abs(a["trust"] - 0.8) < 1e-9
        finally:
            path.unlink(missing_ok=True)

    def test_load_nonexistent_returns_empty(self):
        """Loading from a missing file returns an empty list."""
        result = load_server_truth(Path("/tmp/nonexistent_truth_12345.xml"))
        assert result == []

    def test_atomic_write(self):
        """Save replaces the file atomically (no partial writes)."""
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            path = Path(f.name)
        try:
            save_server_truth(path, [_fact("a", 0.5)])
            save_server_truth(path, [_fact("b", 0.9)])
            loaded = load_server_truth(path)
            ids = {e["id"] for e in loaded}
            assert "b" in ids
            assert "a" not in ids  # replaced, not appended
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _is_server_storable
# ---------------------------------------------------------------------------
class TestIsServerStorable(unittest.TestCase):

    def test_fact_is_storable(self):
        assert _is_server_storable(_fact("a", 0.5)) is True

    def test_feeling_not_storable(self):
        assert _is_server_storable(_feeling("a", 0.5)) is False

    def test_provider_not_storable(self):
        assert _is_server_storable(_provider("a", 0.5)) is False

    def test_reference_not_storable(self):
        """Raw references are not storable (must be resolved to facts first)."""
        assert _is_server_storable(_reference("a", 0.5)) is False

    def test_authority_not_storable(self):
        """Raw authorities are not storable (must be resolved to facts first)."""
        entry = {"id": "auth1", "trust": 0.8,
                 "content": '<authority url="https://example.com"/>',
                 "time": "2025-01-01T00:00:00Z"}
        assert _is_server_storable(entry) is False

    def test_operator_is_storable(self):
        """Operators (and, or, not, non) are storable."""
        entry = {"id": "op1", "trust": 0.5,
                 "content": '<logic><and><ref id="a"/><ref id="b"/></and></logic>',
                 "time": "2025-01-01T00:00:00Z"}
        assert _is_server_storable(entry) is True


# ---------------------------------------------------------------------------
# resolve_reference
# ---------------------------------------------------------------------------
class TestResolveReference(unittest.TestCase):

    def test_reference_with_text(self):
        """Reference with text → fact with src= domain."""
        entry = _reference("r1", 0.7, title="Paris is the capital")
        resolved = resolve_reference(entry)
        assert "<fact" in resolved["content"]
        assert 'src="test"' in resolved["content"]
        assert "Paris is the capital" in resolved["content"]
        assert resolved["id"] == "r1"

    def test_reference_url_only(self):
        """Reference with URL only → fact with src, self-closing."""
        entry = {"type": "truth", "id": "r2", "trust": 0.5, "title": "ref",
                 "content": '<reference href="https://example.com"/>',
                 "time": "2025-01-01T00:00:00Z"}
        resolved = resolve_reference(entry)
        assert "<fact" in resolved["content"]
        assert 'src="example.com"' in resolved["content"]

    def test_non_reference_passthrough(self):
        """Non-reference entries pass through unchanged."""
        entry = _fact("f1", 0.8)
        resolved = resolve_reference(entry)
        assert resolved is entry

    def test_preserves_trust(self):
        """Resolved entry preserves trust value."""
        entry = _reference("r1", 0.7, title="claim")
        resolved = resolve_reference(entry)
        assert abs(resolved["trust"] - 0.7) < 1e-9


# ---------------------------------------------------------------------------
# resolve_provider
# ---------------------------------------------------------------------------
class TestResolveProvider(unittest.TestCase):

    def test_provider_becomes_feeling(self):
        """Provider entry → feeling entry."""
        entry = {"type": "truth", "id": "p1", "trust": 0.6, "title": "prov",
                 "content": '<provider><api_url>http://test</api_url><model>claude</model></provider>',
                 "time": "2025-01-01T00:00:00Z"}
        resolved = resolve_provider(entry)
        assert "<feeling>" in resolved["content"]
        assert "Provider:" in resolved["content"]
        assert "<provider" not in resolved["content"]
        assert resolved["id"] == "p1"

    def test_non_provider_passthrough(self):
        """Non-provider entries pass through unchanged."""
        entry = _fact("f1", 0.8)
        resolved = resolve_provider(entry)
        assert resolved is entry


# ---------------------------------------------------------------------------
# resolve_entries
# ---------------------------------------------------------------------------
class TestResolveEntries(unittest.TestCase):

    def test_facts_pass_through(self):
        """Facts are unchanged by resolve_entries."""
        entries = [_fact("a", 0.8)]
        resolved = resolve_entries(entries)
        assert len(resolved) == 1
        assert resolved[0]["content"] == entries[0]["content"]

    def test_feelings_pass_through(self):
        """Feelings pass through unchanged (still feelings)."""
        entries = [_feeling("f1", 0.5)]
        resolved = resolve_entries(entries)
        assert len(resolved) == 1
        assert "<feeling>" in resolved[0]["content"]

    def test_references_resolved(self):
        """References become facts."""
        entries = [_reference("r1", 0.7, title="claim")]
        resolved = resolve_entries(entries)
        assert len(resolved) == 1
        assert "<fact" in resolved[0]["content"]
        assert "<reference" not in resolved[0]["content"]

    def test_providers_resolved(self):
        """Providers become feelings."""
        entries = [_provider("p1", 0.9)]
        resolved = resolve_entries(entries)
        assert len(resolved) == 1
        assert "<feeling>" in resolved[0]["content"]
        assert "<provider" not in resolved[0]["content"]

    def test_mixed_entries(self):
        """Mix of types → correctly resolved list."""
        entries = [
            _fact("f1", 0.8),
            _feeling("f2", 0.5),
            _reference("r1", 0.7, title="claim"),
            _provider("p1", 0.9),
        ]
        resolved = resolve_entries(entries)
        assert len(resolved) == 4
        # fact unchanged
        assert "<fact>" in resolved[0]["content"]
        # feeling unchanged
        assert "<feeling>" in resolved[1]["content"]
        # reference → fact
        assert "<fact" in resolved[2]["content"] and "src=" in resolved[2]["content"]
        # provider → feeling
        assert "<feeling>" in resolved[3]["content"]


# ---------------------------------------------------------------------------
# validate_operator_operands
# ---------------------------------------------------------------------------
class TestValidateOperatorOperands(unittest.TestCase):

    def test_operator_over_facts_accepted(self):
        """Operator whose leaf operands are all facts passes validation."""
        entries = [
            _fact("a", 0.8),
            _fact("b", 0.6),
            {"id": "op1", "trust": 0.7,
             "content": '<logic><and><ref id="a"/><ref id="b"/></and></logic>',
             "time": "2025-01-01T00:00:00Z"},
        ]
        result = validate_operator_operands(entries)
        ids = {e["id"] for e in result}
        assert "op1" in ids
        assert "a" in ids
        assert "b" in ids

    def test_operator_over_feeling_accepted(self):
        """Operators may now compose feelings — all entries pass through."""
        entries = [
            _fact("a", 0.8),
            _feeling("f1", 0.5),
            {"id": "op1", "trust": 0.7,
             "content": '<logic><and><ref id="a"/><ref id="f1"/></and></logic>',
             "time": "2025-01-01T00:00:00Z"},
        ]
        result = validate_operator_operands(entries)
        ids = {e["id"] for e in result}
        assert "op1" in ids
        assert "a" in ids
        assert "f1" in ids

    def test_non_operators_pass_through(self):
        """Non-operator entries always pass through."""
        entries = [_fact("a", 0.8), _feeling("f1", 0.5)]
        result = validate_operator_operands(entries)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# strip_feelings_from_training
# ---------------------------------------------------------------------------
class TestStripFeelingsFromTraining(unittest.TestCase):

    def test_feelings_stripped(self):
        """Feeling blocks removed from training messages."""
        messages = [
            {"role": "assistant",
             "content": "<R><feeling>Great question!</feeling>"
                        "<fact>Paris is the capital of France.</fact></R>"},
        ]
        result = strip_feelings_from_training(messages)
        assert len(result) == 1
        assert "<feeling>" not in result[0]["content"]
        assert "<fact>" in result[0]["content"]

    def test_facts_preserved(self):
        """Fact blocks preserved in training messages."""
        messages = [
            {"role": "assistant",
             "content": "<R><fact>The sky is blue.</fact></R>"},
        ]
        result = strip_feelings_from_training(messages)
        assert len(result) == 1
        assert "<fact>The sky is blue.</fact>" in result[0]["content"]

    def test_empty_after_strip_removed(self):
        """Messages that become empty after stripping are removed."""
        messages = [
            {"role": "assistant",
             "content": "<feeling>I feel great!</feeling>"},
        ]
        result = strip_feelings_from_training(messages)
        assert len(result) == 0

    def test_self_closing_feelings_stripped(self):
        """Self-closing <feeling/> tags are also stripped."""
        messages = [
            {"role": "assistant",
             "content": '<fact>test</fact><feeling type="joy"/>'},
        ]
        result = strip_feelings_from_training(messages)
        assert len(result) == 1
        assert "<feeling" not in result[0]["content"]
        assert "<fact>" in result[0]["content"]
