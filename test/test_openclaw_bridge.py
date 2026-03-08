#!/usr/bin/env python3
"""Unit tests for bin/openclaw_ext.py — WikiOracle ↔ OpenClaw bridge.

These tests exercise the WikiOracleBridge class in isolation using a mock
HTTP server.  No running WikiOracle or OpenClaw instance is required.

Run via:
    python3 -m pytest test/test_openclaw_bridge.py -v
    # or: make test_unit
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Ensure bin/ is on the path for direct imports
_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project / "bin"))

from openclaw_ext import WikiOracleBridge


# =====================================================================
#  Mock WikiOracle HTTP server
# =====================================================================

class _MockWikiOracleHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler emulating WikiOracle's /chat and /health endpoints."""

    # Class-level overrides for test customization
    response_delay: float = 0.0
    force_error: bool = False
    last_payload: dict | None = None

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):  # noqa: N802
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            if self.force_error:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"error": "forced error"}')
                return

            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return

            # Store the last payload for inspection
            _MockWikiOracleHandler.last_payload = payload

            # Echo back a simple response with state
            response = {
                "content": f"Echo: {payload.get('message', '')}",
                "conversation_id": payload.get("conversation_id", "conv-001"),
                "state": {"messages": [payload.get("message", "")]},
            }
            resp_data = json.dumps(response).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_data)))
            self.end_headers()
            self.wfile.write(resp_data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress stdout logging during tests."""
        pass


def _start_mock_server() -> tuple[HTTPServer, int]:
    """Start a mock WikiOracle server on a random port. Returns (server, port)."""
    server = HTTPServer(("127.0.0.1", 0), _MockWikiOracleHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# =====================================================================
#  Tests
# =====================================================================

class TestWikiOracleBridgeInit(unittest.TestCase):
    """Bridge initialization and configuration."""

    def test_default_server_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(state_dir=tmpdir)
            self.assertEqual(bridge.server_url, "http://localhost:5000")

    def test_custom_server_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge("http://example.com:9999/", state_dir=tmpdir)
            # Trailing slash should be stripped
            self.assertEqual(bridge.server_url, "http://example.com:9999")

    def test_state_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = os.path.join(tmpdir, "sessions")
            bridge = WikiOracleBridge(state_dir=state_dir)
            self.assertTrue(os.path.isdir(state_dir))

    def test_custom_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(timeout=60, state_dir=tmpdir)
            self.assertEqual(bridge.timeout, 60)


class TestWikiOracleBridgeSend(unittest.TestCase):
    """Bridge send() method with a live mock server."""

    @classmethod
    def setUpClass(cls):
        cls._server, cls._port = _start_mock_server()
        cls._url = f"http://127.0.0.1:{cls._port}"

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.bridge = WikiOracleBridge(self._url, state_dir=self._tmpdir)
        _MockWikiOracleHandler.force_error = False
        _MockWikiOracleHandler.last_payload = None

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_send_message(self):
        """send() returns a response with content."""
        resp = self.bridge.send("Hello!", channel_id="test-chan")
        self.assertIn("content", resp)
        self.assertIn("Echo: Hello!", resp["content"])
        self.assertNotIn("error", resp)

    def test_send_includes_username(self):
        """send() includes user_id as username in payload."""
        self.bridge.send("Hi", channel_id="ch1", user_id="alice")
        payload = _MockWikiOracleHandler.last_payload
        self.assertIsNotNone(payload)
        self.assertEqual(payload["username"], "alice")

    def test_send_includes_conversation_id(self):
        """send() includes conversation_id when provided."""
        self.bridge.send("Hi", conversation_id="conv-42")
        payload = _MockWikiOracleHandler.last_payload
        self.assertEqual(payload["conversation_id"], "conv-42")

    def test_session_persistence(self):
        """State is saved after first send and included in subsequent sends."""
        # First message — no state yet
        self.bridge.send("First message", channel_id="persist-ch")
        # State should now be saved
        state_file = self.bridge._state_path("persist-ch")
        self.assertTrue(state_file.exists())

        # Second message — state should be included in payload
        self.bridge.send("Second message", channel_id="persist-ch")
        payload = _MockWikiOracleHandler.last_payload
        self.assertIn("state", payload)

    def test_separate_channels_have_separate_state(self):
        """Different channels maintain independent session state."""
        self.bridge.send("Msg to A", channel_id="channel-A")
        self.bridge.send("Msg to B", channel_id="channel-B")

        state_a = self.bridge._state_path("channel-A")
        state_b = self.bridge._state_path("channel-B")
        self.assertTrue(state_a.exists())
        self.assertTrue(state_b.exists())
        self.assertNotEqual(state_a, state_b)

    def test_channel_id_sanitized(self):
        """Special characters in channel_id are sanitized for file safety."""
        self.bridge.send("Hi", channel_id="slack/general#2024")
        # Should not crash; state file should be created
        state_path = self.bridge._state_path("slack/general#2024")
        # The path should use sanitized characters
        self.assertNotIn("/", state_path.name)
        self.assertNotIn("#", state_path.name)


class TestWikiOracleBridgeHealthCheck(unittest.TestCase):
    """Bridge health_check() method."""

    @classmethod
    def setUpClass(cls):
        cls._server, cls._port = _start_mock_server()
        cls._url = f"http://127.0.0.1:{cls._port}"

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()

    def test_health_check_returns_true(self):
        """health_check() returns True when server is up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(self._url, state_dir=tmpdir)
            self.assertTrue(bridge.health_check())

    def test_health_check_returns_false_when_down(self):
        """health_check() returns False when server is unreachable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge("http://127.0.0.1:1", state_dir=tmpdir, timeout=1)
            self.assertFalse(bridge.health_check())


class TestWikiOracleBridgeErrorHandling(unittest.TestCase):
    """Bridge error handling and graceful degradation."""

    @classmethod
    def setUpClass(cls):
        cls._server, cls._port = _start_mock_server()
        cls._url = f"http://127.0.0.1:{cls._port}"

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()

    def test_unreachable_server(self):
        """send() returns error dict when server is unreachable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge("http://127.0.0.1:1", state_dir=tmpdir, timeout=1)
            resp = bridge.send("Hello")
            self.assertIn("error", resp)
            self.assertTrue(resp["error"])
            self.assertIn("Error:", resp["content"])

    def test_default_channel_id(self):
        """send() uses 'default' channel when none specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(self._url, state_dir=tmpdir)
            resp = bridge.send("Hello")
            self.assertIn("content", resp)
            # Default channel state should be saved
            state_path = bridge._state_path("default")
            self.assertTrue(state_path.exists())


class TestWikiOracleBridgeSessionState(unittest.TestCase):
    """Session state file management."""

    def test_load_nonexistent_session(self):
        """Loading state for a new channel returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(state_dir=tmpdir)
            state = bridge._load_session_state("new-channel")
            self.assertIsNone(state)

    def test_save_and_load_session(self):
        """Saved state is retrievable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(state_dir=tmpdir)
            test_state = {"messages": ["hello", "world"], "context": {"key": "value"}}
            bridge._save_session_state("test-ch", test_state)
            loaded = bridge._load_session_state("test-ch")
            self.assertEqual(loaded, test_state)

    def test_corrupted_state_returns_none(self):
        """Corrupted state files return None instead of crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = WikiOracleBridge(state_dir=tmpdir)
            # Write garbage to the state file
            state_path = bridge._state_path("bad-ch")
            state_path.write_text("not json {{{", encoding="utf-8")
            loaded = bridge._load_session_state("bad-ch")
            self.assertIsNone(loaded)


if __name__ == "__main__":
    unittest.main()
