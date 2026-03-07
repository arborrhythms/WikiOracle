# Test Plan: Tree & Conversation Branching Tests

## Overview

Add/verify four test scenarios in `test/test_tree_branch.py` covering the voting diamond in the D3 tree, parallel node creation, tree-panel branching, and conversation-panel splitting.

---

## Task 1: Verify voting diamond creates diamond links in D3 tree

**What:** Add a test that constructs a diamond conversation structure (alpha → beta1 + beta2 → final with `parentId: [beta1_id, beta2_id]`), passes it through `conversationsToHierarchy()`, and asserts that `_diamondLinks` is populated with the correct extra edges.

**Why:** The existing `test_vote_creates_diamond_structure` in `test_voting.py` only verifies the *server-side* data structure. No test currently verifies that the *client-side* `conversationsToHierarchy()` function correctly detects the shared final node and populates `_diamondLinks`.

**Approach:** Since `conversationsToHierarchy` is JavaScript (in `client/tree.js`), and the test suite is Python, we have two options:
1. **Port the logic to Python for testability** — replicate `conversationsToHierarchy` in a small Python helper and test the algorithm.
2. **Test the server-side diamond structure more thoroughly** — extend the existing `test_vote_creates_diamond_structure` to also verify that the shared final node (same object under multiple beta children) would produce diamond links by checking that `final` appears in multiple `beta.children` lists and that its `parentId` is a list.

**Decision:** Option 2 — the existing test already verifies the diamond data structure including `parentId` being a list. We'll add a focused assertion that the final node is literally the *same Python object* under each beta's children (since `conversationsToHierarchy` relies on `conv.id` deduplication, not object identity). We'll also add a new test class `TestDiamondInTreeHierarchy` that constructs a diamond conversation tree directly (matching what the JS `conversationsToHierarchy` would receive) and verifies the structural properties that the JS function relies on:
* The final node appears as a child of multiple beta nodes
* All instances share the same `id`
* `parentId` is a list of beta IDs

This validates that the server output is correctly shaped for the D3 diamond rendering.

**File:** `test/test_tree_branch.py`

---

## Task 2: Test parallel node creation (type+enter, then navigate to root, then empty enter)

**What:** Add a test that:
1. Creates a first node by sending a message (type text + press enter) — this creates a new root conversation
2. Navigates back to root (selected_conversation = null)
3. Creates a second node by sending empty (just press enter) — this should create a second root child

**Why:** Verifies that creating a node with content vs. creating an empty node both work at root level and produce two parallel children.

**Approach:** Use the existing `_BranchTestBase` with the Flask test client:
1. `POST /chat` with `message="hello"`, no `conversation_id` or `branch_from` → creates root conversation A
2. Take the returned state, set `selected_conversation=null` (navigate to root)
3. `POST /chat` with `message=""` (empty), no `conversation_id` or `branch_from` → should create root conversation B
4. Assert the returned state has 2 root conversations

**Note:** The server allows empty messages at terminal nodes. At the root level (no selected conversation), sending an empty message creates a new root conversation. We need to verify the server's `process_chat` handles this.

**File:** `test/test_tree_branch.py`, new class `TestParallelRootCreation`

---

## Task 3: Test TreePanel branch creates child and grandchild

**What:** Add a test that verifies: creating a node, then selecting "Branch" on that node creates a child, and the child can then have its own child (grandchild of the original).

**Why:** Confirms that `branchFromNode` + `sendMessage` correctly chains to create a child under a specific parent, and that the process can be repeated to create depth.

**Approach:** Use `_BranchTestBase`:
1. Create a root conversation by sending a message → get back state with conversation A
2. Send another message with `branch_from=A` → creates child B under A
3. Send another message with `branch_from=B` → creates grandchild C under B
4. Assert: A has child B, B has child C (three levels deep)

**File:** `test/test_tree_branch.py`, new class `TestBranchCreatesChildAndGrandchild`

---

## Task 4: Test ConversationPanel branch splits conversation at message boundary

**What:** Add a test that verifies `_splitAfterMessage` behavior: selecting "Branch" on a message within a conversation splits that conversation into two — the content before (and including) that message stays in the original, and the content after moves to a new child conversation.

**Why:** The `_splitAfterMessage(msgIdx)` function in `wikioracle.js` is a client-side operation. We need to verify the equivalent server-side behavior or test the split logic directly.

**Approach:** Since `_splitAfterMessage` is purely client-side JavaScript (it modifies `state.conversations` in-place and calls `renderMessages`), we can test the equivalent logic in Python:
1. Build a conversation with 4 messages: [user1, assistant1, user2, assistant2]
2. Simulate splitting after message index 1 (after assistant1):
   * Original conversation keeps messages [user1, assistant1]
   * New child conversation gets messages [user2, assistant2]
   * New child inherits the original's children
   * Original's children becomes [new_child]
3. Assert the split is correct: original has 2 messages, child has 2 messages, parentId is set correctly

This tests the split algorithm. Since the JS `_splitAfterMessage` uses `conv.messages.splice()` and creates a new child, we replicate this in Python using list slicing and verify the structural result.

**File:** `test/test_tree_branch.py`, new class `TestConversationSplit`

---

## Files Modified

* `test/test_tree_branch.py` — add 4 new test classes:
  1. `TestDiamondInTreeHierarchy` — voting diamond produces correct structure for D3
  2. `TestParallelRootCreation` — two root nodes created in parallel
  3. `TestBranchCreatesChildAndGrandchild` — branch popup creates child + grandchild chain
  4. `TestConversationSplit` — branch on message splits conversation into two

## No Other Files Modified

All changes are test-only additions to the existing test file.
