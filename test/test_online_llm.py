#!/usr/bin/env python3
"""Integration tests that verify end-to-end chat with online LLM providers.

These tests make REAL network calls to OpenAI and Anthropic APIs using
the API keys in config.yaml.  They are slow (~5-20s each) and require
valid credentials, so they are NOT included in the default `make test`
target.  Run explicitly:

    python3 -m unittest test.test_online_llm -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

import config as config_mod
from config import Config, _load_config_yaml
from wikioracle import create_app
from state import SCHEMA_URL, STATE_VERSION, ensure_minimal_state, atomic_write_jsonl


def _make_state(**overrides):
    base = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time": "2026-02-28T00:00:00Z",
        "context": "<div>You are a helpful assistant.</div>",
        "conversations": [],
        "selected_conversation": None,
        "truth": {"trust": []},
    }
    base.update(overrides)
    return base


def _has_provider_key(provider: str) -> bool:
    """Check if config.yaml has an API key for the given provider."""
    cfg = _load_config_yaml()
    if not cfg:
        return False
    return bool(cfg.get("providers", {}).get(provider, {}).get("api_key"))


class _OnlineLLMBase(unittest.TestCase):
    """Base that creates a Flask test client with real config.yaml providers."""

    STATELESS = False

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = self.STATELESS
        config_mod.DEBUG_MODE = False

        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "llm.jsonl"
        initial = ensure_minimal_state({}, strict=False)
        atomic_write_jsonl(self._state_path, initial, reject_symlinks=False)

        self.cfg = Config(state_file=self._state_path)
        self.app = create_app(self.cfg, url_prefix="")
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        config_mod.STATELESS_MODE = self._orig_stateless
        config_mod.DEBUG_MODE = self._orig_debug
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _assert_chat_ok(self, resp):
        """Assert a chat response succeeded and contains expected fields."""
        self.assertEqual(resp.status_code, 200,
                         f"Expected 200, got {resp.status_code}: {resp.get_data(as_text=True)[:300]}")
        data = resp.get_json()
        self.assertTrue(data.get("ok"), f"ok=False: {data.get('error')}")
        self.assertIn("text", data)
        self.assertIsInstance(data["text"], str)
        self.assertGreater(len(data["text"]), 0, "Empty response text")
        self.assertIn("state", data)
        convs = data["state"].get("conversations", [])
        self.assertGreater(len(convs), 0, "No conversation created")
        return data


# ---------------------------------------------------------------------------
# Stateful mode tests (server reads config.yaml from disk)
# ---------------------------------------------------------------------------
class TestStatefulOpenAI(_OnlineLLMBase):
    STATELESS = False

    @unittest.skipUnless(_has_provider_key("openai"), "No OpenAI API key in config.yaml")
    def test_chat_openai(self):
        """Stateful: send a message via OpenAI and get a real response."""
        resp = self.client.post("/chat", json={
            "message": "Reply with exactly: ONLINE_TEST_OK",
            "config": {"provider": "openai"},
        })
        self._assert_chat_ok(resp)


class TestStatefulAnthropic(_OnlineLLMBase):
    STATELESS = False

    @unittest.skipUnless(_has_provider_key("anthropic"), "No Anthropic API key in config.yaml")
    def test_chat_anthropic(self):
        """Stateful: send a message via Anthropic and get a real response."""
        resp = self.client.post("/chat", json={
            "message": "Reply with exactly: ONLINE_TEST_OK",
            "config": {"provider": "anthropic"},
        })
        self._assert_chat_ok(resp)


# ---------------------------------------------------------------------------
# Stateless mode tests (client supplies state + runtime_config)
# ---------------------------------------------------------------------------
class TestStatelessOpenAI(_OnlineLLMBase):
    STATELESS = True

    @unittest.skipUnless(_has_provider_key("openai"), "No OpenAI API key in config.yaml")
    def test_chat_openai_stateless(self):
        """Stateless: send a message via OpenAI with client-supplied state."""
        runtime_config = _load_config_yaml() or {}
        resp = self.client.post("/chat", json={
            "message": "Reply with exactly: ONLINE_TEST_OK",
            "state": _make_state(),
            "runtime_config": runtime_config,
            "config": {"provider": "openai"},
        })
        data = self._assert_chat_ok(resp)
        # Verify state file was NOT written (stateless contract)
        state_content = self._state_path.read_text()
        self.assertNotIn("ONLINE_TEST_OK", state_content,
                         "Response leaked into state file in stateless mode")


class TestStatelessAnthropic(_OnlineLLMBase):
    STATELESS = True

    @unittest.skipUnless(_has_provider_key("anthropic"), "No Anthropic API key in config.yaml")
    def test_chat_anthropic_stateless(self):
        """Stateless: send a message via Anthropic with client-supplied state."""
        runtime_config = _load_config_yaml() or {}
        resp = self.client.post("/chat", json={
            "message": "Reply with exactly: ONLINE_TEST_OK",
            "state": _make_state(),
            "runtime_config": runtime_config,
            "config": {"provider": "anthropic"},
        })
        data = self._assert_chat_ok(resp)
        state_content = self._state_path.read_text()
        self.assertNotIn("ONLINE_TEST_OK", state_content,
                         "Response leaked into state file in stateless mode")


if __name__ == "__main__":
    unittest.main()
