#!/usr/bin/env python3
"""Unit tests for the authority trust entry type.

Tests parsing, ID generation, resolution (fetch + trust scaling),
caching, security constraints, and integration with hme.xml test data.
"""

import json
import os
import sys
import tempfile
import time
from unittest.mock import patch

# Add bin/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))

from truth import (
    parse_authority_block,
    ensure_authority_id,
    get_authority_entries,
    resolve_authority_entries,
    _AUTHORITY_CACHE,
)


def _make_temp_entries(records):
    """Create a temp JSONL file and return (path, entries_list).

    The returned entries_list is what _fetch_authority would return
    for valid truth/trust records.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
        tmp_path = f.name
    entries = [r for r in records if isinstance(r, dict) and r.get("type") in ("truth", "trust")]
    return tmp_path, entries


# ─── parse_authority_block tests ───


def test_parse_authority_block_attribute_style():
    content = '<authority url="https://example.com/kb.jsonl" />'
    result = parse_authority_block(content)
    assert result is not None
    assert result["url"] == "https://example.com/kb.jsonl"
    assert result["refresh"] == 3600  # default


def test_parse_authority_block_child_style():
    content = """<authority>
        <url>https://child.example/kb.jsonl</url>
        <refresh>7200</refresh>
    </authority>"""
    result = parse_authority_block(content)
    assert result is not None
    assert result["url"] == "https://child.example/kb.jsonl"
    assert result["refresh"] == 7200


def test_parse_authority_block_mixed_style():
    """Attribute style with some child elements."""
    content = '<authority url="https://mixed.example/kb.jsonl"><refresh>1800</refresh></authority>'
    result = parse_authority_block(content)
    assert result is not None
    assert result["url"] == "https://mixed.example/kb.jsonl"
    assert result["refresh"] == 1800


def test_parse_authority_block_not_authority():
    assert parse_authority_block("<p>Just a fact.</p>") is None
    assert parse_authority_block("") is None
    assert parse_authority_block("<provider name='x' />") is None
    assert parse_authority_block("<implication><antecedent>a</antecedent><consequent>b</consequent></implication>") is None


def test_parse_authority_block_no_url():
    """URL is required; should return None if missing."""
    content = '<authority />'
    result = parse_authority_block(content)
    assert result is None


def test_parse_authority_block_bad_refresh():
    """Non-numeric refresh should default to 3600."""
    content = '<authority url="https://example.com/kb.jsonl" refresh="bad" />'
    result = parse_authority_block(content)
    assert result is not None
    assert result["refresh"] == 3600


# ─── ensure_authority_id tests ───


def test_ensure_authority_id_preserves_existing():
    entry = {"id": "a_existing_01", "content": '<authority url="https://example.com/kb.jsonl" />'}
    assert ensure_authority_id(entry) == "a_existing_01"


def test_ensure_authority_id_generates():
    entry = {"content": '<authority url="https://gen.example/kb.jsonl" />'}
    aid = ensure_authority_id(entry)
    # Generated IDs are deterministic UUIDs (36 chars with dashes)
    assert len(aid) == 36 and aid.count("-") == 4
    assert entry["id"] == aid


def test_ensure_authority_id_deterministic():
    """Same content should always produce the same ID."""
    content = '<authority url="https://det.example/kb.jsonl" />'
    entry1 = {"content": content}
    entry2 = {"content": content}
    id1 = ensure_authority_id(entry1)
    id2 = ensure_authority_id(entry2)
    assert id1 == id2


# ─── get_authority_entries tests ───


def test_get_authority_entries():
    entries = [
        {"id": "t_fact", "trust": 0.5, "content": "<fact>A fact.</fact>", "time": "2026-01-01T00:00:00Z"},
        {"id": "a_auth_01", "trust": 0.8, "content": '<authority url="https://a.example/kb.jsonl" />', "time": "2026-01-02T00:00:00Z"},
        {"id": "i_impl", "trust": 0.0, "content": "<implication><antecedent>a</antecedent><consequent>b</consequent></implication>", "time": "2026-01-03T00:00:00Z"},
        {"id": "a_auth_02", "trust": 0.6, "content": '<authority url="https://b.example/kb.jsonl" />', "time": "2026-01-04T00:00:00Z"},
    ]
    result = get_authority_entries(entries)
    assert len(result) == 2
    # Should be sorted by trust descending
    assert result[0][0]["id"] == "a_auth_01"
    assert result[1][0]["id"] == "a_auth_02"


# ─── resolve_authority_entries tests ───


def test_resolve_authority_entries_file_protocol_blocked():
    """file:// authority URLs should be blocked (security: SSRF prevention)."""
    _AUTHORITY_CACHE.clear()

    tmp_path, _ = _make_temp_entries([
        {"type": "truth", "id": "t_r1", "title": "Remote 1", "trust": 1.0, "content": "<fact>Fact 1</fact>", "time": "2026-01-01T00:00:00Z"},
    ])
    try:
        authority_entries = [
            (
                {"id": "a_test", "trust": 0.5, "content": f'<authority url="file://{tmp_path}" />'},
                {"url": f"file://{tmp_path}", "refresh": 3600},
            )
        ]
        results = resolve_authority_entries(authority_entries, timeout_s=5)
        assert len(results) == 1
        _, scaled = results[0]
        assert scaled == [], "file:// authority URLs must be blocked"
    finally:
        os.unlink(tmp_path)


