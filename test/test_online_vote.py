#!/usr/bin/env python3
"""Online integration test: run a vote and verify the diamond pattern.

Requires a Gemini API key in config.xml.  Copies alpha/beta fixtures
to output/, rewrites authority URLs, runs the vote via Flask test client,
and validates the diamond conversation structure.

Run via:
    make test   (runs in the online vote section, non-blocking)

Or standalone:
    source .venv/bin/activate && python3 -m unittest test.test_online_vote -v
"""

import os
import shutil
import sys
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project / "bin"))


class TestAlphaOutputDiamond(unittest.TestCase):
    """Integration test: run a vote and verify the diamond pattern.

    Copies alpha/beta fixtures to output/, rewrites authority URLs,
    runs the vote via Flask test client, and validates the diamond
    conversation structure:

           root (query + prelim)     <- 1 root, 2 messages
          /    \\
        beta1  beta2                 <- children of root, 1 message each
          \\    /
           final                     <- parentId: [beta1, beta2], 1 message, selected

    Requires a Gemini API key in config.xml.  Skipped otherwise.
    """

    _test_dir = Path(__file__).resolve().parent
    _output_dir = _project / "output"
    _output_file = _output_dir / "alpha.xml"
    _skip_reason = None
    _vote_state = None
    _orig_env = None
    _orig_stateless = None
    _orig_debug = None

    @classmethod
    def setUpClass(cls):
        import config as config_mod
        from config import _load_config, load_config
        from wikioracle import create_app

        # Check for Gemini API key
        raw_cfg = _load_config()
        if not raw_cfg or not raw_cfg.get("providers", {}).get("gemini", {}).get("api_key"):
            cls._skip_reason = "No Gemini API key in config"
            return

        # Preserve global state
        cls._orig_env = os.environ.get("WIKIORACLE_STATE_FILE")
        cls._orig_stateless = config_mod.STATELESS_MODE
        cls._orig_debug = config_mod.DEBUG_MODE

        # Set up output directory with fixtures
        cls._output_dir.mkdir(exist_ok=True)
        for name in ("alpha.xml", "beta1.xml", "beta2.xml"):
            shutil.copy2(cls._test_dir / name, cls._output_dir / name)

        # Rewrite authority paths: file://test/ -> file://output/
        text = cls._output_file.read_text(encoding="utf-8")
        text = text.replace("file://test/", "file://output/")
        cls._output_file.write_text(text, encoding="utf-8")

        # Configure the Flask app to use the output alpha state
        os.environ["WIKIORACLE_STATE_FILE"] = str(cls._output_file)
        config_mod.STATELESS_MODE = False
        config_mod.DEBUG_MODE = False

        app_cfg = load_config()
        app = create_app(app_cfg, url_prefix="")
        app.testing = True
        client = app.test_client()

        # Run the vote: POST /chat with Gemini as provider
        resp = client.post("/chat",
            json={
                "message": "Lets have a vote on taxes. Should we raise them?",
                "config": {"provider": "gemini"},
            },
            headers={"X-Requested-With": "WikiOracle"},
        )
        data = resp.get_json()
        if not data or not data.get("ok"):
            err = data.get("error", "unknown") if data else "no response"
            cls._skip_reason = f"Vote call failed: {err}"
            return
        # Check if the response text is actually a provider error (quota etc.)
        text = data.get("text", "")
        if text.startswith("[Error"):
            cls._skip_reason = f"Provider returned error: {text[:120]}"
            return

        # Load the state that the server wrote to disk
        from state import load_state_file
        cls._vote_state = load_state_file(cls._output_file, strict=False)

    @classmethod
    def tearDownClass(cls):
        import config as config_mod
        # Restore global state
        if cls._orig_env is not None:
            os.environ["WIKIORACLE_STATE_FILE"] = cls._orig_env
        elif "WIKIORACLE_STATE_FILE" in os.environ:
            del os.environ["WIKIORACLE_STATE_FILE"]
        if cls._orig_stateless is not None:
            config_mod.STATELESS_MODE = cls._orig_stateless
        if cls._orig_debug is not None:
            config_mod.DEBUG_MODE = cls._orig_debug

    def setUp(self):
        if self._skip_reason:
            self.skipTest(self._skip_reason)

    def test_diamond_in_output_alpha(self):
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
