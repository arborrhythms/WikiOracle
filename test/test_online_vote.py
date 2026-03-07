#!/usr/bin/env python3
"""Diamond vote integration test using a local NanoChat server.

Starts NanoChat via ``make nano_start`` on a test port, copies alpha/beta
fixtures to output/ with beta providers rewritten to point at the local
server, runs the vote via Flask test client, and validates the diamond
conversation structure:

       root (query + prelim)     <- 1 root, 2 messages
      /    \\
    beta1  beta2                 <- children of root, 1 message each
      \\    /
       final                     <- parentId: [beta1, beta2], 1 message, selected

Run via:
    make test
"""

import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

import requests as _req

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project / "bin"))

_PORT = 8198
_NANO_URL = f"http://127.0.0.1:{_PORT}"


def _wait_for_server(url: str, timeout: int = 45) -> bool:
    """Poll *url*/docs until it responds or *timeout* expires."""
    for _ in range(timeout):
        try:
            r = _req.get(f"{url}/docs", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


class TestAlphaOutputDiamond(unittest.TestCase):
    """Integration test: run a diamond vote against a local NanoChat server.

    Starts NanoChat via ``make nano_start NANO_PORT=<port>``, rewrites the
    alpha.xml beta providers to point at localhost, then exercises the full
    voting pipeline through the WikiOracle Flask app.  Stops the server via
    ``make nano_stop`` in tearDownClass.
    """

    _test_dir = Path(__file__).resolve().parent
    _output_dir = _project / "output"
    _output_file = _output_dir / "alpha.xml"
    _vote_state = None
    _setup_error = None
    _orig_env = None
    _orig_stateless = None
    _orig_debug = None
    _orig_wo_url = None

    @classmethod
    def setUpClass(cls):
        import config as config_mod
        from config import load_config
        from response import PROVIDERS
        from wikioracle import create_app

        # ── Start NanoChat server via Makefile target ──
        result = subprocess.run(
            ["make", "nano_start", f"NANO_PORT={_PORT}"],
            cwd=str(_project),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            cls._setup_error = f"make nano_start failed:\n{result.stdout}\n{result.stderr}"
            return
        if not _wait_for_server(_NANO_URL):
            cls._setup_error = f"NanoChat did not start within 45s"
            return

        # ── Preserve global state ──
        cls._orig_env = os.environ.get("WIKIORACLE_STATE_FILE")
        cls._orig_stateless = config_mod.STATELESS_MODE
        cls._orig_debug = config_mod.DEBUG_MODE
        cls._orig_wo_url = PROVIDERS.get("wikioracle", {}).get("url")

        # Point the wikioracle provider at the test server
        PROVIDERS.setdefault("wikioracle", {})["url"] = f"{_NANO_URL}/chat/completions"

        # ── Set up fixtures ──
        cls._output_dir.mkdir(exist_ok=True)
        for name in ("alpha.xml", "beta1.xml", "beta2.xml"):
            shutil.copy2(cls._test_dir / name, cls._output_dir / name)

        # Rewrite alpha.xml:
        #   - authority paths: file://test/ -> file://output/
        #   - beta providers: Gemini -> local NanoChat
        text = cls._output_file.read_text(encoding="utf-8")
        text = text.replace("file://test/", "file://output/")
        text = text.replace(
            'api_url="https://generativelanguage.googleapis.com/v1beta/models" model="gemini-2.5-flash"',
            f'api_url="{_NANO_URL}/chat/completions" model="nanochat"',
        )
        cls._output_file.write_text(text, encoding="utf-8")

        # ── Configure Flask app ──
        os.environ["WIKIORACLE_STATE_FILE"] = str(cls._output_file)
        config_mod.STATELESS_MODE = False
        config_mod.DEBUG_MODE = False

        app_cfg = load_config()
        app = create_app(app_cfg, url_prefix="")
        app.testing = True
        client = app.test_client()

        # ── Run the vote ──
        resp = client.post("/chat",
            json={
                "message": "Lets have a vote on taxes. Should we raise them?",
                "config": {"provider": "wikioracle"},
            },
            headers={"X-Requested-With": "WikiOracle"},
        )

        data = resp.get_json()
        if not data or not data.get("ok"):
            err = data.get("error", "unknown") if data else "no response"
            cls._setup_error = f"Vote call failed: {err}"
            return
        text = data.get("text", "")
        if text.startswith("[Error"):
            cls._setup_error = f"Provider returned error: {text[:200]}"
            return

        # Load the state that the server wrote to disk
        from state import load_state_file
        cls._vote_state = load_state_file(cls._output_file, strict=False)

    @classmethod
    def tearDownClass(cls):
        import config as config_mod
        from response import PROVIDERS

        # Stop NanoChat via Makefile target
        subprocess.run(
            ["make", "nano_stop"],
            cwd=str(_project),
            capture_output=True,
        )

        # Restore global state
        if cls._orig_env is not None:
            os.environ["WIKIORACLE_STATE_FILE"] = cls._orig_env
        elif "WIKIORACLE_STATE_FILE" in os.environ:
            del os.environ["WIKIORACLE_STATE_FILE"]
        if cls._orig_stateless is not None:
            config_mod.STATELESS_MODE = cls._orig_stateless
        if cls._orig_debug is not None:
            config_mod.DEBUG_MODE = cls._orig_debug
        if cls._orig_wo_url is not None:
            PROVIDERS.setdefault("wikioracle", {})["url"] = cls._orig_wo_url

    def test_diamond_in_output_alpha(self):
        if self._setup_error:
            self.fail(self._setup_error)

        state = self._vote_state
        self.assertIsNotNone(state, "Vote state should have been loaded")

        convs = state.get("conversations", [])
        self.assertGreaterEqual(len(convs), 1,
                                "output/alpha.xml should have at least one root conversation")

        root = convs[0]

        # Root should have 2 messages: user query + alpha preliminary
        self.assertEqual(len(root["messages"]), 2,
                         "Diamond root should have user query + alpha prelim")
        self.assertEqual(root["messages"][0]["role"], "user")
        self.assertEqual(root["messages"][1]["role"], "assistant")

        # Root has only betas as direct children
        betas = root.get("children", [])
        self.assertGreaterEqual(len(betas), 2,
                                f"Root should have >=2 beta children, got {len(betas)}")

        # Each beta has 1 message and final as a child
        for i, beta in enumerate(betas):
            self.assertEqual(len(beta["messages"]), 1,
                             f"Beta {i} should have exactly one message")
            self.assertEqual(beta["messages"][0]["role"], "assistant",
                             f"Beta {i} first message should be assistant")
            self.assertGreaterEqual(len(beta.get("children", [])), 1,
                                    f"Beta {i} should have final as child")

        # Final is shared across all betas (same ID)
        finals = [b["children"][-1] for b in betas]
        final_ids = set(f["id"] for f in finals)
        self.assertEqual(len(final_ids), 1,
                         f"All betas should share the same final, got {final_ids}")
        final = finals[0]

        # Final should be the selected conversation
        self.assertEqual(state.get("selected_conversation"), final["id"],
                         "selected_conversation should point to the final node")

        # Final has two parents (both betas) — true diamond
        self.assertIsInstance(final.get("parentId"), list,
                              "Final parentId should be a list (diamond merge)")
        beta_ids = [b["id"] for b in betas]
        self.assertEqual(sorted(final["parentId"]), sorted(beta_ids),
                         "Final parentId should list all beta IDs")

        # Root title should exist (was a prior bug)
        self.assertTrue(root.get("title"),
                        "Diamond root should have a non-empty title")

        print(f"\n  Diamond verified: root '{root['title']}' -> "
              f"{len(betas)} betas, final '{final.get('title', '?')}'  "
              f"(parentId: {final['parentId']})")


if __name__ == "__main__":
    unittest.main()
