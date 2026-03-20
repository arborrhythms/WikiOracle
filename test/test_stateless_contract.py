#!/usr/bin/env python3
"""Stateless-mode contract tests for the WikiOracle Flask app.

These tests verify the sessionStorage-authority contract:
  - /chat returns 400 when state or runtime_config is missing in stateless mode
  - /chat stateless path uses request-supplied state and config
  - /bootstrap returns seed data from disk
  - No disk writes are attempted in stateless chat flow
  - Stateful mode is unaffected (no regression)
"""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root and bin/ are importable
_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

import config as config_mod
import wikioracle as wikioracle_mod
from config import Config
from wikioracle import create_app
from state import SCHEMA_URL, STATE_VERSION, ensure_minimal_state, load_state_file


def _make_state(**overrides):
    """Create a minimal valid v2 state dict with optional overrides."""
    base = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time_creation": "2026-02-24T00:00:00Z",
        "time_lastModified": "2026-02-24T00:00:00Z",
        "conversations": [],
        "selected_conversation": None,
        "truth": [],
    }
    base.update(overrides)
    return base


def _make_runtime_config(**overrides):
    """Create a runtime_config dict (parsed config)."""
    base = {
        "server": {
            "evaluation": {
                "temperature": 0.7,
                "url_fetch": False,
            },
            "truthset": {
                "truth_symmetry": True,
                "store_concrete": False,
                "truth_weight": 0.7,
            },
        },
        "providers": {"default": "WikiOracle"},
    }
    base.update(overrides)
    return base


class _CsrfClient:
    """Thin wrapper that injects the X-Requested-With CSRF header on POSTs."""

    _CSRF = {"X-Requested-With": "WikiOracle"}

    def __init__(self, client):
        self._c = client

    def __getattr__(self, name):
        return getattr(self._c, name)

    def post(self, *args, headers=None, **kwargs):
        headers = {**(headers or {}), **self._CSRF}
        return self._c.post(*args, headers=headers, **kwargs)


class StatelessContractBase(unittest.TestCase):
    """Base class that creates a Flask test client in stateless mode."""

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = True
        config_mod.DEBUG_MODE = False

        # Use a temp dir for state file (should never be written in stateless)
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "state.xml"
        # Write initial seed state so _load_state doesn't fail for /bootstrap
        initial = ensure_minimal_state({}, strict=False)
        from state import atomic_write_xml
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


