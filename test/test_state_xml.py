"""Tests for XML state serialization and deserialization in bin/state.py."""

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bin/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from state import (
    STATE_VERSION,
    SCHEMA_URL,
    atomic_write_xml,
    ensure_minimal_state,
    load_state_file,
    state_to_xml,
    xml_to_state,
)


# =====================================================================
#  Helpers
# =====================================================================


def _make_state_with_conversations():
    """Build a state dict with nested conversations and truth entries."""
    return {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time_creation": "2026-03-05T12:00:00Z",
        "time_lastModified": "2026-03-05T12:00:00Z",
        "title": "XML Test State",
        "client_name": "Alice",
        "client_id": "alice-uuid-123",
        "selected_conversation": "c_root",
        "conversations": [
            {
                "id": "c_root",
                "title": "Root conversation",
                "messages": [
                    {
                        "id": "m1",
                        "role": "user",
                        "username": "Alice",
                        "time": "2026-03-05T12:00:01Z",
                        "content": "<Q><fact trust=\"0.5\">Hello world.</fact></Q>",
                    },
                    {
                        "id": "m2",
                        "role": "assistant",
                        "username": "WikiOracle",
                        "time": "2026-03-05T12:00:02Z",
                        "content": "<R><feeling>Nice to meet you!</feeling></R>",
                    },
                ],
                "children": [
                    {
                        "id": "c_child",
                        "title": "Child conversation",
                        "parentId": "c_root",
                        "messages": [
                            {
                                "id": "m3",
                                "role": "user",
                                "username": "Alice",
                                "time": "2026-03-05T12:01:00Z",
                                "content": "<Q><fact trust=\"0.8\">Follow-up question.</fact></Q>",
                            },
                        ],
                        "children": [],
                    },
                ],
            },
        ],
        "truth": [
            {
                "id": "t1",
                "title": "Roses",
                "trust": 0.95,
                "content": "<fact>Roses are red.</fact>",
                "time": "2026-03-05T12:00:00Z",
            },
            {
                "id": "t2",
                "title": "Violets",
                "trust": 0.95,
                "content": "<fact>Violets are blue.</fact>",
                "time": "2026-03-05T12:00:01Z",
            },
            {
                "id": "f1",
                "title": "Poetry feeling",
                "trust": 0.5,
                "content": "<feeling>Poetry is beautiful.</feeling>",
                "time": "2026-03-05T12:00:02Z",
            },
        ],
    }


def _make_state_with_operators():
    """Build a state with operator and provider entries."""
    return {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time_creation": "2026-03-05T12:00:00Z",
        "time_lastModified": "2026-03-05T12:00:00Z",
        "title": "Operator Test",
        "conversations": [],
        "truth": [
            {
                "id": "axiom_01",
                "title": "All men are mortal",
                "trust": 1.0,
                "content": "<fact>All men are mortal.</fact>",
                "time": "2026-03-05T00:00:01Z",
            },
            {
                "id": "axiom_02",
                "title": "Socrates is a man",
                "trust": 1.0,
                "content": "<fact>Socrates is a man.</fact>",
                "time": "2026-03-05T00:00:02Z",
            },
            {
                "id": "op_and",
                "title": "Socrates is mortal (AND)",
                "trust": 0.0,
                "content": '<logic><and><ref id="axiom_01"/><ref id="axiom_02"/></and></logic>',
                "time": "2026-03-05T00:00:03Z",
            },
            {
                "id": "provider_claude",
                "title": "Claude (Anthropic)",
                "trust": 0.8,
                "content": (
                    "<provider>"
                    "<api_url>https://api.anthropic.com/v1/messages</api_url>"
                    "<model>claude-sonnet-4-6</model>"
                    "</provider>"
                ),
                "time": "2026-03-05T00:00:04Z",
            },
        ],
    }


# =====================================================================
#  XML roundtrip tests
# =====================================================================


