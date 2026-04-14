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

from state import (
    SCHEMA_URL,
    STATE_VERSION,
    add_child_conversation,
    add_message_to_conversation,
    all_conversation_ids,
    all_message_ids,
    atomic_write_xml,
    build_context_draft,
    ensure_minimal_state,
    extract_context_deltas,
    find_conversation,
    get_ancestor_chain,
    get_context_messages,
    load_state_file,
    merge_llm_states,
    remove_conversation,
    state_to_xml,
    xml_to_state,
)
from truth import (
    ALLOWED_DATA_DIR,
    StateValidationError,
    get_primary_provider,
    get_provider_entries,
    parse_provider_block,
    resolve_api_key,
    utc_now_iso,
)


_HME_XML_PATH = Path(__file__).resolve().parent / "hme.xml"


def _make_state(**overrides):
    """Create a minimal valid v2 state dict with optional overrides."""
    base = {
        "version": 2,
        "schema": SCHEMA_URL,
        "time_creation": "2026-02-23T00:00:00Z",
        "time_lastModified": "2026-02-23T00:00:00Z",
        "conversations": [],
        "selected_conversation": None,
        "truth": [],
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
        self.assertNotIn("context", state)  # context now in config.providers
        self.assertEqual(state["conversations"], [])
        self.assertIn("truth", state)
        self.assertIsNone(state["selected_conversation"])
        self.assertIsNone(state["selected_message"])

    def test_strict_rejects_bad_schema(self):
        with self.assertRaises(StateValidationError):
            ensure_minimal_state({"version": 2, "schema": "bad", "time_creation": "2026-01-01T00:00:00Z",
                                  "conversations": [], "truth": []}, strict=True)

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

    def test_trust_value_clamped(self):
        state = ensure_minimal_state(_make_state(truth=[
            {"title": "X", "trust": 5.0, "content": "test", "time": "2026-01-01T00:00:00Z"},
        ]), strict=True)
        self.assertEqual(state["truth"][0]["trust"], 1.0)

    def test_strict_rejects_non_path_conversation_selection(self):
        root = _make_conv("c_root", "root", [_make_msg("m_1", "user", "Alec", "<p>Q</p>")], children=[
            _make_conv("c_a", "A", [_make_msg("m_2", "assistant", "Bot", "<p>A</p>")]),
            _make_conv("c_b", "B", [_make_msg("m_3", "assistant", "Bot", "<p>B</p>")]),
        ])
        root["children"][0]["selected"] = True
        root["children"][1]["selected"] = True
        with self.assertRaises(StateValidationError):
            ensure_minimal_state(_make_state(conversations=[root]), strict=True)

    def test_strict_rejects_multiple_selected_messages(self):
        root = _make_conv("c_root", "root", [
            _make_msg("m_1", "user", "Alec", "<p>Q</p>"),
            _make_msg("m_2", "assistant", "Bot", "<p>A</p>"),
        ])
        root["messages"][0]["selected"] = True
        root["messages"][1]["selected"] = True
        with self.assertRaises(StateValidationError):
            ensure_minimal_state(_make_state(conversations=[root]), strict=True)


class TestXMLRoundTrip(unittest.TestCase):

    def test_roundtrip(self):
        original = ensure_minimal_state(_make_state(
            conversations=[
                _make_conv("c_1", "hello", [
                    _make_msg("m_1", "user", "Alec", "<p>Hello</p>"),
                    _make_msg("m_2", "assistant", "Bot", "<p>Hi</p>",
                              time="2026-02-23T00:00:02Z"),
                ]),
            ],
            truth=[
                {"id": "t_1", "title": "Fact", "time": "2026-02-23T00:00:00Z",
                 "trust": 0.9, "content": "<div>Truth</div>"}
            ]
        ), strict=True)

        xml_text = state_to_xml(original)

        # Roundtrip
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored, strict=True)
        self.assertEqual(len(restored["conversations"]), 1)
        self.assertEqual(len(restored["conversations"][0]["messages"]), 2)
        self.assertEqual(restored["conversations"][0]["id"], "c_1")
        self.assertEqual(len(restored["truth"]), 1)

    def test_roundtrip_with_children(self):
        """Conversations with children survive XML roundtrip."""
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

        xml_text = state_to_xml(original)
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored, strict=True)

        self.assertEqual(len(restored["conversations"]), 1)
        root = restored["conversations"][0]
        self.assertEqual(root["id"], "c_1")
        self.assertEqual(len(root["children"]), 1)
        self.assertEqual(root["children"][0]["id"], "c_2")
        self.assertEqual(restored["selected_conversation"], "c_2")

    @unittest.skipIf(not _HME_XML_PATH.exists(), "test/hme.xml not found")
    def test_hme_xml_roundtrip(self):
        """test/hme.xml survives load -> serialize -> reload with all trust entries intact."""
        original = load_state_file(_HME_XML_PATH, strict=True)

        # Verify initial parse has expected trust entries
        trust = original.get("truth", [])
        self.assertGreaterEqual(len(trust), 10, "hme.xml should have >=10 trust entries")
        ids_orig = {e["id"] for e in trust if "id" in e}
        self.assertIn("axiom_01", ids_orig)
        self.assertIn("false_01", ids_orig)
        self.assertIn("provider_claude", ids_orig)

        # Context was moved to config.providers — old files may still have it in state

        # Round-trip: serialize -> parse -> normalize
        xml_text = state_to_xml(original)
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored, strict=True)

        # Trust entries preserved
        trust_rt = restored.get("truth", [])
        ids_rt = {e["id"] for e in trust_rt if "id" in e}
        self.assertEqual(ids_orig, ids_rt, "Trust entry IDs must survive round-trip")

        # Trust values preserved (including negative)
        by_id = {e["id"]: e for e in trust_rt}
        self.assertEqual(by_id["axiom_01"]["trust"], 1.0)
        self.assertEqual(by_id["false_01"]["trust"], -0.9)
        self.assertEqual(by_id["soft_01"]["trust"], 0.8)

        # Context was moved to config.providers — skip context check

        # Write to disk and reload (full disk round-trip)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hme_roundtrip.xml"
            atomic_write_xml(path, original)
            reloaded = load_state_file(path, strict=True)
            trust_disk = reloaded.get("truth", [])
            ids_disk = {e["id"] for e in trust_disk if "id" in e}
            self.assertEqual(ids_orig, ids_disk, "Trust entries must survive disk round-trip")

    def test_legacy_json_detection(self):
        """load_state_file should handle legacy monolithic JSON gracefully."""
        state = {
            "version": 1,
            "schema": SCHEMA_URL,
            "time": "2026-02-23T00:00:00Z",
            "conversations": [],
            "truth": [],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(state, f)
            f.flush()
            path = Path(f.name)
        try:
            loaded = load_state_file(path, strict=False)
            self.assertEqual(loaded["version"], 2)
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

    def test_add_message_to_empty_placeholder_conversation_updates_title(self):
        empty = _make_conv("c_empty", "", [], [])
        tree = [empty]
        new_msg = {
            "id": "m_new",
            "role": "user",
            "username": "Alec",
            "time": "2026-02-23T00:01:00Z",
            "content": "<p>Fresh branch title</p>",
        }
        result = add_message_to_conversation(tree, "c_empty", new_msg)
        self.assertTrue(result)
        conv = find_conversation(tree, "c_empty")
        self.assertEqual(conv["title"], "Fresh branch title")
        self.assertEqual(len(conv["messages"]), 1)

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
        base = ensure_minimal_state(_make_state(truth=[
            {"id": "t_1", "title": "Fact A", "trust": 0.8,
             "time": "2026-02-23T00:00:00Z", "content": "<div>A</div>"},
        ]), strict=True)

        incoming = ensure_minimal_state(_make_state(truth=[
            {"id": "t_2", "title": "Fact B", "trust": 0.6,
             "time": "2026-02-23T00:01:00Z", "content": "<div>B</div>"},
        ]), strict=True)

        merged, meta = merge_llm_states(base, incoming)
        self.assertEqual(len(merged["truth"]), 2)
        self.assertEqual(meta["trust_added"], 1)

    def test_merge_child_attached_to_parent(self):
        """Child conversation from incoming is attached to existing parent."""
        base = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "parent", [
                _make_msg("m_1", "user", "Alec", "<p>Root</p>"),
            ]),
        ]), strict=True)

        # Incoming has c_2 as child of c_1
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


