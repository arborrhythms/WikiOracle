#!/usr/bin/env python3
"""Integration tests that verify end-to-end chat with online LLM providers.

These tests make REAL network calls to OpenAI and Anthropic APIs using
the API keys in config.xml.  They are slow (~5-20s each) and require
valid credentials.  Failures are treated as warnings in `make test`
(non-blocking).  Tests without matching API keys are skipped automatically.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))
_RUN_SLOW = os.getenv("RUN_SLOW") == "1"

import config as config_mod
from config import Config, _load_config
from wikioracle import create_app
from state import SCHEMA_URL, STATE_VERSION, ensure_minimal_state, atomic_write_xml


def _make_state(**overrides):
    base = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time": "2026-02-28T00:00:00Z",
        "context": "<div>You are a helpful assistant.</div>",
        "conversations": [],
        "selected_conversation": None,
        "truth": [],
    }
    base.update(overrides)
    return base


def _has_provider_key(provider: str) -> bool:
    """Check if config.xml has an API key for the given provider."""
    cfg = _load_config()
    if not cfg:
        return False
    return bool(cfg.get("providers", {}).get(provider, {}).get("api_key"))


def _provider_skip_reason(provider: str) -> str | None:
    if not _RUN_SLOW:
        return "online provider test — set RUN_SLOW=1"
    if not _has_provider_key(provider):
        return f"No {provider.capitalize()} API key in config.xml"
    return None


_OPENAI_SKIP = _provider_skip_reason("openai")
_ANTHROPIC_SKIP = _provider_skip_reason("anthropic")


class _CsrfClient:
    """Thin wrapper that injects X-Requested-With CSRF header on POSTs."""

    _CSRF = {"X-Requested-With": "WikiOracle"}

    def __init__(self, client):
        self._c = client

    def __getattr__(self, name):
        return getattr(self._c, name)

    def post(self, *args, headers=None, **kwargs):
        headers = {**(headers or {}), **self._CSRF}
        return self._c.post(*args, headers=headers, **kwargs)


class _OnlineLLMBase(unittest.TestCase):
    """Base that creates a Flask test client with real config.xml providers."""

    STATELESS = False

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = self.STATELESS
        config_mod.DEBUG_MODE = False

        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "state.xml"
        initial = ensure_minimal_state({}, strict=False)
        atomic_write_xml(self._state_path, initial, reject_symlinks=False)

        self.cfg = Config(state_file=self._state_path)
        self.app = create_app(self.cfg, url_prefix="")
        self.app.testing = True
        self.client = _CsrfClient(self.app.test_client())

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
# Stateful mode tests (server reads config.xml from disk)
# ---------------------------------------------------------------------------
class TestStatefulOpenAI(_OnlineLLMBase):
    STATELESS = False

    @unittest.skipIf(_OPENAI_SKIP is not None, _OPENAI_SKIP or "")
    def test_chat_openai(self):
        """Stateful: send a message via OpenAI and get a real response."""
        resp = self.client.post("/chat", json={
            "message": "Reply with exactly: ONLINE_TEST_OK",
            "config": {"provider": "openai"},
        })
        self._assert_chat_ok(resp)


class TestStatefulAnthropic(_OnlineLLMBase):
    STATELESS = False

    @unittest.skipIf(_ANTHROPIC_SKIP is not None, _ANTHROPIC_SKIP or "")
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

    @unittest.skipIf(_OPENAI_SKIP is not None, _OPENAI_SKIP or "")
    def test_chat_openai_stateless(self):
        """Stateless: send a message via OpenAI with client-supplied state."""
        runtime_config = _load_config() or {}
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

    @unittest.skipIf(_ANTHROPIC_SKIP is not None, _ANTHROPIC_SKIP or "")
    def test_chat_anthropic_stateless(self):
        """Stateless: send a message via Anthropic with client-supplied state."""
        runtime_config = _load_config() or {}
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