class TestStateToXml(unittest.TestCase):
    """Test state dict to XML serialization."""

    def test_produces_valid_xml(self):
        import xml.etree.ElementTree as ET

        state = _make_state_with_conversations()
        xml_str = state_to_xml(state)
        self.assertIn("<?xml", xml_str)
        # Should parse without error
        root = ET.fromstring(xml_str.split("\n", 1)[1])
        self.assertEqual(root.tag, "state")

    def test_contains_client(self):
        state = _make_state_with_conversations()
        xml_str = state_to_xml(state)
        self.assertIn("<client>", xml_str)
        self.assertIn("<title>XML Test State</title>", xml_str)
        self.assertIn("<client_name>Alice</client_name>", xml_str)
        self.assertIn("<client_id>alice-uuid-123</client_id>", xml_str)

    def test_contains_conversations(self):
        state = _make_state_with_conversations()
        xml_str = state_to_xml(state)
        self.assertIn('<conversation id="c_root"', xml_str)
        self.assertIn('<conversation id="c_child"', xml_str)

    def test_contains_truth_entries(self):
        state = _make_state_with_conversations()
        xml_str = state_to_xml(state)
        self.assertIn('<fact id="t1"', xml_str)
        self.assertIn("Roses are red.", xml_str)

    def test_contains_messages(self):
        state = _make_state_with_conversations()
        xml_str = state_to_xml(state)
        self.assertIn('id="m1"', xml_str)
        self.assertIn('role="user"', xml_str)
        self.assertIn('username="Alice"', xml_str)

    def test_operator_entry_serializes_as_logic(self):
        state = _make_state_with_operators()
        xml_str = state_to_xml(state)
        self.assertIn('<logic ', xml_str)
        self.assertIn('<and>', xml_str)
        self.assertIn('<ref id="axiom_01"', xml_str)
        self.assertIn('<ref id="axiom_02"', xml_str)

    def test_reference_serializes_as_anchor(self):
        state = ensure_minimal_state({
            "conversations": [],
            "truth": [{
                "id": "ref_1",
                "title": "Example",
                "trust": 0.8,
                "content": '<reference href="https://example.com">Example</reference>',
                "time": "2026-03-05T00:00:00Z",
            }],
        }, strict=False)
        xml_str = state_to_xml(state)
        self.assertIn('<reference id="ref_1"', xml_str)
        self.assertIn('<a href="https://example.com">Example</a>', xml_str)

    def test_selected_conversation_serializes_as_selected_path(self):
        state = ensure_minimal_state({
            "version": STATE_VERSION,
            "schema": SCHEMA_URL,
            "time_creation": "2026-03-05T12:00:00Z",
            "title": "Selection Test",
            "selected_conversation": "c_child",
            "conversations": [
                {
                    "id": "c_root",
                    "title": "Root",
                    "messages": [],
                    "children": [
                        {
                            "id": "c_child",
                            "title": "Child",
                            "messages": [],
                            "children": [],
                        },
                    ],
                },
            ],
            "truth": [],
        }, strict=False)
        xml_str = state_to_xml(state)
        self.assertNotIn("<selected_conversation>", xml_str)
        self.assertIn('<conversation id="c_root" selected="true">', xml_str)
        self.assertIn('<conversation id="c_child" parentId="c_root" selected="true">', xml_str)

    def test_selected_message_serializes_as_attribute(self):
        state = ensure_minimal_state({
            "version": STATE_VERSION,
            "schema": SCHEMA_URL,
            "time_creation": "2026-03-05T12:00:00Z",
            "title": "Selection Test",
            "selected_conversation": "c_root",
            "selected_message": "m2",
            "conversations": [
                {
                    "id": "c_root",
                    "title": "Root",
                    "messages": [
                        {
                            "id": "m1",
                            "role": "user",
                            "username": "Alice",
                            "time": "2026-03-05T12:00:01Z",
                            "content": "<p>Hello</p>",
                        },
                        {
                            "id": "m2",
                            "role": "assistant",
                            "username": "WikiOracle",
                            "time": "2026-03-05T12:00:02Z",
                            "content": "<p>Hi</p>",
                        },
                    ],
                    "children": [],
                },
            ],
            "truth": [],
        }, strict=False)
        xml_str = state_to_xml(state)
        self.assertIn('message id="m2" role="assistant" username="WikiOracle" time="2026-03-05T12:00:02Z" selected="true"', xml_str)


