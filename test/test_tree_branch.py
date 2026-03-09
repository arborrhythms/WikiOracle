#!/usr/bin/env python3
"""Tests for TreeView display and conversation branching.

TreeView display:
  - splitter_pct=0 guard: init must restore tree to a visible height
  - config normalization must not silently zero the splitter

Branching:
  - Branch from a node with one child must create a SECOND child
  - Branch from a node with no children must create a first child
  - Branch from root level must create a new root conversation
  - Optimistic conversation (client_owns_query) is updated, not duplicated

Diamond topology:
  - Voting diamond structure is correctly shaped for D3 tree rendering

Parallel creation:
  - Two root conversations created in sequence produce parallel children

Child/grandchild chaining:
  - Branch popup creates child, then grandchild (3-level depth)

Conversation splitting:
  - Branch on mid-conversation message splits into head + tail conversations
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

import config as config_mod
from config import Config
from wikioracle import create_app
from state import (
    SCHEMA_URL,
    STATE_VERSION,
    ensure_minimal_state,
    find_conversation,
    normalize_conversation,
    atomic_write_xml,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides):
    """Create a minimal valid v2 state dict with optional overrides."""
    base = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time": "2026-03-01T00:00:00Z",
        "context": "<div>Test context</div>",
        "conversations": [],
        "selected_conversation": None,
        "truth": [],
    }
    base.update(overrides)
    return base


def _make_runtime_config(**overrides):
    base = {
        "server": {
            "evaluation": {"temperature": 0.7, "url_fetch": False},
            "truthset": {"truth_weight": 0.7},
        },
        "providers": {"default": "wikioracle"},
    }
    base.update(overrides)
    return base


def _make_conversation(conv_id, title, messages=None, children=None, parent_id=None):
    """Create a minimal conversation dict."""
    conv = {
        "id": conv_id,
        "title": title,
        "messages": messages or [],
        "children": children or [],
        "parentId": parent_id,
    }
    return normalize_conversation(conv, parent_id=parent_id)


def _make_message(role, content, username=None, msg_id=None):
    """Create a minimal message dict."""
    msg = {
        "role": role,
        "content": f"<p>{content}</p>",
        "username": username or ("TestUser" if role == "user" else "TestLLM"),
        "time": "2026-03-01T00:00:00Z",
    }
    if msg_id:
        msg["id"] = msg_id
    return msg


class _CsrfClient:
    _CSRF = {"X-Requested-With": "WikiOracle"}

    def __init__(self, client):
        self._c = client

    def __getattr__(self, name):
        return getattr(self._c, name)

    def post(self, *args, headers=None, **kwargs):
        headers = {**(headers or {}), **self._CSRF}
        return self._c.post(*args, headers=headers, **kwargs)


class _BranchTestBase(unittest.TestCase):
    """Base for branching tests: stateless Flask test client."""

    def setUp(self):
        self._orig_stateless = config_mod.STATELESS_MODE
        self._orig_debug = config_mod.DEBUG_MODE
        config_mod.STATELESS_MODE = True
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

    def _chat(self, message, state_dict, branch_from=None, conversation_id=None):
        """Send a chat request and return (status, response_data)."""
        body = {
            "message": message,
            "state": state_dict,
            "runtime_config": _make_runtime_config(),
            "config": {"provider": "wikioracle"},
        }
        if branch_from:
            body["branch_from"] = branch_from
        if conversation_id:
            body["conversation_id"] = conversation_id
        with patch("response._call_nanochat", return_value="<p>test reply</p>"):
            resp = self.client.post("/chat", json=body)
        return resp.status_code, resp.get_json()


# ---------------------------------------------------------------------------
# TreeView display tests
# ---------------------------------------------------------------------------

class TestTreeDisplayConfig(unittest.TestCase):
    """Verify tree display safeguards."""

    def test_splitter_pct_zero_is_config_bug(self):
        """config.xml should never have splitter_pct=0 after init guard.

        The JavaScript guard in wikioracle.js:init() restores splitter_pct
        from 0 → 30.  This test verifies the config.xml shipped value is
        not 0, which would cause the tree to start collapsed.
        """
        cfg_path = _project / "config.xml"
        if not cfg_path.exists():
            self.skipTest("config.xml not present")
        text = cfg_path.read_text()
        # Look for <splitter_pct>0</splitter_pct>
        import re
        match = re.search(r"<splitter_pct>\s*(\d+(?:\.\d+)?)\s*</splitter_pct>", text)
        if match:
            pct = float(match.group(1))
            self.assertGreater(pct, 0,
                "config.xml has splitter_pct=0 which collapses the tree panel")

    def test_js_guard_restores_zero_splitter(self):
        """The JS init guard should restore splitter_pct=0 to 30%.

        This is a code-level check: verify the guard exists in wikioracle.js.
        """
        js_path = _project / "client" / "wikioracle.js"
        text = js_path.read_text()
        # The guard should check for pct <= 0 and set to 30
        self.assertIn("pct <= 0", text,
            "wikioracle.js should guard against splitter_pct <= 0")
        self.assertIn("pct = 30", text,
            "wikioracle.js should restore collapsed tree to 30%")


# ---------------------------------------------------------------------------
# Branching tests — stateless mode
# ---------------------------------------------------------------------------

class TestBranchFromNodeWithOneChild(_BranchTestBase):
    """Branch from a node that already has one child → must create a SECOND child."""

    def test_branch_creates_second_child(self):
        """POST /chat with branch_from=A where A has child B → A gets a second child."""
        child_b = _make_conversation("conv_B", "Child B",
            messages=[_make_message("user", "original question"),
                      _make_message("assistant", "original answer")])

        parent_a = _make_conversation("conv_A", "Parent A",
            messages=[_make_message("user", "root question"),
                      _make_message("assistant", "root answer")],
            children=[child_b])

        # Simulate client optimistic: add a new child C (like the JS client does)
        optimistic_c = _make_conversation("conv_C_opt", "branched message",
            messages=[_make_message("user", "branched message", msg_id="msg_opt")],
            parent_id="conv_A")
        parent_a["children"].append(optimistic_c)

        state = _make_state(
            conversations=[parent_a],
            selected_conversation="conv_C_opt",
        )

        status, data = self._chat("branched message", state, branch_from="conv_A")
        self.assertEqual(status, 200, f"Chat failed: {data}")

        # The returned state should have parent A with TWO children
        returned_convs = data["state"]["conversations"]
        returned_a = find_conversation(returned_convs, "conv_A")
        self.assertIsNotNone(returned_a, "Parent A not found in response")

        children = returned_a.get("children", [])
        self.assertGreaterEqual(len(children), 2,
            f"Expected ≥2 children of A, got {len(children)}: "
            f"{[c.get('id') for c in children]}")

        # Child B should still be present
        child_ids = {c["id"] for c in children}
        self.assertIn("conv_B", child_ids, "Original child B was lost")

    def test_branch_response_appended_to_optimistic(self):
        """In stateless mode, the server appends response to the optimistic conv."""
        child_b = _make_conversation("conv_B", "Child B",
            messages=[_make_message("user", "q"), _make_message("assistant", "a")])

        parent_a = _make_conversation("conv_A", "Parent A",
            messages=[_make_message("user", "rq"), _make_message("assistant", "ra")],
            children=[child_b])

        optimistic_c = _make_conversation("conv_C_opt", "new branch",
            messages=[_make_message("user", "new branch", msg_id="opt_msg")],
            parent_id="conv_A")
        parent_a["children"].append(optimistic_c)

        state = _make_state(
            conversations=[parent_a],
            selected_conversation="conv_C_opt",
        )

        status, data = self._chat("new branch", state, branch_from="conv_A")
        self.assertEqual(status, 200)

        # The optimistic conv should now have 2 messages (user + assistant)
        returned_c = find_conversation(data["state"]["conversations"], "conv_C_opt")
        self.assertIsNotNone(returned_c, "Optimistic conv C not found")
        self.assertEqual(len(returned_c.get("messages", [])), 2,
            "Optimistic conv should have user msg + assistant response")


class TestBranchFromNodeNoChildren(_BranchTestBase):
    """Branch from a leaf node → must create a first child."""

    def test_branch_creates_first_child(self):
        """POST /chat with branch_from on a leaf → creates first child."""
        leaf = _make_conversation("conv_leaf", "Leaf",
            messages=[_make_message("user", "leaf q"),
                      _make_message("assistant", "leaf a")])

        # Optimistic child
        optimistic = _make_conversation("conv_opt", "branch msg",
            messages=[_make_message("user", "branch msg")],
            parent_id="conv_leaf")
        leaf["children"].append(optimistic)

        state = _make_state(
            conversations=[leaf],
            selected_conversation="conv_opt",
        )

        status, data = self._chat("branch msg", state, branch_from="conv_leaf")
        self.assertEqual(status, 200)

        returned_leaf = find_conversation(data["state"]["conversations"], "conv_leaf")
        self.assertIsNotNone(returned_leaf)
        self.assertGreaterEqual(len(returned_leaf.get("children", [])), 1,
            "Leaf should have at least 1 child after branch")


class TestBranchNewRoot(_BranchTestBase):
    """New root conversation (no branch_from, no conversation_id)."""

    def test_new_root_creates_conversation(self):
        """POST /chat with no branch_from or conversation_id → new root."""
        state = _make_state(conversations=[])

        status, data = self._chat("hello world", state)
        self.assertEqual(status, 200)

        convs = data["state"]["conversations"]
        self.assertGreaterEqual(len(convs), 1,
            "Should have at least 1 conversation after new root chat")


# ---------------------------------------------------------------------------
# Diamond topology — verify structure for D3 tree rendering
# ---------------------------------------------------------------------------

class TestDiamondInTreeHierarchy(unittest.TestCase):
    """Verify that the voting diamond conversation structure is correctly
    shaped for the D3 conversationsToHierarchy() function.

    The JS function deduplicates nodes by conv.id and pushes extra
    parent→child edges into _diamondLinks.  This test builds the diamond
    data structure directly and asserts the properties that the JS relies on.
    """

    def _build_diamond(self):
        """Build the canonical diamond: root → [beta1, beta2] → final."""
        final = _make_conversation("conv_final", "Final consensus",
            messages=[_make_message("assistant", "synthesized answer")],
            parent_id=["conv_beta1", "conv_beta2"])
        # Override parentId to be a list (normalize_conversation may coerce it)
        final["parentId"] = ["conv_beta1", "conv_beta2"]

        beta1 = _make_conversation("conv_beta1", "Beta1",
            messages=[_make_message("assistant", "beta1 response")],
            children=[final],
            parent_id="conv_root")

        beta2 = _make_conversation("conv_beta2", "Beta2",
            messages=[_make_message("assistant", "beta2 response")],
            children=[final],  # same object — shared reference
            parent_id="conv_root")

        root = _make_conversation("conv_root", "Vote root",
            messages=[_make_message("user", "query")],
            children=[beta1, beta2])

        return root, beta1, beta2, final

    def test_final_appears_in_both_beta_children(self):
        """The final node must be a child of both beta1 and beta2."""
        root, beta1, beta2, final = self._build_diamond()
        self.assertIn(final, beta1["children"])
        self.assertIn(final, beta2["children"])

    def test_final_shares_same_id(self):
        """Both references to final must have the same id (JS dedup key)."""
        root, beta1, beta2, final = self._build_diamond()
        beta1_final = beta1["children"][-1]
        beta2_final = beta2["children"][-1]
        self.assertEqual(beta1_final["id"], beta2_final["id"])

    def test_final_parent_id_is_list(self):
        """final.parentId must be a list of both beta IDs."""
        root, beta1, beta2, final = self._build_diamond()
        self.assertIsInstance(final["parentId"], list,
            "Final parentId should be a list (diamond merge)")
        self.assertEqual(sorted(final["parentId"]),
                         sorted(["conv_beta1", "conv_beta2"]))

    def test_diamond_has_four_unique_ids(self):
        """The diamond tree should have exactly 4 unique conversation IDs."""
        root, beta1, beta2, final = self._build_diamond()

        def _collect_ids(conv, seen=None):
            if seen is None:
                seen = set()
            seen.add(conv["id"])
            for child in conv.get("children", []):
                if child["id"] not in seen:
                    _collect_ids(child, seen)
            return seen

        ids = _collect_ids(root)
        self.assertEqual(len(ids), 4,
            f"Expected 4 unique IDs (root, beta1, beta2, final), got {ids}")
        self.assertEqual(ids, {"conv_root", "conv_beta1", "conv_beta2", "conv_final"})


# ---------------------------------------------------------------------------
# Parallel root creation — two root conversations in sequence
# ---------------------------------------------------------------------------

class TestParallelRootCreation(_BranchTestBase):
    """Create two root conversations in sequence → two parallel children."""

    def test_two_root_conversations(self):
        """POST /chat twice with no branch_from → two root conversations."""
        # Step 1: Create first root conversation
        state = _make_state(conversations=[])
        status, data = self._chat("first question", state)
        self.assertEqual(status, 200, f"First chat failed: {data}")

        state1 = data["state"]
        convs1 = state1["conversations"]
        self.assertGreaterEqual(len(convs1), 1, "Should have at least 1 root conv")

        # Step 2: Navigate to root (clear selected_conversation)
        state1["selected_conversation"] = None

        # Step 3: Create second root conversation
        status, data = self._chat("second question", state1)
        self.assertEqual(status, 200, f"Second chat failed: {data}")

        convs2 = data["state"]["conversations"]
        self.assertGreaterEqual(len(convs2), 2,
            f"Expected ≥2 root conversations, got {len(convs2)}: "
            f"{[c.get('id') for c in convs2]}")

        # Both should be root-level (no parentId)
        for conv in convs2:
            self.assertIn(conv.get("parentId"), [None, ""],
                f"Root conversation '{conv['id']}' should have no parentId")


# ---------------------------------------------------------------------------
# Branch creates child and grandchild — 3-level depth
# ---------------------------------------------------------------------------

class TestBranchCreatesChildAndGrandchild(_BranchTestBase):
    """Branch popup on a node creates child, branching again creates grandchild."""

    def test_three_level_depth(self):
        """Create root → branch child → branch grandchild → 3 levels deep."""
        # Step 1: Create root conversation
        state = _make_state(conversations=[])
        status, data = self._chat("root question", state)
        self.assertEqual(status, 200, f"Root chat failed: {data}")

        state1 = data["state"]
        root_conv = state1["conversations"][0]
        root_id = root_conv["id"]

        # Step 2: Branch from root → creates child
        optimistic_b = _make_conversation("opt_b", "child question",
            messages=[_make_message("user", "child question", msg_id="opt_b_msg")],
            parent_id=root_id)
        root_conv["children"].append(optimistic_b)
        state1["selected_conversation"] = "opt_b"

        status, data = self._chat("child question", state1, branch_from=root_id)
        self.assertEqual(status, 200, f"Child chat failed: {data}")

        state2 = data["state"]
        returned_root = find_conversation(state2["conversations"], root_id)
        self.assertIsNotNone(returned_root, "Root not found after child branch")
        children = returned_root.get("children", [])
        self.assertGreaterEqual(len(children), 1, "Root should have at least 1 child")

        child_id = children[-1]["id"]  # the branched child

        # Step 3: Branch from child → creates grandchild
        child_conv = find_conversation(state2["conversations"], child_id)
        self.assertIsNotNone(child_conv, f"Child '{child_id}' not found")

        optimistic_c = _make_conversation("opt_c", "grandchild question",
            messages=[_make_message("user", "grandchild question", msg_id="opt_c_msg")],
            parent_id=child_id)
        child_conv["children"].append(optimistic_c)
        state2["selected_conversation"] = "opt_c"

        status, data = self._chat("grandchild question", state2, branch_from=child_id)
        self.assertEqual(status, 200, f"Grandchild chat failed: {data}")

        state3 = data["state"]
        returned_root = find_conversation(state3["conversations"], root_id)
        returned_child = find_conversation(state3["conversations"], child_id)
        self.assertIsNotNone(returned_child, "Child not found after grandchild branch")

        grandchildren = returned_child.get("children", [])
        self.assertGreaterEqual(len(grandchildren), 1,
            "Child should have at least 1 grandchild")

        # Verify 3-level nesting: root → child → grandchild
        self.assertGreaterEqual(len(returned_root.get("children", [])), 1)
        self.assertGreaterEqual(len(returned_child.get("children", [])), 1)

        grandchild = grandchildren[-1]
        self.assertGreaterEqual(len(grandchild.get("messages", [])), 1,
            "Grandchild should have at least 1 message")


# ---------------------------------------------------------------------------
# Conversation split — _splitAfterMessage algorithm
# ---------------------------------------------------------------------------

class TestConversationSplit(unittest.TestCase):
    """Verify that splitting a conversation at a message boundary produces
    correct head (original) and tail (new child) conversations.

    Replicates the client-side _splitAfterMessage(msgIdx) algorithm from
    wikioracle.js in Python to test the structural result.
    """

    @staticmethod
    def _split_after_message(conv, msg_idx):
        """Python equivalent of wikioracle.js _splitAfterMessage(msgIdx).

        Mutates conv in place:
        - conv.messages truncated to [:msg_idx+1]
        - new child gets messages[msg_idx+1:] and inherits conv's children
        - conv.children becomes [new_child]
        """
        if msg_idx < 0 or msg_idx >= len(conv["messages"]) - 1:
            return None  # nothing to split

        tail_messages = conv["messages"][msg_idx + 1:]
        conv["messages"] = conv["messages"][:msg_idx + 1]

        first_tail = tail_messages[0] if tail_messages else {}
        content = first_tail.get("content", "")
        # Strip tags for title (simplified)
        import re
        preview = re.sub(r"<[^>]+>", "", content)[:40]

        new_conv = {
            "id": "split_child_001",
            "title": preview or "Split",
            "messages": tail_messages,
            "children": conv.get("children", []),
            "parentId": conv["id"],
        }
        # Update moved children's parentId
        for child in new_conv["children"]:
            child["parentId"] = new_conv["id"]
        conv["children"] = [new_conv]

        return new_conv

    def test_split_produces_head_and_tail(self):
        """Split after message 1 of 4 → head has 2 msgs, tail has 2 msgs."""
        existing_child = _make_conversation("conv_X", "Existing child",
            messages=[_make_message("user", "child q")],
            parent_id="conv_main")

        conv = _make_conversation("conv_main", "Main conversation",
            messages=[
                _make_message("user", "question 1"),
                _make_message("assistant", "answer 1"),
                _make_message("user", "question 2"),
                _make_message("assistant", "answer 2"),
            ],
            children=[existing_child])

        new_child = self._split_after_message(conv, 1)
        self.assertIsNotNone(new_child, "Split should return new child")

        # Original keeps head messages
        self.assertEqual(len(conv["messages"]), 2,
            "Original should keep first 2 messages")
        self.assertEqual(conv["messages"][0]["role"], "user")
        self.assertEqual(conv["messages"][1]["role"], "assistant")

        # New child gets tail messages
        self.assertEqual(len(new_child["messages"]), 2,
            "New child should have last 2 messages")
        self.assertEqual(new_child["messages"][0]["role"], "user")
        self.assertEqual(new_child["messages"][1]["role"], "assistant")

        # New child's parentId is the original
        self.assertEqual(new_child["parentId"], "conv_main")

        # Original's children is now [new_child]
        self.assertEqual(len(conv["children"]), 1)
        self.assertEqual(conv["children"][0]["id"], "split_child_001")

        # Existing child X was reparented under the new child
        self.assertEqual(len(new_child["children"]), 1)
        self.assertEqual(new_child["children"][0]["id"], "conv_X")
        self.assertEqual(new_child["children"][0]["parentId"], "split_child_001")

    def test_split_at_last_message_returns_none(self):
        """Splitting after the last message should return None (nothing to split)."""
        conv = _make_conversation("conv_A", "Conv A",
            messages=[
                _make_message("user", "q"),
                _make_message("assistant", "a"),
            ])
        result = self._split_after_message(conv, 1)
        self.assertIsNone(result, "Split at last message should be no-op")
        self.assertEqual(len(conv["messages"]), 2, "Messages should be unchanged")

    def test_split_preserves_message_content(self):
        """Split must not lose or corrupt message content."""
        msgs = [
            _make_message("user", "alpha"),
            _make_message("assistant", "bravo"),
            _make_message("user", "charlie"),
            _make_message("assistant", "delta"),
        ]
        conv = _make_conversation("conv_S", "Splittable",
            messages=list(msgs))  # copy list

        new_child = self._split_after_message(conv, 1)
        self.assertIsNotNone(new_child)

        # Verify content preserved
        self.assertIn("alpha", conv["messages"][0]["content"])
        self.assertIn("bravo", conv["messages"][1]["content"])
        self.assertIn("charlie", new_child["messages"][0]["content"])
        self.assertIn("delta", new_child["messages"][1]["content"])


# ---------------------------------------------------------------------------
# Save test results to output/
# ---------------------------------------------------------------------------

class TestSaveOutputArtifacts(unittest.TestCase):
    """Save branch test state files to output/ for manual inspection."""

    def test_save_branch_state_to_output(self):
        """Save the pre-branch and post-branch state to output/ as XML."""
        output_dir = _project / "output"
        output_dir.mkdir(exist_ok=True)

        # Build a state with parent A having child B
        child_b = _make_conversation("conv_B", "Child B",
            messages=[_make_message("user", "original question"),
                      _make_message("assistant", "original answer")])
        parent_a = _make_conversation("conv_A", "Parent A",
            messages=[_make_message("user", "root question"),
                      _make_message("assistant", "root answer")],
            children=[child_b])
        pre_state = _make_state(
            conversations=[parent_a],
            selected_conversation="conv_A",
            title="Branch Test (pre-branch)",
        )
        pre_state = ensure_minimal_state(pre_state, strict=False)
        pre_path = output_dir / "branch_test_pre.xml"
        atomic_write_xml(pre_path, pre_state, reject_symlinks=False)
        self.assertTrue(pre_path.exists())

        # Add optimistic child C (simulating client branch)
        optimistic_c = _make_conversation("conv_C_opt", "branched message",
            messages=[_make_message("user", "branched message")],
            parent_id="conv_A")
        parent_a["children"].append(optimistic_c)
        post_state = _make_state(
            conversations=[parent_a],
            selected_conversation="conv_C_opt",
            title="Branch Test (post-branch with optimistic)",
        )
        post_state = ensure_minimal_state(post_state, strict=False)
        post_path = output_dir / "branch_test_post.xml"
        atomic_write_xml(post_path, post_state, reject_symlinks=False)
        self.assertTrue(post_path.exists())

        print(f"\n  Branch test artifacts saved:")
        print(f"    {pre_path}")
        print(f"    {post_path}")


if __name__ == "__main__":
    unittest.main()