def test_resolve_authority_entries_with_mock():
    """Test authority resolution and trust scaling using mocked fetch."""
    _AUTHORITY_CACHE.clear()

    mock_entries = [
        {"type": "truth", "id": "t_r1", "title": "Remote 1", "trust": 1.0, "content": "<fact>Fact 1</fact>", "time": "2026-01-01T00:00:00Z"},
        {"type": "truth", "id": "t_r2", "title": "Remote 2", "trust": 0.8, "content": "<fact>Fact 2</fact>", "time": "2026-01-01T00:00:01Z"},
    ]

    authority_entries = [
        (
            {"id": "a_test", "trust": 0.5, "content": '<authority url="https://example.com/kb.jsonl" />'},
            {"url": "https://example.com/kb.jsonl", "refresh": 3600},
        )
    ]

    with patch("truth._fetch_authority", return_value=mock_entries):
        results = resolve_authority_entries(authority_entries, timeout_s=5)
    assert len(results) == 1
    auth_entry, scaled = results[0]
    assert len(scaled) == 2

    # Trust scaling: 0.5 * 1.0 = 0.5
    r1 = next(s for s in scaled if s["id"] == "a_test:t_r1")
    assert abs(r1["trust"] - 0.5) < 1e-9, f"Expected 0.5, got {r1['trust']}"

    # Trust scaling: 0.5 * 0.8 = 0.4
    r2 = next(s for s in scaled if s["id"] == "a_test:t_r2")
    assert abs(r2["trust"] - 0.4) < 1e-9, f"Expected 0.4, got {r2['trust']}"


def test_resolve_authority_id_namespacing():
    """Imported IDs should be prefixed with authority ID."""
    _AUTHORITY_CACHE.clear()

    mock_entries = [
        {"type": "truth", "id": "t_fact_42", "title": "Fact", "trust": 1.0, "content": "<fact>X</fact>", "time": "2026-01-01T00:00:00Z"},
    ]

    authority_entries = [
        (
            {"id": "a_ns_test", "trust": 0.7, "content": '<authority url="https://example.com/kb.jsonl" />'},
            {"url": "https://example.com/kb.jsonl", "refresh": 3600},
        )
    ]
    with patch("truth._fetch_authority", return_value=mock_entries):
        results = resolve_authority_entries(authority_entries, timeout_s=5)
    scaled = results[0][1]
    assert scaled[0]["id"] == "a_ns_test:t_fact_42"


