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
    save_server_truth,
    _is_server_storable,
    _normalize_trust_entry,
)


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

    def test_references_are_stored(self):
        """References should be stored."""
        server = []
        client = [_reference("r1", 0.7)]
        result = merge_client_truth(server, client, merge_rate=0.1, author="u1")
        ids = {e["id"] for e in result}
        assert "r1" in ids

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

    def test_reference_is_storable(self):
        assert _is_server_storable(_reference("a", 0.5)) is True