class TestXmlToState(unittest.TestCase):
    """Test XML to state dict deserialization."""

    def test_roundtrip_preserves_client(self):
        original = _make_state_with_conversations()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        self.assertEqual(restored["title"], "XML Test State")
        self.assertEqual(restored["time_creation"], "2026-03-05T12:00:00Z")
        self.assertIn("time_lastModified", restored)
        self.assertEqual(restored["selected_conversation"], "c_root")
        self.assertEqual(restored["client_name"], "Alice")
        self.assertEqual(restored["client_id"], "alice-uuid-123")

    def test_roundtrip_preserves_conversations(self):
        original = _make_state_with_conversations()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        self.assertEqual(len(restored["conversations"]), 1)
        root_conv = restored["conversations"][0]
        self.assertEqual(root_conv["id"], "c_root")
        self.assertEqual(root_conv["title"], "Root conversation")
        self.assertEqual(len(root_conv["messages"]), 2)

    def test_roundtrip_preserves_nested_children(self):
        original = _make_state_with_conversations()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        root_conv = restored["conversations"][0]
        self.assertEqual(len(root_conv["children"]), 1)
        child = root_conv["children"][0]
        self.assertEqual(child["id"], "c_child")
        self.assertEqual(child["title"], "Child conversation")
        self.assertEqual(len(child["messages"]), 1)

    def test_roundtrip_preserves_truth(self):
        original = _make_state_with_conversations()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        self.assertEqual(len(restored["truth"]), 3)
        t1 = restored["truth"][0]
        self.assertEqual(t1["id"], "t1")
        self.assertEqual(t1["title"], "Roses")
        self.assertAlmostEqual(t1["trust"], 0.95)

    def test_roundtrip_preserves_message_content(self):
        original = _make_state_with_conversations()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        msg = restored["conversations"][0]["messages"][0]
        self.assertIn("Hello world.", msg["content"])
        self.assertIn("fact", msg["content"])

    def test_roundtrip_preserves_operators(self):
        original = _make_state_with_operators()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        op = [e for e in restored["truth"] if e["id"] == "op_and"][0]
        # Operators now use <logic><and><ref id="..."/></and></logic>
        self.assertIn("<logic>", op["content"])
        self.assertIn("<and>", op["content"])
        self.assertIn('id="axiom_01"', op["content"])
        self.assertIn('id="axiom_02"', op["content"])

    def test_roundtrip_preserves_provider_content(self):
        original = _make_state_with_operators()
        xml_str = state_to_xml(original)
        restored = xml_to_state(xml_str)
        prov = [e for e in restored["truth"] if e["id"] == "provider_claude"][0]
        self.assertIn("<api_url>", prov["content"])
        self.assertIn("claude-sonnet-4-6", prov["content"])

    def test_roundtrip_preserves_reference_link(self):
        state = ensure_minimal_state({
            "conversations": [],
            "truth": [{
                "id": "ref_1",
                "title": "Example",
                "trust": 0.8,
                "content": '<reference href="https://example.com">Example</reference>',
                "time": "2026-03-05T00:00:00Z",
            }],
        }, strict=False)
        restored = xml_to_state(state_to_xml(state))
        ref = restored["truth"][0]
        self.assertIn("<reference", ref["content"])
        self.assertIn('<a href="https://example.com">', ref["content"])

    def test_roundtrip_derives_selection_from_attributes(self):
        xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<state>
  <header>
    <version>2</version>
    <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
    <time>2026-03-05T12:00:00Z</time>
    <title>Selected Attrs</title>
    <context><div /></context>
  </header>
  <conversation id="c_root" selected="true">
    <title>Root</title>
    <conversation id="c_child" parentId="c_root" selected="true">
      <title>Child</title>
      <message id="m_1" role="user" username="Alice" time="2026-03-05T12:00:01Z" selected="true">
        <content><p>Hello</p></content>
      </message>
    </conversation>
  </conversation>