def test_resolve_authority_skips_nested_authorities():
    """Remote JSONL with <authority> entries should have those entries skipped."""
    _AUTHORITY_CACHE.clear()

    mock_entries = [
        {"type": "truth", "id": "t_ok", "title": "OK", "trust": 1.0, "content": "<fact>Fine</fact>", "time": "2026-01-01T00:00:00Z"},
        {"type": "truth", "id": "a_nested", "title": "Nested Authority", "trust": 0.9, "content": '<authority url="https://other.example/kb.jsonl" />', "time": "2026-01-01T00:00:01Z"},
    ]

    authority_entries = [
        (
            {"id": "a_parent", "trust": 0.8, "content": '<authority url="https://example.com/kb.jsonl" />'},
            {"url": "https://example.com/kb.jsonl", "refresh": 3600},
        )
    ]
    with patch("truth._fetch_authority", return_value=mock_entries):
        results = resolve_authority_entries(authority_entries, timeout_s=5)
    scaled = results[0][1]
    assert len(scaled) == 1  # nested authority should be skipped
    assert scaled[0]["id"] == "a_parent:t_ok"


def test_resolve_authority_abbreviated_jsonl():
    """Handle JSONL with only trust entries (no header)."""
    _AUTHORITY_CACHE.clear()

    mock_entries = [
        {"type": "truth", "id": "t_a1", "title": "A1", "trust": 0.6, "content": "<fact>A1</fact>", "time": "2026-01-01T00:00:00Z"},
    ]

    authority_entries = [
        (
            {"id": "a_abbrev", "trust": 1.0, "content": '<authority url="https://example.com/kb.jsonl" />'},
            {"url": "https://example.com/kb.jsonl", "refresh": 3600},
        )
    ]
    with patch("truth._fetch_authority", return_value=mock_entries):
        results = resolve_authority_entries(authority_entries, timeout_s=5)
    scaled = results[0][1]
    assert len(scaled) == 1
    # 1.0 * 0.6 = 0.6
    assert abs(scaled[0]["trust"] - 0.6) < 1e-9


def test_resolve_authority_fetch_failure():
    """Non-existent file should return empty list for that authority."""
    _AUTHORITY_CACHE.clear()

    authority_entries = [
        (
            {"id": "a_missing", "trust": 0.5, "content": '<authority url="file:///nonexistent/path.jsonl" />'},
            {"url": "file:///nonexistent/path.jsonl", "refresh": 3600},
        )
    ]
    results = resolve_authority_entries(authority_entries, timeout_s=5)
    assert len(results) == 1
    assert results[0][1] == []  # empty list, no crash


def test_resolve_authority_negative_trust():
    """Negative authority trust should invert remote beliefs."""
    _AUTHORITY_CACHE.clear()

    mock_entries = [
        {"type": "truth", "id": "t_pos", "title": "Positive", "trust": 0.8, "content": "<fact>X</fact>", "time": "2026-01-01T00:00:00Z"},
    ]

    authority_entries = [
        (
            {"id": "a_neg", "trust": -0.5, "content": '<authority url="https://example.com/kb.jsonl" />'},
            {"url": "https://example.com/kb.jsonl", "refresh": 3600},
        )
    ]
    with patch("truth._fetch_authority", return_value=mock_entries):
        results = resolve_authority_entries(authority_entries, timeout_s=5)
    scaled = results[0][1]
    # -0.5 * 0.8 = -0.4
    assert abs(scaled[0]["trust"] - (-0.4)) < 1e-9


