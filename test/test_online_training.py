#!/usr/bin/env python3
"""Integration test for the /train endpoint (online training via NanoChat).

Starts a NanoChat server with the local d6 checkpoint, mounts the WikiOracle
/train route, sends a training step, and verifies the loss is returned.

Requirements:
  - torch, fastapi, uvicorn (NanoChat's .venv-linux or equivalent)
  - nanochat/chatsft_checkpoints/d6/ must exist (small CPU demo model)

Skipped automatically if torch is not importable or checkpoint is missing.
Run via:
  cd nanochat && source .venv-linux/bin/activate && \
    PYTHONPATH=".:../bin" NANOCHAT_BASE_DIR="$(pwd)" \
    python3 -m pytest ../test/test_online_training.py -v

Or from the repo root:
  make test-train
"""

import os
import sys
import time
import unittest
import subprocess
import json
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
_nanochat = _project / "nanochat"
_bin = _project / "bin"
_checkpoint = _nanochat / "chatsft_checkpoints"

# Pre-flight checks
_skip_reason = None
try:
    import torch
except ImportError:
    _skip_reason = "torch not installed"

if not _skip_reason and not _checkpoint.exists():
    _skip_reason = f"No SFT checkpoint at {_checkpoint}"

try:
    import requests as _req
except ImportError:
    if not _skip_reason:
        _skip_reason = "requests not installed"

# Port for the ephemeral server
_PORT = 8199
_URL = f"http://127.0.0.1:{_PORT}"


@unittest.skipIf(_skip_reason, _skip_reason or "")
class TestOnlineTraining(unittest.TestCase):
    """End-to-end: start server → POST /train → verify loss."""

    _server_proc = None

    @classmethod
    def setUpClass(cls):
        """Start NanoChat server with /train route in a subprocess."""
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{_nanochat}:{_bin}"
        env["NANOCHAT_BASE_DIR"] = str(_nanochat)

        # Inline launcher script — avoids import-path issues with start_nanochat.py
        launcher = (
            "import sys; "
            f"sys.argv = ['test', '-p', '{_PORT}', '-d', 'float32', '--device-type', 'cpu']; "
            "from scripts.chat_web import app, args; "
            "from nanochat_ext import mount_train_route; "
            "mount_train_route(app); "
            "import uvicorn; "
            f"uvicorn.run(app, host='127.0.0.1', port={_PORT})"
        )

        cls._server_proc = subprocess.Popen(
            [sys.executable, "-c", launcher],
            env=env,
            cwd=str(_nanochat),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        # Wait for the server to start (poll /docs)
        for _ in range(30):
            time.sleep(1)
            try:
                r = _req.get(f"{_URL}/docs", timeout=2)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            # Check if process died
            if cls._server_proc.poll() is not None:
                out = cls._server_proc.stdout.read().decode()
                raise RuntimeError(f"Server exited early:\n{out}")

        raise RuntimeError("Server did not start within 30s")

    @classmethod
    def tearDownClass(cls):
        """Shut down the server."""
        if cls._server_proc and cls._server_proc.poll() is None:
            cls._server_proc.terminate()
            cls._server_proc.wait(timeout=10)

    def test_train_returns_loss(self):
        """A single /train step should return status=ok and a numeric loss."""
        resp = _req.post(f"{_URL}/train", json={
            "messages": [
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "The capital of France is Paris."},
            ],
            "degree_of_truth": 0.8,
            "device": "cpu",
        }, timeout=30)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIsInstance(data["loss"], float)
        self.assertGreater(data["loss"], 0.0)

    def test_train_loss_decreases(self):
        """Repeated steps on the same data should decrease loss."""
        losses = []
        for _ in range(4):
            resp = _req.post(f"{_URL}/train", json={
                "messages": [
                    {"role": "user", "content": "The sky is blue."},
                    {"role": "assistant", "content": "Yes, the sky appears blue due to Rayleigh scattering."},
                ],
                "degree_of_truth": 1.0,
                "device": "cpu",
            }, timeout=30)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            losses.append(data["loss"])
        # Loss should decrease overall (last < first)
        self.assertLess(losses[-1], losses[0],
                        f"Loss did not decrease: {losses}")

    def test_train_dot_zero_skips(self):
        """degree_of_truth ≈ 0 should skip training and return no loss."""
        resp = _req.post(f"{_URL}/train", json={
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
            "degree_of_truth": 0.0,
            "device": "cpu",
        }, timeout=30)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIsNone(data["loss"])
        self.assertIn("skipped", data.get("message", ""))

    def test_train_negative_dot_trains(self):
        """Negative DoT (false statement) should still train, returns gain."""
        resp = _req.post(f"{_URL}/train", json={
            "messages": [
                {"role": "user", "content": "Is the earth flat?"},
                {"role": "assistant", "content": "No, the earth is not flat."},
            ],
            "degree_of_truth": -0.9,
            "device": "cpu",
        }, timeout=30)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIsInstance(data["gain"], float)
        self.assertGreater(data["gain"], 0.0)

    def test_train_empty_messages_skips(self):
        """Empty messages should produce a skip, not an error."""
        resp = _req.post(f"{_URL}/train", json={
            "messages": [],
            "degree_of_truth": 1.0,
            "device": "cpu",
        }, timeout=30)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIsNone(data["loss"])


if __name__ == "__main__":
    unittest.main()