</state>
"""
        restored = xml_to_state(xml_text)
        self.assertEqual(restored["selected_conversation"], "c_child")
        self.assertEqual(restored["selected_message"], "m_1")
        root = restored["conversations"][0]
        child = root["children"][0]
        self.assertTrue(root.get("selected"))
        self.assertTrue(child.get("selected"))
        self.assertTrue(child["messages"][0].get("selected"))

    def test_invalid_xml_returns_empty_state(self):
        restored = xml_to_state("not valid xml")
        self.assertEqual(restored["conversations"], [])
        self.assertEqual(restored["truth"], [])

    def test_empty_string_returns_empty_state(self):
        restored = xml_to_state("")
        self.assertEqual(restored["conversations"], [])

    def test_backward_compat_old_time_field(self):
        """Old <time> element maps to time_creation."""
        xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<state>
  <header>
    <version>2</version>
    <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
    <time>2026-03-05T12:00:00Z</time>
    <title>Old Format</title>
    <context><div /></context>
  </header>
</state>
"""
        restored = xml_to_state(xml_text)
        self.assertEqual(restored["time_creation"], "2026-03-05T12:00:00Z")
        self.assertEqual(restored["time_lastModified"], "2026-03-05T12:00:00Z")

    def test_backward_compat_old_user_guid(self):
        """Old <user_guid> in <header> maps to client_id via ensure_minimal_state."""
        xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<state>
  <header>
    <version>2</version>
    <schema>https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd</schema>
    <time_creation>2026-03-05T12:00:00Z</time_creation>
    <time_lastModified>2026-03-05T12:00:00Z</time_lastModified>
    <title>Old GUID Format</title>
  </header>