class TestAtomicWriteXML(unittest.TestCase):

    def test_write_and_read_roundtrip(self):
        state = ensure_minimal_state(_make_state(conversations=[
            _make_conv("c_1", "T", [
                _make_msg("m_1", "user", "U", "<p>X</p>"),
            ]),
        ]), strict=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.xml"
            atomic_write_xml(path, state)
            self.assertTrue(path.exists())

            loaded = load_state_file(path, strict=True)
            self.assertEqual(len(loaded["conversations"]), 1)
            self.assertEqual(loaded["conversations"][0]["id"], "c_1")


class TestSymlinkRejection(unittest.TestCase):

    def test_rejects_symlink_on_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real = Path(tmpdir) / "real.xml"
            real.write_text('<?xml version="1.0" ?><state version="2" schema="' + SCHEMA_URL + '" time="2026-01-01T00:00:00Z"><context><div /></context></state>')
            link = Path(tmpdir) / "link.xml"
            link.symlink_to(real)
            with self.assertRaises(StateValidationError):
                load_state_file(link, strict=True, reject_symlinks=True)


class TestProviderParsing(unittest.TestCase):

    PROVIDER_XHTML = (
        '<provider>'
        '<name>claude</name>'
        '<api_url>https://api.anthropic.com/v1/messages</api_url>'
        '<api_key>sk-test-key-123</api_key>'
        '<model>claude-sonnet-4-6</model>'
        '<timeout>60</timeout>'
        '<max_tokens>4096</max_tokens>'
        '</provider>'
    )

    def test_parse_provider_block(self):
        result = parse_provider_block(self.PROVIDER_XHTML)
        self.assertIsNotNone(result)
        self.assertEqual(result["api_url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(result["api_key"], "sk-test-key-123")
        self.assertEqual(result["model"], "claude-sonnet-4-6")
        self.assertEqual(result["timeout"], 60)
        self.assertEqual(result["max_tokens"], 4096)

    def test_parse_no_provider(self):
        result = parse_provider_block("<div><p>Just some text.</p></div>")
        self.assertIsNone(result)

    def test_parse_provider_in_mixed_xhtml(self):
        content = "<div><p>This is a provider entry.</p>" + self.PROVIDER_XHTML + "</div>"
        result = parse_provider_block(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["api_url"], "https://api.anthropic.com/v1/messages")

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
            {"id": "t_1", "title": "P1", "trust": 0.8,
             "time": "2026-02-23T00:00:01Z",
             "content": "<provider><api_url>http://a</api_url><api_key>k1</api_key></provider>"},
            {"id": "t_2", "title": "P2", "trust": 0.9,
             "time": "2026-02-23T00:00:02Z",
             "content": "<provider><api_url>http://b</api_url><api_key>k2</api_key></provider>"},
            {"id": "t_3", "title": "P3", "trust": 0.9,
             "time": "2026-02-23T00:00:03Z",
             "content": "<provider><api_url>http://c</api_url><api_key>k3</api_key></provider>"},
        ]
        result = get_provider_entries(entries)
        titles = [e["title"] for e, _ in result]
        self.assertEqual(titles[0], "P3")
        self.assertEqual(titles[1], "P2")
        self.assertEqual(titles[2], "P1")

    def test_get_primary_provider(self):
        entries = [
            {"id": "t_1", "title": "low", "trust": 0.5, "time": "2026-02-23T00:00:01Z",
             "content": "<provider><api_url>x</api_url><api_key>k</api_key></provider>"},
            {"id": "t_2", "title": "high", "trust": 0.95, "time": "2026-02-23T00:00:01Z",
             "content": "<provider><api_url>y</api_url><api_key>k</api_key></provider>"},
        ]
        result = get_primary_provider(entries)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["title"], "high")

    def test_get_primary_provider_none(self):
        result = get_primary_provider([
            {"id": "t_1", "trust": 0.5, "time": "2026-02-23T00:00:01Z",
             "content": "<div>Normal trust entry</div>"},
        ])
        self.assertIsNone(result)


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
        xml_text = state_to_xml(state)
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored, strict=True)
        self.assertEqual(restored["selected_conversation"], "c_1")
        self.assertTrue(restored["conversations"][0].get("selected"))

    def test_selected_message_persists(self):
        state = ensure_minimal_state(_make_state(
            selected_conversation="c_1",
            selected_message="m_2",
            conversations=[
                _make_conv("c_1", "test", [
                    _make_msg("m_1", "user", "U", "<p>A</p>"),
                    _make_msg("m_2", "assistant", "Bot", "<p>B</p>"),
                ]),
            ],
        ), strict=True)
        xml_text = state_to_xml(state)
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored, strict=True)
        self.assertEqual(restored["selected_conversation"], "c_1")
        self.assertEqual(restored["selected_message"], "m_2")
        self.assertTrue(restored["conversations"][0]["messages"][1].get("selected"))


class TestTitleField(unittest.TestCase):
    """Test state.title persistence and defaults."""

    def test_title_preserved(self):
        """Non-empty title survives normalization."""
        state = ensure_minimal_state({"title": "My Doc"})
        self.assertEqual(state["title"], "My Doc")

    def test_title_default(self):
        """Missing title gets the default."""
        state = ensure_minimal_state({})
        self.assertEqual(state["title"], "WikiOracle")

    def test_title_xml_roundtrip(self):
        """Title survives XML serialization round-trip."""
        state = ensure_minimal_state({"title": "Research Notes"})
        xml_text = state_to_xml(state)
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored)
        self.assertEqual(restored["title"], "Research Notes")


if __name__ == "__main__":
    unittest.main()
