"""Tests for XML config loading and serialization in bin/config.py."""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure bin/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import config as config_mod
from config import (
    _build_providers,
    _client_safe_config,
    _load_config_xml,
    config_to_xml,
)


# =====================================================================
#  XML config loading
# =====================================================================


# Canonical format: <server>/<client> sections with nested <providers>.
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
    <providers>
      <context>Return strictly valid XHTML.</context>
      <output>Use &lt;conversation&gt; for the answer.</output>
      <provider>
        <name>WikiOracle</name>
        <type>wikioracle</type>
        <username>test@example.com</username>
        <timeout>15</timeout>
      </provider>
      <provider>
        <name>chatGPT</name>
        <type>openai</type>
        <username>test@example.com</username>
        <url>https://api.openai.com/v1/chat/completions</url>
        <model>gpt-4o</model>
      </provider>
    </providers>
  </server>
  <client>
    <temperature>0.7</temperature>
    <url_fetch>false</url_fetch>
    <thought_free>false</thought_free>
    <ui>
      <layout>horizontal</layout>
      <theme>light</theme>
    </ui>
    <providers>
      <default_provider>WikiOracle</default_provider>
      <default_model>NanoChat</default_model>
      <provider>
        <name>chatGPT</name>
        <api_key>sk-test-1234</api_key>
      </provider>
    </providers>
  </client>