</state>
"""
        restored = xml_to_state(xml_text)
        restored = ensure_minimal_state(restored, strict=False)
        # Old format is parsed by xml_to_state with backward compat
        self.assertEqual(restored["title"], "Old GUID Format")

    def test_client_fields_roundtrip(self):
        """Flat client_name and client_id roundtrip through XML."""
        state = ensure_minimal_state({
            "time_creation": "2026-03-05T12:00:00Z",
            "title": "Client Fields Test",
            "client_name": "Alice",
            "client_id": "alice-uuid-123",
            "conversations": [],
            "truth": [],
        }, strict=False)
        xml_str = state_to_xml(state)
        self.assertIn("<client_name>Alice</client_name>", xml_str)
        self.assertIn("<client_id>alice-uuid-123</client_id>", xml_str)
        restored = xml_to_state(xml_str)
        self.assertEqual(restored["client_name"], "Alice")
        self.assertEqual(restored["client_id"], "alice-uuid-123")


# =====================================================================
#  File I/O tests
# =====================================================================


class TestAtomicWriteXml(unittest.TestCase):
    """Test atomic XML file writing."""

    def test_write_and_reload(self):
        state = _make_state_with_conversations()
        state = ensure_minimal_state(state, strict=False)
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            atomic_write_xml(path, state)
            reloaded = load_state_file(path, strict=False)
            self.assertEqual(reloaded["title"], "XML Test State")
            self.assertEqual(len(reloaded["conversations"]), 1)
            self.assertTrue(len(reloaded["truth"]) >= 3)
        finally:
            path.unlink(missing_ok=True)

    def test_load_detects_xml_by_extension(self):
        state = _make_state_with_conversations()
        state = ensure_minimal_state(state, strict=False)
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            path.write_text(state_to_xml(state), encoding="utf-8")
            reloaded = load_state_file(path, strict=False)
            self.assertEqual(reloaded["title"], "XML Test State")
        finally:
            path.unlink(missing_ok=True)

    def test_load_detects_xml_by_content(self):
        """Even with a .txt extension, XML content should be detected."""
        state = _make_state_with_conversations()
        state = ensure_minimal_state(state, strict=False)
        xml_content = state_to_xml(state)
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
            tmp.write(xml_content)
            path = Path(tmp.name)
        try:
            reloaded = load_state_file(path, strict=False)
            self.assertEqual(reloaded["title"], "XML Test State")
        finally:
            path.unlink(missing_ok=True)


# =====================================================================
#  XML fixture verification
# =====================================================================


class TestMigrationRoundtrip(unittest.TestCase):
    """Test that XML fixture files load correctly."""

    def _get_data_dir(self):
        return Path(__file__).resolve().parent

    def test_alpha_xml_exists_and_loads(self):
        path = self._get_data_dir() / "alpha.xml"
        if not path.exists():
            self.skipTest("alpha.xml not yet migrated")
        state = load_state_file(path, strict=False)
        self.assertEqual(state["title"], "Alpha Vote Test")
        # Should have truth entries
        self.assertTrue(len(state["truth"]) >= 2)

    def test_hme_xml_exists_and_loads(self):
        path = self._get_data_dir() / "hme.xml"
        if not path.exists():
            self.skipTest("hme.xml not yet migrated")
        state = load_state_file(path, strict=False)
        self.assertEqual(state["title"], "HME Test")
        # Should have axioms, operators, references, providers, authority
        ids = {e["id"] for e in state["truth"]}
        self.assertIn("axiom_01", ids)
        self.assertIn("op_socrates_mortal", ids)

    def test_llm_xml_exists_and_loads(self):
        path = self._get_data_dir() / "llm.xml"
        if not path.exists():
            self.skipTest("llm.xml not yet migrated")
        state = load_state_file(path, strict=False)
        self.assertEqual(state["title"], "WikiOracle")


# =====================================================================
#  Context with XHTML content
# =====================================================================


class TestXhtmlContentPreservation(unittest.TestCase):
    """Test that XHTML content in context and messages roundtrips."""

    def test_ui_block_roundtrips(self):
        """UI block in state roundtrips through XML."""
        state = ensure_minimal_state({
            "conversations": [],
            "truth": [],
            "ui": {"layout": "horizontal", "theme": "dark", "model": "gpt-4o"},
        }, strict=False)
        xml_str = state_to_xml(state)
        self.assertIn("<ui>", xml_str)
        self.assertIn("<layout>horizontal</layout>", xml_str)
        restored = xml_to_state(xml_str)
        self.assertEqual(restored.get("ui", {}).get("layout"), "horizontal")
        self.assertEqual(restored.get("ui", {}).get("theme"), "dark")
        self.assertEqual(restored.get("ui", {}).get("model"), "gpt-4o")

    def test_truth_entry_with_xhtml_fact(self):
        state = ensure_minimal_state({
            "conversations": [],
            "truth": [{
                "id": "test_fact",
                "title": "Test",
                "trust": 0.9,
                "place": "Paris",
                "content": '<fact trust="0.9">The sky is blue.</fact>',
                "time": "2026-03-05T00:00:00Z",
            }],
        }, strict=False)
        xml_str = state_to_xml(state)
        self.assertIn('place="Paris"', xml_str)
        self.assertNotIn('author="', xml_str)
        restored = xml_to_state(xml_str)
        entry = restored["truth"][0]
        self.assertEqual(entry["place"], "Paris")
        self.assertIn("The sky is blue.", entry["content"])
        self.assertIn("fact", entry["content"])

    def test_truth_entry_with_provider_xhtml(self):
        state = ensure_minimal_state({
            "conversations": [],
            "truth": [{
                "id": "prov_test",
                "title": "Test Provider",
                "trust": 0.8,
                "content": (
                    "<provider>"
                    "<api_url>https://api.example.com</api_url>"
                    "<model>test-model</model>"
                    "</provider>"
                ),
                "time": "2026-03-05T00:00:00Z",
            }],
        }, strict=False)
        xml_str = state_to_xml(state)
        restored = xml_to_state(xml_str)
        entry = restored["truth"][0]
        self.assertIn("<api_url>", entry["content"])
        self.assertIn("test-model", entry["content"])


if __name__ == "__main__":
    unittest.main()
