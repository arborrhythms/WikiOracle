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
  <server>
    <server_id>test-server-id-1234</server_id>
    <stateless>false</stateless>
    <url_prefix></url_prefix>
    <truthset>
      <truth_symmetry>true</truth_symmetry>
      <store_concrete>false</store_concrete>
      <truth_weight>0.7</truth_weight>
    </truthset>
    <evaluation>
      <temperature>0.7</temperature>
      <max_tokens>128</max_tokens>
      <timeout>120</timeout>
      <url_fetch>false</url_fetch>
    </evaluation>
    <training>
      <enabled>false</enabled>
      <truth_corpus_path>data/truth.xml</truth_corpus_path>
      <alpha_base>0.01</alpha_base>
      <alpha_min>0.001</alpha_min>
      <alpha_max>0.1</alpha_max>
      <merge_rate>0.1</merge_rate>
      <device>cpu</device>
      <dissonance_enabled>true</dissonance_enabled>
      <operators_dynamic_enabled>true</operators_dynamic_enabled>
    </training>
    <allowed_urls>
      <url>https://api.openai.com/</url>
      <url>https://api.anthropic.com/</url>
    </allowed_urls>
  </server>
  <providers>
    <default>wikioracle</default>
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

    def test_loads_server_id(self):
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(data["server"]["server_id"], "test-server-id-1234")

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

    def test_evaluation_settings(self):
        data = _load_config_xml(self.tmp_path)
        ev = data["server"]["evaluation"]
        self.assertIs(ev["url_fetch"], False)
        self.assertAlmostEqual(ev["temperature"], 0.7)
        self.assertEqual(ev["max_tokens"], 128)

    def test_truthset_settings(self):
        data = _load_config_xml(self.tmp_path)
        ts = data["server"]["truthset"]
        self.assertIs(ts["truth_symmetry"], True)
        self.assertIs(ts["store_concrete"], False)
        self.assertAlmostEqual(ts["truth_weight"], 0.7)

    def test_providers_default(self):
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(data["providers"]["default"], "wikioracle")

    def test_server_stateless(self):
        data = _load_config_xml(self.tmp_path)
        self.assertIs(data["server"]["stateless"], False)

    def test_training(self):
        data = _load_config_xml(self.tmp_path)
        tr = data["server"]["training"]
        self.assertIs(tr["enabled"], False)
        self.assertEqual(tr["device"], "cpu")
        self.assertAlmostEqual(tr["alpha_base"], 0.01)

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
            "server": {
                "server_id": "test-server-id-5678",
                "stateless": False,
                "url_prefix": "",
                "truthset": {
                    "truth_symmetry": True,
                    "store_concrete": False,
                    "truth_weight": 0.7,
                },
                "evaluation": {
                    "temperature": 0.7,
                    "max_tokens": 128,
                    "timeout": 120,
                    "url_fetch": False,
                },
                "training": {
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
            "providers": {
                "default": "wikioracle",
                "wikioracle": {
                    "name": "wikiOracle",
                    "username": "alice@example.com",
                    "timeout": 15,
                },
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

    def test_contains_server_id(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<server_id>test-server-id-5678</server_id>", xml_str)

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
            self.assertEqual(reloaded["server"]["server_id"], "test-server-id-5678")
            self.assertEqual(reloaded["providers"]["wikioracle"]["name"], "wikiOracle")
            self.assertEqual(reloaded["providers"]["default"], "wikioracle")
            self.assertAlmostEqual(reloaded["server"]["evaluation"]["temperature"], 0.7)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