def test_resolve_authority_caching():
    """Second call within refresh window should use cache."""
    _AUTHORITY_CACHE.clear()

    mock_entries = [
        {"type": "truth", "id": "t_cached", "title": "Cached", "trust": 1.0, "content": "<fact>C</fact>", "time": "2026-01-01T00:00:00Z"},
    ]

    url = "https://example.com/cache-test.jsonl"
    authority_entries = [
        (
            {"id": "a_cache_test", "trust": 0.5, "content": f'<authority url="{url}" />'},
            {"url": url, "refresh": 3600},
        )
    ]

    # First call: populates cache
    with patch("truth._fetch_authority", return_value=mock_entries):
        results1 = resolve_authority_entries(authority_entries, timeout_s=5)
    assert len(results1[0][1]) == 1
    assert url in _AUTHORITY_CACHE

    # Second call: _fetch_authority returns [] but cache should still provide data
    with patch("truth._fetch_authority", return_value=[]):
        results2 = resolve_authority_entries(authority_entries, timeout_s=5)
    assert len(results2[0][1]) == 1


def test_resolve_authority_url_scheme_restriction():
    """HTTP (not HTTPS) URLs should be rejected."""
    _AUTHORITY_CACHE.clear()

    authority_entries = [
        (
            {"id": "a_http", "trust": 0.5, "content": '<authority url="http://insecure.example/kb.jsonl" />'},
            {"url": "http://insecure.example/kb.jsonl", "refresh": 3600},
        )
    ]
    results = resolve_authority_entries(authority_entries, timeout_s=5)
    assert len(results) == 1
    assert results[0][1] == []  # rejected, empty list


# ─── Integration with hme.xml ───


def test_hme_xml_authority_entry():
    """Load test/hme.xml and verify it contains an authority entry."""
    hme_path = os.path.join(os.path.dirname(__file__), "hme.xml")
    if not os.path.exists(hme_path):
        return  # skip if file not present

    from state import load_state_file
    state = load_state_file(hme_path, strict=True)
    entries = state.get("truth", [])

    authority_entries = get_authority_entries(entries)
    assert len(authority_entries) >= 1, "Expected at least one authority entry in hme.xml"

    # Verify the test authority
    test_auth = None
    for entry, config in authority_entries:
        if entry.get("id") == "auth_test_01":
            test_auth = (entry, config)
            break
    assert test_auth is not None, "auth_test_01 not found in hme.xml"
    assert test_auth[0]["trust"] == 0.5
    assert "hme_authority_fragment" in test_auth[1]["url"]


def test_hme_authority_resolution():
    """Resolve the test authority from hme.xml against the fragment file."""
    _AUTHORITY_CACHE.clear()
    hme_path = os.path.join(os.path.dirname(__file__), "hme.xml")
    fragment_path = os.path.join(os.path.dirname(__file__), "hme_authority_fragment.xml")
    if not os.path.exists(hme_path) or not os.path.exists(fragment_path):
        return  # skip if files not present

    from state import load_state_file

    # Load fragment entries to use as mock return value.
    fragment_state = load_state_file(fragment_path, strict=False)
    fragment_entries = fragment_state.get("truth", [])

    # Load hme state
    hme_state = load_state_file(hme_path, strict=True)
    entries = hme_state.get("truth", [])

    authority_entries = get_authority_entries(entries)

    # Mock _fetch_authority since the spec fixture uses file:// URLs
    # which are blocked in production.
    with patch("truth._fetch_authority", return_value=fragment_entries):
        results = resolve_authority_entries(authority_entries, timeout_s=5)

    # Find the result for auth_test_01
    for auth_entry, scaled in results:
        if auth_entry.get("id") == "auth_test_01":
            assert len(scaled) == 2, f"Expected 2 remote entries, got {len(scaled)}"
            # remote_01: 0.5 * 1.0 = 0.5
            r1 = next((s for s in scaled if "remote_01" in s["id"]), None)
            assert r1 is not None
            assert abs(r1["trust"] - 0.5) < 1e-9, f"Expected 0.5, got {r1['trust']}"
            # remote_02: 0.5 * 0.9 = 0.45
            r2 = next((s for s in scaled if "remote_02" in s["id"]), None)
            assert r2 is not None
            assert abs(r2["trust"] - 0.45) < 1e-9, f"Expected 0.45, got {r2['trust']}"
            return

    assert False, "auth_test_01 not found in resolved results"


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