</config>
"""


class TestLoadConfigXml(unittest.TestCase):
    """Test XML config file loading into the canonical shape."""

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

    def test_loads_providers_by_name(self):
        data = _load_config_xml(self.tmp_path)
        provs = data["server"]["providers"]
        self.assertIn("WikiOracle", provs)
        self.assertIn("chatGPT", provs)

    def test_provider_has_type(self):
        data = _load_config_xml(self.tmp_path)
        provs = data["server"]["providers"]
        self.assertEqual(provs["WikiOracle"]["type"], "wikioracle")
        self.assertEqual(provs["chatGPT"]["type"], "openai")

    def test_provider_has_model(self):
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(
            data["server"]["providers"]["chatGPT"]["model"], "gpt-4o"
        )

    def test_provider_timeout_is_int(self):
        data = _load_config_xml(self.tmp_path)
        wo = data["server"]["providers"]["WikiOracle"]
        self.assertIsInstance(wo["timeout"], int)
        self.assertEqual(wo["timeout"], 15)

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

    def test_client_default_provider_and_model(self):
        data = _load_config_xml(self.tmp_path)
        cprovs = data["client"]["providers"]
        self.assertEqual(cprovs["default_provider"], "WikiOracle")
        self.assertEqual(cprovs["default_model"], "NanoChat")

    def test_client_api_key_loaded(self):
        data = _load_config_xml(self.tmp_path)
        self.assertEqual(
            data["client"]["providers"]["chatGPT"]["api_key"], "sk-test-1234"
        )

    def test_server_provider_section_keys_loaded(self):
        data = _load_config_xml(self.tmp_path)
        provs = data["server"]["providers"]
        self.assertEqual(provs["context"], "Return strictly valid XHTML.")
        self.assertIn("conversation", provs["output"])

    def test_client_temperature_loaded(self):
        data = _load_config_xml(self.tmp_path)
        self.assertAlmostEqual(data["client"]["temperature"], 0.7)

    def test_client_ui_loaded(self):
        data = _load_config_xml(self.tmp_path)
        ui = data["client"]["ui"]
        self.assertEqual(ui["layout"], "horizontal")
        self.assertEqual(ui["theme"], "light")

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
                "providers": {
                    "WikiOracle": {
                        "type": "wikioracle",
                        "username": "alice@example.com",
                        "timeout": 15,
                    },
                },
            },
            "client": {
                "temperature": 0.7,
                "url_fetch": False,
                "thought_free": False,
                "ui": {"layout": "horizontal", "theme": "light"},
                "providers": {
                    "default_provider": "WikiOracle",
                    "default_model": "NanoChat",
                    "WikiOracle": {"api_key": "sk-test-key"},
                },
            },
        }

    def test_produces_valid_xml(self):
        """config_to_xml should produce parseable XML."""
        import xml.etree.ElementTree as ET

        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<?xml", xml_str)
        ET.fromstring(
            xml_str.split("\n", 1)[1] if xml_str.startswith("<?xml") else xml_str
        )

    def test_contains_server_id(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<server_id>test-server-id-5678</server_id>", xml_str)

    def test_no_name_attribute_on_provider(self):
        """New format uses child elements, no attributes."""
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        # No `name="..."` attributes anywhere in the providers section
        srv_provs = xml_str.split("<server>")[1].split("</server>")[0]
        self.assertNotIn('name="', srv_provs)

    def test_provider_has_name_element(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<name>WikiOracle</name>", xml_str)

    def test_provider_has_type_element(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<type>wikioracle</type>", xml_str)

    def test_default_provider_in_client(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        self.assertIn("<default_provider>WikiOracle</default_provider>", xml_str)
        self.assertIn("<default_model>NanoChat</default_model>", xml_str)

    def test_api_key_in_client_section(self):
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)
        # Client API keys should appear in the <client> section, not <server>
        client_section = xml_str.split("<client>")[1].split("</client>")[0]
        self.assertIn("<api_key>sk-test-key</api_key>", client_section)
        server_section = xml_str.split("<server>")[1].split("</server>")[0]
        self.assertNotIn("sk-test-key", server_section)

    def test_roundtrip(self):
        """Load XML → serialize to XML → reload should preserve key values."""
        data = self._make_minimal_config()
        xml_str = config_to_xml(data)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-8"
        )
        tmp.write(xml_str)
        tmp.close()
        try:
            reloaded = _load_config_xml(Path(tmp.name))
            self.assertEqual(
                reloaded["server"]["server_id"], "test-server-id-5678"
            )
            self.assertIn("WikiOracle", reloaded["server"]["providers"])
            self.assertEqual(
                reloaded["server"]["providers"]["WikiOracle"]["type"], "wikioracle"
            )
            self.assertEqual(
                reloaded["client"]["providers"]["default_provider"], "WikiOracle"
            )
            self.assertEqual(
                reloaded["client"]["providers"]["default_model"], "NanoChat"
            )
            self.assertEqual(
                reloaded["client"]["providers"]["WikiOracle"]["api_key"],
                "sk-test-key",
            )
            self.assertAlmostEqual(
                reloaded["server"]["evaluation"]["temperature"], 0.7
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)


# =====================================================================
#  Provider registry construction + client-safe projection
# =====================================================================


class TestBuildProviders(unittest.TestCase):
    """Test provider registry construction from canonical config."""

    def setUp(self):
        self._orig_config = copy.deepcopy(config_mod.TheConfig.data)

    def tearDown(self):
        config_mod.TheConfig.replace(self._orig_config)

    def test_config_model_overrides_builtin_default(self):
        config_mod.TheConfig.replace({
            "server": {
                "providers": {
                    "OpenAI": {
                        "type": "openai",
                        "model": "gpt-4.1-mini",
                    },
                },
            },
            "client": {"providers": {}},
        })
        with patch.dict(os.environ, {}, clear=True):
            providers = _build_providers()
        self.assertEqual(providers["OpenAI"]["model"], "gpt-4.1-mini")

    def test_client_api_key_overlays_provider_definition(self):
        config_mod.TheConfig.replace({
            "server": {
                "providers": {
                    "OpenAI": {
                        "type": "openai",
                        "model": "gpt-4o",
                    },
                },
            },
            "client": {
                "providers": {
                    "OpenAI": {"api_key": "sk-from-client"},
                },
            },
        })
        providers = _build_providers()
        self.assertEqual(providers["OpenAI"]["api_key"], "sk-from-client")

    def test_section_keys_skipped(self):
        config_mod.TheConfig.replace({
            "server": {
                "providers": {
                    "context": "shared XHTML context",
                    "output": "output instructions",
                    "OpenAI": {"type": "openai", "model": "gpt-4o"},
                },
            },
            "client": {"providers": {}},
        })
        providers = _build_providers()
        self.assertIn("OpenAI", providers)
        self.assertNotIn("context", providers)
        self.assertNotIn("output", providers)

    def test_providers_keyed_by_name(self):
        providers = _build_providers()
        self.assertIn("OpenAI", providers)
        self.assertIn("WikiOracle", providers)
        self.assertNotIn("openai", providers)

    def test_provider_has_type(self):
        providers = _build_providers()
        self.assertEqual(providers["OpenAI"]["type"], "openai")
        self.assertEqual(providers["WikiOracle"]["type"], "wikioracle")


class TestClientSafeConfig(unittest.TestCase):
    """Test the client-facing projection of canonical config."""

    def test_strips_dropbox_secrets(self):
        cfg = {
            "server": {
                "server_id": "x",
                "dropbox": {"app_key": "k", "app_secret": "s"},
                "providers": {},
            },
            "client": {},
        }
        safe = _client_safe_config(cfg)
        self.assertNotIn("dropbox", safe["server"])

    def test_strips_provider_api_keys_from_server_providers(self):
        cfg = {
            "server": {
                "providers": {
                    "OpenAI": {
                        "type": "openai",
                        "api_key": "sk-secret",
                    },
                },
            },
            "client": {},
        }
        safe = _client_safe_config(cfg)
        self.assertNotIn("api_key", safe["server"]["providers"]["OpenAI"])

    def test_augments_provider_with_models_list(self):
        cfg = {
            "server": {
                "providers": {
                    "OpenAI": {"type": "openai"},
                },
            },
            "client": {},
        }
        safe = _client_safe_config(cfg)
        openai = safe["server"]["providers"]["OpenAI"]
        self.assertEqual(openai["name"], "OpenAI")
        self.assertIn("models", openai)
        self.assertIsInstance(openai["models"], list)

    def test_preserves_section_keys(self):
        cfg = {
            "server": {
                "providers": {
                    "context": "shared context",
                    "output": "output instructions",
                    "OpenAI": {"type": "openai"},
                },
            },
            "client": {},
        }
        safe = _client_safe_config(cfg)
        self.assertEqual(
            safe["server"]["providers"]["context"], "shared context"
        )
        self.assertEqual(
            safe["server"]["providers"]["output"], "output instructions"
        )

    def test_preserves_client_section(self):
        cfg = {
            "server": {"providers": {}},
            "client": {
                "temperature": 0.7,
                "providers": {
                    "default_provider": "OpenAI",
                    "OpenAI": {"api_key": "sk-client"},
                },
            },
        }
        safe = _client_safe_config(cfg)
        self.assertAlmostEqual(safe["client"]["temperature"], 0.7)
        self.assertEqual(
            safe["client"]["providers"]["default_provider"], "OpenAI"
        )
        # Client-owned api_keys are NOT stripped (the client owns them)
        self.assertEqual(
            safe["client"]["providers"]["OpenAI"]["api_key"], "sk-client"
        )


if __name__ == "__main__":
    unittest.main()
