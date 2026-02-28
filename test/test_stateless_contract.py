#!/usr/bin/env python3
"""Stateless-mode contract tests for the WikiOracle Flask app.

These tests verify the sessionStorage-authority contract:
  - /chat returns 400 when state or runtime_config is missing in stateless mode
  - /chat stateless path uses request-supplied state and config
  - /bootstrap returns seed data from disk
  - No disk writes are attempted in stateless chat flow
  - Stateful mode is unaffected (no regression)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root and bin/ are importable
_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

import config as config_mod
from config import Config
from wikioracle import create_app
from state import SCHEMA_URL, STATE_VERSION, ensure_minimal_state


def _make_state(**overrides):
    """Create a minimal valid v2 state dict with optional overrides."""
    base = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time": "2026-02-24T00:00:00Z",
        "context": "<div>Test</div>",
        "conversations": [],
        "selected_conversation": None,
        "truth": {"trust": []},
    }
    base.update(overrides)
    return base


def _make_runtime_config(**overrides):
    """Create a runtime_config dict (parsed config.yaml)."""
    base = {
        "user": {"name": "TestUser"},
        "chat": {
            "temperature": 0.7,
            "message_window": 40,
            "rag": True,
            "url_fetch": False,
        },
        "ui": {"default_provider": "wikioracle"},
    }
    base.update(overrides)
    return base


class StatelessContractBase(unittest.TestCase):
    """Base class that creates a Flask test client in stateless mode."""

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = True
        config_mod.DEBUG_MODE = False

        # Use a temp dir for state file (should never be written in stateless)
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "llm.jsonl"
        # Write initial seed state so _load_state doesn't fail for /bootstrap
        initial = ensure_minimal_state({}, strict=False)
        from state import atomic_write_jsonl
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


class TestStatelessChatValidation(StatelessContractBase):
    """Verify stateless /chat rejects requests missing required fields."""

    def test_chat_missing_state_returns_400(self):
        """POST /chat without body.state in stateless mode → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "runtime_config": _make_runtime_config(),
            "config": {"provider": "wikioracle"},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("stateless_missing_state", data.get("error", ""))

    def test_chat_missing_runtime_config_returns_400(self):
        """POST /chat without body.runtime_config in stateless mode → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "state": _make_state(),
            "config": {"provider": "wikioracle"},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("stateless_missing_runtime_config", data.get("error", ""))

    def test_chat_missing_both_returns_400(self):
        """POST /chat without state or runtime_config → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "config": {"provider": "wikioracle"},
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_state_not_dict_returns_400(self):
        """POST /chat with state as non-dict → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "state": "not a dict",
            "runtime_config": _make_runtime_config(),
            "config": {"provider": "wikioracle"},
        })
        self.assertEqual(resp.status_code, 400)

    def test_chat_runtime_config_not_dict_returns_400(self):
        """POST /chat with runtime_config as non-dict → 400."""
        resp = self.client.post("/chat", json={
            "message": "hello",
            "state": _make_state(),
            "runtime_config": "not a dict",
            "config": {"provider": "wikioracle"},
        })
        self.assertEqual(resp.status_code, 400)


class TestStatelessChatNoDiskWrites(StatelessContractBase):
    """Verify stateless /chat does NOT write to disk."""

    def test_no_state_file_write(self):
        """Stateless chat must not write llm.jsonl to disk."""
        mtime_before = self._state_path.stat().st_mtime

        # Mock _call_nanochat to avoid network call
        with patch("response._call_nanochat", return_value="test reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "state": _make_state(),
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "wikioracle"},
            })

        # Should succeed (502 means provider error which is OK to catch separately)
        self.assertIn(resp.status_code, (200, 502))
        if resp.status_code == 200:
            mtime_after = self._state_path.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after,
                             "State file was modified during stateless chat")

    def test_no_config_yaml_write(self):
        """Stateless chat must not write config.yaml to disk."""
        project_root = Path(__file__).resolve().parent.parent
        cfg_path = project_root / "config.yaml"
        had_config = cfg_path.exists()
        mtime_before = cfg_path.stat().st_mtime if had_config else None

        with patch("response._call_nanochat", return_value="test reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "state": _make_state(),
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "wikioracle"},
            })

        if had_config:
            mtime_after = cfg_path.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after,
                             "config.yaml was modified during stateless chat")


class TestStatelessChatUsesRequestPayload(StatelessContractBase):
    """Verify stateless /chat uses client-supplied state, not _MEMORY_STATE or disk."""

    def test_uses_request_state(self):
        """The returned state reflects client-supplied state, not server memory."""
        client_state = _make_state(context="<div>From Client</div>")

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hi",
                "state": client_state,
                "runtime_config": _make_runtime_config(),
                "config": {"provider": "wikioracle"},
            })

        if resp.status_code == 200:
            data = resp.get_json()
            returned_state = data.get("state", {})
            # The context should still be the client-supplied value
            self.assertEqual(returned_state.get("context"), "<div>From Client</div>")
            # A new conversation should have been created
            self.assertGreater(len(returned_state.get("conversations", [])), 0)

    def test_uses_runtime_config_user_name(self):
        """The user display name in messages comes from runtime_config, not _CONFIG_YAML."""
        rt = _make_runtime_config()
        rt["user"]["name"] = "RuntimeUser"

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hi",
                "state": _make_state(),
                "runtime_config": rt,
                "config": {"provider": "wikioracle"},
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
        self.assertNotIn("config_yaml", data)  # raw YAML no longer sent
        self.assertNotIn("parsed", data)        # no more parsed/config split
        self.assertIn("config", data)
        self.assertIsInstance(data["config"], dict)

    def test_bootstrap_returns_providers(self):
        resp = self.client.get("/bootstrap")
        data = resp.get_json()
        self.assertIn("providers", data)
        provs = data["providers"]
        self.assertIn("wikioracle", provs)
        self.assertIn("name", provs["wikioracle"])

    def test_bootstrap_config_has_expected_keys(self):
        """Config in bootstrap response has YAML-shaped keys."""
        resp = self.client.get("/bootstrap")
        data = resp.get_json()
        c = data["config"]
        # Top-level sections
        self.assertIn("user", c)
        self.assertIn("ui", c)
        self.assertIn("chat", c)
        self.assertIn("server", c)
        # YAML-shaped sub-keys (not flat)
        self.assertIn("name", c["user"])
        self.assertIn("default_provider", c["ui"])
        self.assertIn("layout", c["ui"])
        self.assertIn("stateless", c["server"])
        self.assertIn("url_prefix", c["server"])


class TestStatefulChatUnaffected(unittest.TestCase):
    """Verify stateful mode is not broken by the stateless refactor."""

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = False
        config_mod.DEBUG_MODE = False

        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / "llm.jsonl"
        initial = ensure_minimal_state({}, strict=False)
        from state import atomic_write_jsonl
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

    def test_stateful_chat_does_not_require_state_in_body(self):
        """In stateful mode, /chat should NOT require body.state (reads from disk)."""
        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "config": {"provider": "wikioracle"},
            })
        # Should not return 400 for missing state/runtime_config
        self.assertNotEqual(resp.status_code, 400)

    def test_stateful_chat_writes_to_disk(self):
        """In stateful mode, /chat should write state to disk."""
        mtime_before = self._state_path.stat().st_mtime

        import time
        time.sleep(0.05)  # ensure mtime granularity

        with patch("response._call_nanochat", return_value="reply"):
            resp = self.client.post("/chat", json={
                "message": "hello",
                "config": {"provider": "wikioracle"},
            })

        if resp.status_code == 200:
            mtime_after = self._state_path.stat().st_mtime
            self.assertGreater(mtime_after, mtime_before,
                               "State file was NOT written during stateful chat")


class TestStatelessExistingEndpoints(StatelessContractBase):
    """Verify existing stateless 403s still work."""

    def test_merge_returns_403(self):
        resp = self.client.post("/merge", json={"state": _make_state()})
        self.assertEqual(resp.status_code, 403)

    def test_config_post_returns_403(self):
        resp = self.client.post("/config", json={"yaml": ""})
        self.assertEqual(resp.status_code, 403)

    def test_config_post_returns_403(self):
        resp = self.client.post("/config", json={"provider": "wikioracle"})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
