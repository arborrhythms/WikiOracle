"""Tests for XML config loading and serialization in bin/config.py."""

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure bin/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

from config import _load_config_xml, config_to_xml, _normalize_config


# =====================================================================
#  XML config loading
# =====================================================================


SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <user>
    <name>TestUser</name>
    <uid></uid>
  </user>
  <providers>
    <provider name="wikioracle">
      <display_name>wikiOracle</display_name>
      <username>test@example.com</username>
      <timeout>15</timeout>
    </provider>
    <provider name="openai">
      <display_name>chatGPT</display_name>
      <username>test@example.com</username>
      <url>https://api.openai.com/v1/chat/completions</url>
      <api_key></api_key>
      <default_model>gpt-4o</default_model>
    </provider>
  </providers>
  <chat>
    <temperature>0.7</temperature>
    <rag>true</rag>
    <url_fetch>false</url_fetch>
    <confirm_actions>true</confirm_actions>
  </chat>
  <ui>
    <default_provider>wikioracle</default_provider>
    <layout>horizontal</layout>
    <theme>system</theme>
    <splitter_pct>0</splitter_pct>
    <swipe_nav_horizontal>true</swipe_nav_horizontal>
    <swipe_nav_vertical>false</swipe_nav_vertical>
  </ui>
  <server>
    <stateless>false</stateless>
    <url_prefix></url_prefix>
    <online_training>
      <enabled>false</enabled>
      <truth_corpus_path>data/truth.xml</truth_corpus_path>
      <alpha_base>0.01</alpha_base>
      <alpha_min>0.001</alpha_min>
      <alpha_max>0.1</alpha_max>
      <merge_rate>0.1</merge_rate>
      <device>cpu</device>
      <dissonance_enabled>true</dissonance_enabled>
      <operators_dynamic_enabled>true</operators_dynamic_enabled>
    </online_training>
    <allowed_urls>
      <url>https://api.openai.com/</url>
      <url>https://api.anthropic.com/</url>
    </allowed_urls>
  </server>
</config>
"""


class TestLoadConfigXml(unittest.TestCase):
    """Test XML config file loading."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-8"
        )
        self.tmp.write(SAMPLE_XML)
        self.tmp.close()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp_path.unlink(missing_ok=True)

    def test_loads_user(self):
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(data["user"]["name"], "TestUser")
        self.assertEqual(data["user"]["uid"], "")

    def test_loads_providers(self):
        data = _load_config_xml(self.tmp_path)
        self.assertIn("wikioracle", data["providers"])
        self.assertIn("openai", data["providers"])

    def test_provider_display_name_mapped(self):
        """display_name in XML maps to 'name' key in the dict."""
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(data["providers"]["wikioracle"]["name"], "wikiOracle")
        self.assertEqual(data["providers"]["openai"]["name"], "chatGPT")

    def test_provider_timeout_is_int(self):
        data = _load_config_xml(self.tmp_path)
        self.assertIsInstance(data["providers"]["wikioracle"]["timeout"], int)
        self.assertEqual(data["providers"]["wikioracle"]["timeout"], 15)

    def test_chat_booleans(self):
        data = _load_config_xml(self.tmp_path)
        self.assertIs(data["chat"]["rag"], True)
        self.assertIs(data["chat"]["url_fetch"], False)
        self.assertIs(data["chat"]["confirm_actions"], True)

    def test_chat_temperature_is_float(self):
        data = _load_config_xml(self.tmp_path)
        self.assertIsInstance(data["chat"]["temperature"], float)
        self.assertAlmostEqual(data["chat"]["temperature"], 0.7)

    def test_ui_section(self):
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(data["ui"]["default_provider"], "wikioracle")
        self.assertEqual(data["ui"]["layout"], "horizontal")
        self.assertIs(data["ui"]["swipe_nav_horizontal"], True)
        self.assertIs(data["ui"]["swipe_nav_vertical"], False)

    def test_server_stateless(self):
        data = _load_config_xml(self.tmp_path)
        self.assertIs(data["server"]["stateless"], False)

    def test_online_training(self):
        data = _load_config_xml(self.tmp_path)
        ot = data["server"]["online_training"]
        self.assertIs(ot["enabled"], False)
        self.assertEqual(ot["device"], "cpu")
        self.assertAlmostEqual(ot["alpha_base"], 0.01)

    def test_allowed_urls(self):
        data = _load_config_xml(self.tmp_path)
        urls = data["server"]["allowed_urls"]
        self.assertIsInstance(urls, list)
        self.assertEqual(len(urls), 2)
        self.assertIn("https://api.openai.com/", urls)


# =====================================================================
#  XML config serialization
# =====================================================================


class TestConfigToXml(unittest.TestCase):
    """Test config dict to XML serialization."""

    def _make_minimal_config(self):
        return {
            "user": {"name": "Alice", "uid": ""},
            "providers": {
                "wikioracle": {
                    "name": "wikiOracle",
                    "username": "alice@example.com",
                    "timeout": 15,
                },
            },
            "chat": {"temperature": 0.7, "rag": True, "url_fetch": False, "confirm_actions": True},
            "ui": {
                "default_provider": "wikioracle",
                "layout": "horizontal",
                "theme": "system",
                "splitter_pct": 0,
                "swipe_nav_horizontal": True,
                "swipe_nav_vertical": False,
            },
            "server": {
                "stateless": False,
                "url_prefix": "",
                "online_training": {
                    "enabled": False,
                    "truth_corpus_path": "data/truth.xml",
                    "alpha_base": 0.01,
                    "alpha_min": 0.001,
                    "alpha_max": 0.1,
                    "merge_rate": 0.1,
                    "device": "cpu",
                    "dissonance_enabled": True,
                    "operators_dynamic_enabled": True,
                },
                "allowed_urls": ["https://api.openai.com/"],
            },
        }

    def test_produces_valid_xml(self):
        """config_to_xml should produce parseable XML."""
        import xml.etree.ElementTree as ET

        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<?xml", xml_str)
        # Should parse without error
        ET.fromstring(xml_str.split("\n", 1)[1] if xml_str.startswith("<?xml") else xml_str)

    def test_contains_user_name(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<name>Alice</name>", xml_str)

    def test_contains_display_name(self):
        """The 'name' dict key should map to <display_name> in XML."""
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<display_name>wikiOracle</display_name>", xml_str)

    def test_contains_provider_attr(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn('name="wikioracle"', xml_str)

    def test_roundtrip(self):
        """Load XML → serialize to XML → reload should preserve key values."""
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)

        # Write to temp file and reload
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-8"
        )
        tmp.write(xml_str)
        tmp.close()
        try:
            reloaded = _load_config_xml(Path(tmp.name))
            self.assertEqual(reloaded["user"]["name"], "Alice")
            self.assertEqual(reloaded["providers"]["wikioracle"]["name"], "wikiOracle")
            self.assertIs(reloaded["chat"]["rag"], True)
            self.assertAlmostEqual(reloaded["chat"]["temperature"], 0.7)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
