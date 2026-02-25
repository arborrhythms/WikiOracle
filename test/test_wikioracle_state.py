#!/usr/bin/env python3
"""Tests for wikioracle_state module (v2: conversation-based hierarchy)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bin/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from wikioracle_state import (
    ALLOWED_KEY_DIR,
    DEFAULT_OUTPUT,
    SCHEMA_URL,
    SCHEMA_URL_V1,
    SCHEMA_URL_V2,
    STATE_VERSION,
    StateValidationError,
    add_child_conversation,
    add_message_to_conversation,
    all_conversation_ids,
    all_message_ids,
    atomic_write_jsonl,
    build_context_draft,
    ensure_minimal_state,
    extract_context_deltas,
    find_conversation,
    get_ancestor_chain,
    get_context_messages,
    get_primary_provider,
    get_provider_entries,
    get_src_entries,
    jsonl_to_state,
    load_state_file,
    merge_llm_states,
    migrate_v1_to_v2,
    parse_provider_block,
    parse_src_block,
    remove_conversation,
    resolve_api_key,
    resolve_src_content,
    state_to_jsonl,
    utc_now_iso,
)


def _make_state(**overrides):
    """Create a minimal valid v2 state dict with optional overrides."""
    base = {
        "version": 2,
        "schema": SCHEMA_URL,
        "time": "2026-02-23T00:00:00Z",
        "context": "<div>Test</div>",
        "conversations": [],
        "selected_conversation": None,
        "truth": {"trust": []},
    }
    base.update(overrides)
    return base


def _make_conv(id, title, messages, children=None):
    """Shorthand to create a conversation node."""
    return {
        "id": id,
        "title": title,
        "messages": messages,
        "children": children or [],
    }


def _make_msg(id, role, username, content, time="2026-02-23T00:00:01Z"):
    """Shorthand to create a message."""
    return {
        "id": id,
        "role": role,
        "username": username,
        "time": time,
        "content": content,
    }


class TestEnsureMinimalState(unittest.TestCase):

    def test_defaults_from_empty(self):
        state = ensure_minimal_state({}, strict=False)
        self.assertEqual(state["version"], 2)
        self.assertEqual(state["schema"], SCHEMA_URL)
        self.assertIn("context", state)
        self.assertEqual(state["conversations"], [])
        self.assertIn("truth", state)
        self.assertIsNone(state["selected_conversation"])

    def test_strict_rejects_bad_version(self):
        with self.assertRaises(StateValidationError):
            ensure_minimal_state({"version": 99, "schema": SCHEMA_URL, "time": "2026-01-01T00:00:00Z",
                                  "context": "<div/>", "conversations": [], "truth": {"trust": []}}, strict=True)

    def test_strict_rejects_bad_schema(self):
        with self.assertRaises(StateValidationError):
            ensure_minimal_state({"version": 2, "schema": "bad", "time": "2026-01-01T00:00:00Z",
                                  "context": "<div/>", "conversations": [], "truth": {"trust": []}}, strict=True)

    def test_conversations_normalized(self):
        state = ensure_minimal_state(_make_state(conversations=[
            {"id": "c_1", "messages": [
                {"id": "m_1", "role": "user", "username": "Alec",
                 "time": "2026-02-23T00:00:01Z", "content": "Hello"}
            ]}
        ]), strict=True)
        conv = state["conversations"][0]
        self.assertEqual(conv["id"], "c_1")
        # Title is derived from first user message, not stored
        self.assertEqual(conv["title"], "Hello")
        self.assertEqual(len(conv["messages"]), 1)
        self.assertEqual(conv["messages"][0]["role"], "user")
        self.assertEqual(conv["children"], [])

    def test_trust_certainty_clamped(self):
        state = ensure_minimal_state(_make_state(truth={
            "trust": [{"title": "X", "certainty": 5.0, "content": "test", "time": "2026-01-01T00:00:00Z"}],
                    }), strict=True)
        self.assertEqual(state["truth"]["trust"][0]["certainty"], 1.0)

    def test_auto_migrates_v1(self):
        """V1 state with messages and parent_id is auto-migrated to v2."""
        v1 = {
            "version": 1,
            "schema": SCHEMA_URL_V1,
            "time": "2026-02-23T00:00:00Z",
            "context": "<div>V1</div>",
            "messages": [
                {"id": "m_1", "parent_id": None, "username": "Alec",
                 "time": "2026-02-23T00:00:01Z", "content": "<p>hello</p>"},
                {"id": "m_2", "parent_id": "m_1", "username": "WikiOracle NanoChat",
                 "time": "2026-02-23T00:00:02Z", "content": "<p>hi</p>"},
            ],
            "truth": {"trust": []},
        }
        state = ensure_minimal_state(v1, strict=False)
        self.assertEqual(state["version"], 2)
        self.assertNotIn("messages", state)
        self.assertGreaterEqual(len(state["conversations"]), 1)
        # Check first conversation has 2 messages
        conv = state["conversations"][0]
        self.assertEqual(len(conv["messages"]), 2)
        self.assertEqual(conv["messages"][0]["role"], "user")
        self.assertEqual(conv["messages"][1]["role"], "assistant")

    def test_removes_legacy_fields(self):
        state = ensure_minimal_state({
            "version": 2, "schema": SCHEMA_URL, "time": "2026-02-23T00:00:00Z",
            "context": "<div/>", "conversations": [],
            "messages": [{"id": "m_1"}],  # legacy
            "active_path": ["m_1"],  # legacy
            "truth": {"trust": []},
        }, strict=False)
        self.assertNotIn("messages", state)
        self.assertNotIn("active_path", state)


class TestV1MigrationDetailed(unittest.TestCase):

    def test_empty_messages(self):
        v2 = migrate_v1_to_v2({"version": 1, "messages": [], "truth": {"trust": []}})
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["conversations"], [])

    def test_linear_chain(self):
        v1 = {
            "version": 1,
            "messages": [
                {"id": "m_1", "parent_id": None, "username": "Alec",
                 "time": "2026-02-23T00:00:01Z", "content": "<p>Q1</p>"},
                {"id": "m_2", "parent_id": "m_1", "username": "Bot",
                 "time": "2026-02-23T00:00:02Z", "content": "<p>A1</p>"},
                {"id": "m_3", "parent_id": "m_2", "username": "Alec",
                 "time": "2026-02-23T00:00:03Z", "content": "<p>Q2</p>"},
                {"id": "m_4", "parent_id": "m_3", "username": "Bot",
                 "time": "2026-02-23T00:00:04Z", "content": "<p>A2</p>"},
            ],
            "truth": {"trust": []},
        }
        v2 = migrate_v1_to_v2(v1)
        # Linear chain = one conversation with 4 messages
        self.assertEqual(len(v2["conversations"]), 1)
        conv = v2["conversations"][0]
        self.assertEqual(len(conv["messages"]), 4)
        self.assertEqual(conv["children"], [])

    def test_branching(self):
        v1 = {
            "version": 1,
            "messages": [
                {"id": "m_1", "parent_id": None, "username": "Alec",
                 "time": "2026-02-23T00:00:01Z", "content": "<p>Root</p>"},
                {"id": "m_2", "parent_id": "m_1", "username": "Bot",
                 "time": "2026-02-23T00:00:02Z", "content": "<p>Reply</p>"},
                {"id": "m_3", "parent_id": "m_2", "username": "Alec",
                 "time": "2026-02-23T00:00:03Z", "content": "<p>Branch A</p>"},
                {"id": "m_4", "parent_id": "m_2", "username": "Alec",
                 "time": "2026-02-23T00:00:04Z", "content": "<p>Branch B</p>"},
            ],
            "truth": {"trust": []},
        }
        v2 = migrate_v1_to_v2(v1)
        # Root conversation has m_1, m_2 (chain stops at m_2 because 2 children)
        # Two child conversations: m_3 and m_4
        self.assertEqual(len(v2["conversations"]), 1)
        root_conv = v2["conversations"][0]
        self.assertEqual(len(root_conv["messages"]), 2)
        self.assertEqual(len(root_conv["children"]), 2)
        child_msgs = {len(c["messages"]) for c in root_conv["children"]}
        self.assertEqual(child_msgs, {1})  # each branch has 1 message


class TestJSONLRoundTrip(unittest.TestCase):

    def test_roundtrip(self):
        original = ensure_minimal_state(_make_state(
            conversations=[
                _make_conv("c_1", "hello", [
                    _make_msg("m_1", "user", "Alec", "<p>Hello</p>"),
                    _make_msg("m_2", "assistant", "Bot", "<p>Hi</p>",
                              time="2026-02-23T00:00:02Z"),
                ]),
            ],
            truth={"trust": [
                {"id": "t_1", "title": "Fact", "time": "2026-02-23T00:00:00Z",
                 "certainty": 0.9, "content": "<div>Truth</div>"}
            ]}
        ), strict=True)

        jsonl_text = state_to_jsonl(original)
        lines = jsonl_text.strip().split("\n")
        self.assertGreaterEqual(len(lines), 3)  # header + 1 conv + 1 trust

        # Parse header
        header = json.loads(lines[0])
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["version"], 2)

        # Roundtrip
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored, strict=True)
        self.assertEqual(len(restored["conversations"]), 1)
        self.assertEqual(len(restored["conversations"][0]["messages"]), 2)
        self.assertEqual(restored["conversations"][0]["id"], "c_1")
        self.assertEqual(len(restored["truth"]["trust"]), 1)

    def test_roundtrip_with_children(self):
        """Conversations with children survive JSONL roundtrip."""
        original = ensure_minimal_state(_make_state(
            conversations=[
                _make_conv("c_1", "root", [
                    _make_msg("m_1", "user", "Alec", "<p>Q</p>"),
                ], children=[
                    _make_conv("c_2", "child", [
                        _make_msg("m_2", "user", "Alec", "<p>Q2</p>"),
                    ]),
                ]),
            ],
            selected_conversation="c_2",
        ), strict=True)

        jsonl_text = state_to_jsonl(original)
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored, strict=True)

        self.assertEqual(len(restored["conversations"]), 1)
        root = restored["conversations"][0]
        self.assertEqual(root["id"], "c_1")
        self.assertEqual(len(root["children"]), 1)
        self.assertEqual(root["children"][0]["id"], "c_2")
        self.assertEqual(restored["selected_conversation"], "c_2")

    def test_hme_jsonl_roundtrip(self):
        """spec/hme.jsonl survives load → serialize → reload with all trust entries intact."""
        spec_path = Path(__file__).resolve().parent.parent / "spec" / "hme.jsonl"
        if not spec_path.exists():
            self.skipTest("spec/hme.jsonl not found")

        original = load_state_file(spec_path, strict=True)

        # Verify initial parse has expected trust entries
        trust = original.get("truth", {}).get("trust", [])
        self.assertGreaterEqual(len(trust), 10, "hme.jsonl should have ≥10 trust entries")
        ids_orig = {e["id"] for e in trust if "id" in e}
        self.assertIn("t_axiom_01", ids_orig)
        self.assertIn("t_false_01", ids_orig)
        self.assertIn("t_provider_claude", ids_orig)

        # Context should describe Kleene ternary logic
        self.assertIn("Kleene", original.get("context", ""))

        # Round-trip: serialize → parse → normalize
        jsonl_text = state_to_jsonl(original)
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored, strict=True)

        # Trust entries preserved
        trust_rt = restored.get("truth", {}).get("trust", [])
        ids_rt = {e["id"] for e in trust_rt if "id" in e}
        self.assertEqual(ids_orig, ids_rt, "Trust entry IDs must survive round-trip")

        # Certainty values preserved (including negative)
        by_id = {e["id"]: e for e in trust_rt}
        self.assertEqual(by_id["t_axiom_01"]["certainty"], 1.0)
        self.assertEqual(by_id["t_false_01"]["certainty"], -0.9)
        self.assertEqual(by_id["t_soft_01"]["certainty"], 0.8)

        # Context preserved
        self.assertIn("Kleene", restored.get("context", ""))

        # Write to disk and reload (full disk round-trip)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hme_roundtrip.jsonl"
            atomic_write_jsonl(path, original)
            reloaded = load_state_file(path, strict=True)
            trust_disk = reloaded.get("truth", {}).get("trust", [])
            ids_disk = {e["id"] for e in trust_disk if "id" in e}
            self.assertEqual(ids_orig, ids_disk, "Trust entries must survive disk round-trip")

    def test_legacy_json_detection(self):
        """load_state_file should handle legacy monolithic JSON (v1 format)."""
        state = {
            "version": 1,
            "schema": SCHEMA_URL_V1,
            "time": "2026-02-23T00:00:00Z",
            "context": "<div/>",
            "messages": [
                {"id": "m_1", "username": "Alec", "parent_id": None,
                 "time": "2026-02-23T00:00:01Z", "content": "<p>Hi</p>"}
            ],
            "truth": {"trust": []},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            f.flush()
            path = Path(f.name)
        try:
            loaded = load_state_file(path, strict=False)
            self.assertEqual(loaded["version"], 2)
            self.assertGreaterEqual(len(loaded["conversations"]), 1)
        finally:
            path.unlink()


class TestConversationTree(unittest.TestCase):

    def setUp(self):
        self.tree = [
            _make_conv("c_1", "root conv", [
                _make_msg("m_1", "user", "Alec", "<p>Q</p>"),
                _make_msg("m_2", "assistant", "Bot", "<p>A</p>"),
            ], children=[
                _make_conv("c_2", "branch A", [
                    _make_msg("m_3", "user", "Alec", "<p>Q2</p>"),
                    _make_msg("m_4", "assistant", "Bot", "<p>A2</p>"),
                ]),
                _make_conv("c_3", "branch B", [
                    _make_msg("m_5", "user", "Alec", "<p>Q3</p>"),
                ], children=[
                    _make_conv("c_4", "deep", [
                        _make_msg("m_6", "user", "Alec", "<p>Q4</p>"),
                    ]),
                ]),
            ]),
        ]

    def test_find_conversation_root(self):
        conv = find_conversation(self.tree, "c_1")
        self.assertIsNotNone(conv)
        self.assertEqual(conv["id"], "c_1")

    def test_find_conversation_nested(self):
        conv = find_conversation(self.tree, "c_4")
        self.assertIsNotNone(conv)
        self.assertEqual(conv["title"], "deep")

    def test_find_conversation_not_found(self):
        self.assertIsNone(find_conversation(self.tree, "c_nonexistent"))

    def test_get_ancestor_chain(self):
        chain = get_ancestor_chain(self.tree, "c_4")
        ids = [c["id"] for c in chain]
        self.assertEqual(ids, ["c_1", "c_3", "c_4"])

    def test_get_ancestor_chain_root(self):
        chain = get_ancestor_chain(self.tree, "c_1")
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["id"], "c_1")

    def test_get_ancestor_chain_not_found(self):
        chain = get_ancestor_chain(self.tree, "c_nonexistent")
        self.assertEqual(chain, [])

    def test_get_context_messages(self):
        msgs = get_context_messages(self.tree, "c_4")
        ids = [m["id"] for m in msgs]
        # Should include: c_1's messages (m_1, m_2) + c_3's (m_5) + c_4's (m_6)
        self.assertEqual(ids, ["m_1", "m_2", "m_5", "m_6"])

    def test_get_context_messages_root(self):
        msgs = get_context_messages(self.tree, "c_1")
        ids = [m["id"] for m in msgs]
        self.assertEqual(ids, ["m_1", "m_2"])

    def test_add_message_to_conversation(self):
        new_msg = {"id": "m_new", "role": "user", "username": "Alec",
                   "time": "2026-02-23T00:01:00Z", "content": "<p>New</p>"}
        result = add_message_to_conversation(self.tree, "c_2", new_msg)
        self.assertTrue(result)
        conv = find_conversation(self.tree, "c_2")
        self.assertEqual(len(conv["messages"]), 3)
        self.assertEqual(conv["messages"][-1]["id"], "m_new")

    def test_add_message_not_found(self):
        result = add_message_to_conversation(self.tree, "c_missing", {})
        self.assertFalse(result)

    def test_add_child_conversation(self):
        new_conv = {"id": "c_new", "title": "new branch", "messages": [
            {"id": "m_new", "role": "user", "username": "Alec",
             "time": "2026-02-23T00:01:00Z", "content": "<p>Branch</p>"}
        ]}
        result = add_child_conversation(self.tree, "c_2", new_conv)
        self.assertTrue(result)
        parent = find_conversation(self.tree, "c_2")
        self.assertEqual(len(parent["children"]), 1)
        self.assertEqual(parent["children"][0]["id"], "c_new")

    def test_remove_conversation(self):
        result = remove_conversation(self.tree, "c_3")
        self.assertTrue(result)
        # c_3 and c_4 should be gone
        self.assertIsNone(find_conversation(self.tree, "c_3"))
        self.assertIsNone(find_conversation(self.tree, "c_4"))
        # c_1 and c_2 still exist
        self.assertIsNotNone(find_conversation(self.tree, "c_1"))
        self.assertIsNotNone(find_conversation(self.tree, "c_2"))

    def test_all_conversation_ids(self):
        ids = all_conversation_ids(self.tree)
        self.assertEqual(ids, {"c_1", "c_2", "c_3", "c_4"})

    def test_all_message_ids(self):
        ids = all_message_ids(self.tree)
        self.assertEqual(ids, {"m_1", "m_2", "m_3", "m_4", "m_5", "m_6"})


class TestMerge(unittest.TestCase):

    def test_merge_new_conversations(self):
        base = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "existing", [
                _make_msg("m_1", "user", "Alec", "<p>Hello</p>"),
            ]),
        ]), strict=True)

        incoming = ensure_minimal_state(_make_state(
            date="2026-02-23T01:00:00Z",
            conversations=[
                _make_conv("c_2", "new conv", [
                    _make_msg("m_2", "user", "Alec", "<p>New</p>"),
                ]),
            ],
        ), strict=True)

        merged, meta = merge_llm_states(base, incoming, keep_base_context=True)
        self.assertEqual(len(merged["conversations"]), 2)
        self.assertEqual(meta["conversations_added"], 1)
        # Base context preserved
        self.assertEqual(merged["context"], "<div>Test</div>")

    def test_merge_deduplicates_by_id(self):
        base = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "existing", [
                _make_msg("m_1", "user", "Alec", "<p>Hello</p>"),
            ]),
        ]), strict=True)

        incoming = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "existing", [
                _make_msg("m_1", "user", "Alec", "<p>Hello</p>"),
            ]),
        ]), strict=True)

        merged, meta = merge_llm_states(base, incoming)
        self.assertEqual(len(merged["conversations"]), 1)
        self.assertEqual(meta["conversations_added"], 0)

    def test_merge_trust_entries(self):
        base = ensure_minimal_state(_make_state(truth={
            "trust": [{"id": "t_1", "title": "Fact A", "certainty": 0.8,
                       "time": "2026-02-23T00:00:00Z", "content": "<div>A</div>"}],
        }), strict=True)

        incoming = ensure_minimal_state(_make_state(truth={
            "trust": [{"id": "t_2", "title": "Fact B", "certainty": 0.6,
                       "time": "2026-02-23T00:01:00Z", "content": "<div>B</div>"}],
        }), strict=True)

        merged, meta = merge_llm_states(base, incoming)
        self.assertEqual(len(merged["truth"]["trust"]), 2)
        self.assertEqual(meta["trust_added"], 1)

    def test_merge_child_attached_to_parent(self):
        """Child conversation from incoming is attached to existing parent."""
        base = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "parent", [
                _make_msg("m_1", "user", "Alec", "<p>Root</p>"),
            ]),
        ]), strict=True)

        # Incoming has c_2 as child of c_1 (in JSONL, parent field)
        # We test via merge which uses _flatten_all_conversations
        incoming_state = _make_state(conversations=[
            _make_conv("c_1", "parent", [
                _make_msg("m_1", "user", "Alec", "<p>Root</p>"),
            ], children=[
                _make_conv("c_2", "child", [
                    _make_msg("m_2", "user", "Alec", "<p>Child</p>"),
                ]),
            ]),
        ])
        incoming = ensure_minimal_state(incoming_state, strict=True)

        merged, meta = merge_llm_states(base, incoming)
        # c_2 should be added as child of c_1
        c1 = find_conversation(merged["conversations"], "c_1")
        self.assertIsNotNone(c1)
        self.assertEqual(len(c1["children"]), 1)
        self.assertEqual(c1["children"][0]["id"], "c_2")


class TestContextDeltas(unittest.TestCase):

    def test_extracts_decision_keywords(self):
        convs = [
            _make_conv("c_1", "test", [
                _make_msg("m_1", "user", "Alec", "<p>We decided to use JSONL format.</p>"),
                _make_msg("m_2", "assistant", "Bot", "<p>The weather is nice.</p>"),
                _make_msg("m_3", "user", "Alec", "<p>The schema file must be versioned.</p>"),
            ]),
        ]
        deltas = extract_context_deltas(convs)
        self.assertEqual(len(deltas), 2)  # "decided" and "must"

    def test_build_context_draft_appends(self):
        base = "<div>Original context</div>"
        deltas = ["Alec: We decided X"]
        draft = build_context_draft(base, deltas)
        self.assertIn("Original context", draft)
        self.assertIn("Merged Session Deltas", draft)
        self.assertIn("We decided X", draft)

    def test_build_context_draft_noop_empty(self):
        base = "<div>Original</div>"
        result = build_context_draft(base, [])
        self.assertEqual(result, base)


class TestAtomicWriteJSONL(unittest.TestCase):

    def test_write_and_read_roundtrip(self):
        state = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "T", [
                _make_msg("m_1", "user", "U", "<p>X</p>"),
            ]),
        ]), strict=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            atomic_write_jsonl(path, state)
            self.assertTrue(path.exists())

            loaded = load_state_file(path, strict=True)
            self.assertEqual(len(loaded["conversations"]), 1)
            self.assertEqual(loaded["conversations"][0]["id"], "c_1")


class TestSymlinkRejection(unittest.TestCase):

    def test_rejects_symlink_on_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real = Path(tmpdir) / "real.jsonl"
            real.write_text('{"type":"header","version":2,"schema":"' + SCHEMA_URL + '","time":"2026-01-01T00:00:00Z","context":"<div/>"}')
            link = Path(tmpdir) / "link.jsonl"
            link.symlink_to(real)
            with self.assertRaises(StateValidationError):
                load_state_file(link, strict=True, reject_symlinks=True)


class TestProviderParsing(unittest.TestCase):

    PROVIDER_XHTML = (
        '<provider>'
        '<name>claude</name>'
        '<api_url>https://api.anthropic.com/v1/messages</api_url>'
        '<api_key>sk-test-key-123</api_key>'
        '<model>claude-sonnet-4-20250514</model>'
        '<timeout>60</timeout>'
        '<max_tokens>4096</max_tokens>'
        '</provider>'
    )

    def test_parse_provider_block(self):
        result = parse_provider_block(self.PROVIDER_XHTML)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "claude")
        self.assertEqual(result["api_url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(result["api_key"], "sk-test-key-123")
        self.assertEqual(result["model"], "claude-sonnet-4-20250514")
        self.assertEqual(result["timeout"], 60)
        self.assertEqual(result["max_tokens"], 4096)

    def test_parse_no_provider(self):
        result = parse_provider_block("<div><p>Just some text.</p></div>")
        self.assertIsNone(result)

    def test_parse_provider_in_mixed_xhtml(self):
        content = "<div><p>This is a provider entry.</p>" + self.PROVIDER_XHTML + "</div>"
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "claude")

    def test_resolve_api_key_raw(self):
        self.assertEqual(resolve_api_key("sk-raw-key"), "sk-raw-key")

    def test_resolve_api_key_empty(self):
        self.assertEqual(resolve_api_key(""), "")

    def test_resolve_api_key_rejects_outside_allowlist(self):
        with self.assertRaises(StateValidationError):
            resolve_api_key("file:///etc/passwd")

    def test_resolve_api_key_rejects_traversal(self):
        with self.assertRaises(StateValidationError):
            resolve_api_key("file://~/.wikioracle/keys/../../../etc/passwd")

    def test_get_provider_entries_sorted(self):
        entries = [
            {"id": "t_1", "title": "P1", "certainty": 0.8,
             "time": "2026-02-23T00:00:01Z",
             "content": "<provider><name>p1</name><api_url>http://a</api_url><api_key>k1</api_key></provider>"},
            {"id": "t_2", "title": "P2", "certainty": 0.9,
             "time": "2026-02-23T00:00:02Z",
             "content": "<provider><name>p2</name><api_url>http://b</api_url><api_key>k2</api_key></provider>"},
            {"id": "t_3", "title": "P3", "certainty": 0.9,
             "time": "2026-02-23T00:00:03Z",
             "content": "<provider><name>p3</name><api_url>http://c</api_url><api_key>k3</api_key></provider>"},
        ]
        result = get_provider_entries(entries)
        names = [cfg["name"] for _, cfg in result]
        self.assertEqual(names[0], "p3")
        self.assertEqual(names[1], "p2")
        self.assertEqual(names[2], "p1")

    def test_get_primary_provider(self):
        entries = [
            {"id": "t_1", "certainty": 0.5, "time": "2026-02-23T00:00:01Z",
             "content": "<provider><name>low</name><api_url>x</api_url><api_key>k</api_key></provider>"},
            {"id": "t_2", "certainty": 0.95, "time": "2026-02-23T00:00:01Z",
             "content": "<provider><name>high</name><api_url>y</api_url><api_key>k</api_key></provider>"},
        ]
        result = get_primary_provider(entries)
        self.assertIsNotNone(result)
        self.assertEqual(result[1]["name"], "high")

    def test_get_primary_provider_none(self):
        result = get_primary_provider([
            {"id": "t_1", "certainty": 0.5, "time": "2026-02-23T00:00:01Z",
             "content": "<div>Normal trust entry</div>"},
        ])
        self.assertIsNone(result)


class TestSrcParsing(unittest.TestCase):

    SRC_XHTML = (
        '<src>'
        '<name>project-readme</name>'
        '<path>file://~/.wikioracle/keys/readme.txt</path>'
        '<format>text</format>'
        '</src>'
    )

    def test_parse_src_block(self):
        result = parse_src_block(self.SRC_XHTML)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "project-readme")
        self.assertIn("readme.txt", result["path"])
        self.assertEqual(result["format"], "text")

    def test_parse_no_src(self):
        result = parse_src_block("<div><p>Just text.</p></div>")
        self.assertIsNone(result)

    def test_get_src_entries(self):
        entries = [
            {"id": "t_1", "certainty": 0.7, "time": "2026-02-23T00:00:01Z",
             "content": "<src><name>a</name><path>file://x</path></src>"},
            {"id": "t_2", "certainty": 0.5, "time": "2026-02-23T00:00:01Z",
             "content": "<div>Normal</div>"},
        ]
        result = get_src_entries(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["name"], "a")


class TestSelectedConversationRoundtrip(unittest.TestCase):

    def test_selected_conversation_persists(self):
        state = ensure_minimal_state(_make_state(
            selected_conversation="c_1",
            conversations=[
                _make_conv("c_1", "test", [
                    _make_msg("m_1", "user", "U", "<p>A</p>"),
                ]),
            ],
        ), strict=True)
        jsonl_text = state_to_jsonl(state)
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored, strict=True)
        self.assertEqual(restored["selected_conversation"], "c_1")


class TestOutputField(unittest.TestCase):
    """Test state.output persistence and defaults."""

    def test_output_preserved_in_ensure_minimal_state(self):
        """Non-empty output string survives normalization."""
        state = ensure_minimal_state({"output": "Custom format."})
        self.assertEqual(state["output"], "Custom format.")

    def test_output_defaults_when_whitespace(self):
        """Whitespace-only output gets the default."""
        state = ensure_minimal_state({"output": "  \n  "})
        self.assertEqual(state["output"], DEFAULT_OUTPUT)

    def test_output_defaults_when_missing(self):
        """Missing output gets the default."""
        state = ensure_minimal_state({})
        self.assertEqual(state["output"], DEFAULT_OUTPUT)

    def test_output_jsonl_roundtrip(self):
        """Output survives JSONL serialization round-trip."""
        state = ensure_minimal_state({"output": "Return JSON."})
        jsonl_text = state_to_jsonl(state)
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored)
        self.assertEqual(restored["output"], "Return JSON.")

    def test_default_output_roundtrip(self):
        """Default output persists through JSONL round-trip."""
        state = ensure_minimal_state({})
        jsonl_text = state_to_jsonl(state)
        restored = jsonl_to_state(jsonl_text)
        restored = ensure_minimal_state(restored)
        self.assertEqual(restored["output"], DEFAULT_OUTPUT)


if __name__ == "__main__":
    unittest.main()