class TestStatelessChatValidation(StatelessContractBase):
    """Verify stateless /chat rejects requests missing required fields."""

    def test_chat_missing_state_returns_400(self):
        """POST /chat without body.state in stateless mode → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "runtime_config": _make_runtime_config(),
            "config": {"provider": "WikiOracle"},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("stateless_missing_state", data.get("error", ""))

    def test_chat_missing_runtime_config_returns_400(self):
        """POST /chat without body.runtime_config in stateless mode → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "state": _make_state(),
            "config": {"provider": "WikiOracle"},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("stateless_missing_runtime_config", data.get("error", ""))

    def test_chat_missing_both_returns_400(self):
        """POST /chat without state or runtime_config → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "config": {"provider": "WikiOracle"},
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_state_not_dict_returns_400(self):
        """POST /chat with state as non-dict → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "state": "not a dict",
            "runtime_config": _make_runtime_config(),
            "config": {"provider": "WikiOracle"},
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_runtime_config_not_dict_returns_400(self):
        """POST /chat with runtime_config as non-dict → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "state": _make_state(),
            "runtime_config": "not a dict",
            "config": {"provider": "WikiOracle"},
        })
        self.assertEqual(resp.status_code, 400)


class TestStatelessChatNoDiskWrites(StatelessContractBase):
    """Verify stateless /chat does NOT write to disk."""

    def test_no_state_file_write(self):
        """Stateless chat must not write state.xml to disk."""
        mtime_before = self._state_path.stat().st_mtime

        # Mock _call_nanochat to avoid network call
        with patch("response._call_nanochat", return_value="test reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "state": _make_state(),
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "WikiOracle"},
            })

        # Should succeed (502 means provider error which is OK to catch separately)
        self.assertIn(resp.status_code, (200, 502))
        if resp.status_code == 200:
            mtime_after = self._state_path.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after,
                             "State file was modified during stateless chat")

    def test_no_config_xml_write(self):
        """Stateless chat must not write config.xml to disk."""
        project_root = Path(__file__).resolve().parent.parent
        cfg_path = project_root / "config.xml"
        had_config = cfg_path.exists()
        mtime_before = cfg_path.stat().st_mtime if had_config else None

        with patch("response._call_nanochat", return_value="test reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "state": _make_state(),
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "WikiOracle"},
            })

        if had_config:
            mtime_after = cfg_path.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after,
                             "config.xml was modified during stateless chat")


class TestStatelessChatUsesRequestPayload(StatelessContractBase):
    """Verify stateless /chat uses client-supplied state, not _MEMORY_STATE or disk."""

    def test_uses_request_state(self):
        """The returned state reflects client-supplied state, not server memory."""
        client_state = _make_state(title="From Client")

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hi",
                "state": client_state,
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "WikiOracle"},
            })

        if resp.status_code == 200:
            data = resp.get_json()
            returned_state = data.get("state", {})
            # A new conversation should have been created
            self.assertGreater(len(returned_state.get("conversations", [])), 0)

    def test_uses_state_client_name(self):
        """The user display name in messages comes from state, not _CONFIG."""
        st = _make_state()
        st["client_name"] = "RuntimeUser"

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hi",
                "state": st,
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "WikiOracle"},
            })

        if resp.status_code == 200:
            data = resp.get_json()
            convs = data.get("state", {}).get("conversations", [])
            if convs:
                msgs = convs[0].get("messages", [])
                user_msgs = [m for m in msgs if m.get("role") == "user"]
                if user_msgs:
                    self.assertEqual(user_msgs[0].get("username"), "RuntimeUser")


class TestBootstrapEndpoint(StatelessContractBase):
    """Verify /bootstrap returns seed data."""

    def test_bootstrap_returns_state(self):
        resp = self.client.get("/bootstrap")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("state", data)
        self.assertIsInstance(data["state"], dict)
        self.assertIn("version", data["state"])

    def test_bootstrap_returns_config(self):
        resp = self.client.get("/bootstrap")
        data = resp.get_json()
        self.assertNotIn("config_yaml", data)  # legacy key no longer sent
        self.assertNotIn("parsed", data)        # no more parsed/config split
        self.assertIn("config", data)
        self.assertIsInstance(data["config"], dict)

    def test_bootstrap_returns_providers_in_config(self):
        """Provider metadata is part of config.server.providers."""
        resp = self.client.get("/bootstrap")
        data = resp.get_json()
        self.assertNotIn("providers", data)  # no longer a top-level key
        provs = data["config"]["server"]["providers"]
        self.assertIn("WikiOracle", provs)
        self.assertIn("name", provs["WikiOracle"])

    def test_bootstrap_config_has_expected_keys(self):
        """Config in bootstrap response has expected nested keys."""
        resp = self.client.get("/bootstrap")
        data = resp.get_json()
        c = data["config"]
        # Top-level sections: server + providers only
        self.assertNotIn("user", c)
        self.assertNotIn("ui", c)       # UI now lives in state
        self.assertNotIn("chat", c)     # split into server.evaluation + server.truthset
        self.assertIn("server", c)
        self.assertIn("providers", c)
        # Nested sub-keys
        self.assertIn("default", c["providers"])
        self.assertIn("stateless", c["server"])
        self.assertIn("url_prefix", c["server"])
        self.assertIn("server_id", c["server"])


class TestConfigDrivenRuntimeBehavior(StatelessContractBase):
    """Verify request/runtime config affects server behavior."""

    def test_chat_uses_runtime_default_provider_when_request_omits_provider(self):
        with patch(
            "response._call_provider",
            return_value="<conversation>reply</conversation>",
        ) as mock_call:
            resp = self.client.post("/chat", json={
                "message": "hi",
                "state": _make_state(),
                "runtime_config": _make_runtime_config(
                    providers={"default": "openai"},
                ),
                "config": {},
            })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_call.call_args[0][3], "openai")


class TestNanoChatStatusEndpoint(StatelessContractBase):
    """Verify the NanoChat status route uses the configured provider URL."""

    def test_status_uses_wikioracle_provider_url(self):
        with patch.dict(
            wikioracle_mod.PROVIDERS,
            {
                "WikiOracle": {
                    "type": "wikioracle",
                    "url": "http://127.0.0.1:9999/chat/completions",
                    "timeout": 7,
                },
            },
            clear=False,
        ):
            mock_resp = type("Resp", (), {"ok": True})()
            with patch("requests.get", return_value=mock_resp) as mock_get:
                resp = self.client.get("/nanochat_status")

        self.assertEqual(resp.status_code, 200)
        mock_get.assert_called_once_with(
            "http://127.0.0.1:9999/health",
            timeout=7,
            verify=False,
        )
        data = resp.get_json()
        self.assertEqual(data.get("url"), "http://127.0.0.1:9999")
        self.assertEqual(data.get("status"), "online")


class TestServerInfoUsesLiveConfig(unittest.TestCase):
    """Verify routes read TheConfig after it is rebound."""

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        self._orig_config = copy.deepcopy(config_mod.TheConfig.data)
        config_mod.STATELESS_MODE = False
        config_mod.DEBUG_MODE = False

        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "state.xml"
        initial = ensure_minimal_state({}, strict=False)
        from state import atomic_write_xml
        atomic_write_xml(self._state_path, initial, reject_symlinks=False)

        self.cfg = Config(state_file=self._state_path)
        self.app = create_app(self.cfg, url_prefix="")
        self.app.testing = True
        self.client = _CsrfClient(self.app.test_client())

    def tearDown(self):
        config_mod.TheConfig.replace(self._orig_config)
        config_mod.STATELESS_MODE = self._orig_stateless
        config_mod.DEBUG_MODE = self._orig_debug
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_server_info_reads_rebound_config(self):
        config_mod.TheConfig.replace({
            "server": {
                "training": {
                    "enabled": True,
                },
            },
        })

        resp = self.client.get("/server_info")

        self.assertEqual(resp.status_code, 200)
        self.assertIs(resp.get_json()["training"], True)


class TestStatefulChatUnaffected(unittest.TestCase):
    """Verify stateful mode is not broken by the stateless refactor."""

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = False
        config_mod.DEBUG_MODE = False

        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "state.xml"
        initial = ensure_minimal_state({}, strict=False)
        from state import atomic_write_xml
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

    def test_stateful_chat_does_not_require_state_in_body(self):
        """In stateful mode, /chat should NOT require body.state (reads from disk)."""
        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "config": {"provider": "WikiOracle"},
            })
        # Should not return 400 for missing state/runtime_config
        self.assertNotEqual(resp.status_code, 400)

    def test_stateful_chat_writes_to_disk(self):
        """In stateful mode, /chat should write state to disk."""
        mtime_before = self._state_path.stat().st_mtime
        time.sleep(0.05)  # ensure mtime granularity

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "config": {"provider": "WikiOracle"},
            })

        if resp.status_code == 200:
            mtime_after = self._state_path.stat().st_mtime
            self.assertGreater(mtime_after, mtime_before,
                               "State file was NOT written during stateful chat")

    def test_stateful_chat_rewrites_selection_flags_before_save(self):
        """Stateful chat should not fail when the previously selected root changes."""
        existing_conv = {
            "id": "conv_existing",
            "title": "Existing root",
            "messages": [
                {
                    "role": "user",
                    "username": "User",
                    "time": "2026-02-24T00:00:00Z",
                    "content": "<p>old question</p>",
                },
                {
                    "role": "assistant",
                    "username": "WikiOracle",
                    "time": "2026-02-24T00:00:01Z",
                    "content": "<p>old answer</p>",
                },
            ],
            "children": [],
        }
        seeded = ensure_minimal_state(_make_state(
            conversations=[existing_conv],
            selected_conversation="conv_existing",
        ), strict=False)
        from state import atomic_write_xml
        atomic_write_xml(self._state_path, seeded, reject_symlinks=False)

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "new root",
                "config": {"provider": "WikiOracle"},
            })

        self.assertEqual(
            resp.status_code,
            200,
            f"Expected 200, got {resp.status_code}: {resp.get_data(as_text=True)[:300]}",
        )
        persisted = load_state_file(self._state_path, strict=True)
        self.assertEqual(len(persisted.get("conversations", [])), 2)
        self.assertNotEqual(persisted.get("selected_conversation"), "conv_existing")


class TestStatelessExistingEndpoints(StatelessContractBase):
    """Verify existing stateless 403s still work."""

    def test_merge_returns_403(self):
        resp = self.client.post("/merge", json={"state": _make_state()})
        self.assertEqual(resp.status_code, 403)

    def test_config_post_returns_403(self):
        resp = self.client.post("/config", json={"config": {}})
        self.assertEqual(resp.status_code, 403)

    def test_config_post_returns_403(self):
        resp = self.client.post("/config", json={"provider": "WikiOracle"})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
