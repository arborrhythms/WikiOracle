"""Pure node/edge algorithms for conversation trees and DAGs.

Nodes are dicts with ``id``, ``children``, ``messages``, ``selected``, ``parentId``.
Edges are implicit: ``children`` lists define parent→child, ``parentId`` stores
the reverse link (a string or a list of strings for diamond merges).

All functions operate on a conversation list (forest) passed as argument.
No module-level mutable state is read or written.
"""

from __future__ import annotations

from typing import Any, Iterable

from truth import StateValidationError


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------

def iter_conversation_paths(conversations: list) -> Iterable[tuple[dict, list[dict]]]:
    """Yield each conversation with its root-to-node path."""
    def _walk(nodes: list, path: list[dict]) -> Iterable[tuple[dict, list[dict]]]:
        for conv in nodes:
            new_path = path + [conv]
            yield conv, new_path
            yield from _walk(conv.get("children", []), new_path)

    yield from _walk(conversations, [])


# ---------------------------------------------------------------------------
# Node lookup
# ---------------------------------------------------------------------------

def find_conversation(conversations: list, conv_id: str) -> dict | None:
    """Find a conversation by ID in the tree (recursive)."""
    for conv in conversations:
        if conv.get("id") == conv_id:
            return conv
        found = find_conversation(conv.get("children", []), conv_id)
        if found is not None:
            return found
    return None


def get_ancestor_chain(conversations: list, conv_id: str) -> list:
    """Return list of conversations from root to the given conv_id (inclusive).

    Each element is the conversation dict. Returns [] if not found.
    Uses DFS; for diamond nodes returns the first path found.
    """
    def _search(convs, target, path):
        for conv in convs:
            new_path = path + [conv]
            if conv.get("id") == target:
                return new_path
            result = _search(conv.get("children", []), target, new_path)
            if result:
                return result
        return None

    return _search(conversations, conv_id, []) or []


def get_all_ancestor_ids(conversations: list, conv_id: str) -> set[str]:
    """Return IDs of all conversations on any root-to-conv_id path.

    For diamond nodes reachable via multiple parents, returns the union of
    all paths — e.g. ``{root, beta1, beta2, final}``.
    """
    result: set[str] = set()

    def _walk(convs: list, ancestors: list[str]) -> bool:
        found = False
        for conv in convs:
            cid = conv.get("id", "")
            current = ancestors + [cid]
            if cid == conv_id:
                result.update(current)
                found = True
            child_found = _walk(conv.get("children", []), current)
            if child_found:
                result.update(current)
                found = True
        return found

    _walk(conversations, [])
    return result


def get_context_messages(conversations: list, conv_id: str) -> list:
    """Get all messages in the ancestor chain up to and including conv_id.

    Used to build the upstream context window for an LLM call.
    Returns flat list of messages in conversation order.
    """
    chain = get_ancestor_chain(conversations, conv_id)
    all_msgs = []
    for conv in chain:
        all_msgs.extend(conv.get("messages", []))
    return all_msgs


# ---------------------------------------------------------------------------
# Tree mutation
# ---------------------------------------------------------------------------

def remove_conversation(conversations: list, conv_id: str) -> bool:
    """Remove a conversation and all its children from the tree. Returns True if found."""
    for i, conv in enumerate(conversations):
        if conv.get("id") == conv_id:
            conversations.pop(i)
            return True
        if remove_conversation(conv.get("children", []), conv_id):
            return True
    return False


def all_conversation_ids(conversations: list) -> set:
    """Collect all conversation IDs in the tree."""
    ids = set()
    for conv in conversations:
        ids.add(conv.get("id", ""))
        ids.update(all_conversation_ids(conv.get("children", [])))
    return ids


def all_message_ids(conversations: list) -> set:
    """Collect all message IDs across all conversations."""
    ids = set()
    for conv in conversations:
        for msg in conv.get("messages", []):
            ids.add(msg.get("id", ""))
        ids.update(all_message_ids(conv.get("children", [])))
    return ids


def flatten_conversations(conversations: list) -> list[tuple[dict, str | None]]:
    """Flatten tree into list of ``(conv_dict_without_children, parent_id)`` tuples."""
    result: list[tuple[dict, str | None]] = []

    def _walk(conv_list: list, parent_id: str | None = None) -> None:
        for conv in conv_list:
            flat = {k: v for k, v in conv.items() if k != "children"}
            result.append((flat, parent_id))
            _walk(conv.get("children", []), conv.get("id"))

    _walk(conversations)
    return result


# ---------------------------------------------------------------------------
# Selection flags
# ---------------------------------------------------------------------------

def collect_selected_flags(conversations: list) -> tuple[list[list[dict]], list[tuple[list[dict], dict]]]:
    """Collect explicitly selected conversations and messages from the tree.

    Diamond nodes (same conversation ID under multiple parents) may all carry
    ``selected=True`` from :func:`apply_selection_flags`.  We deduplicate by
    terminal conversation ID so that only the first path to each selected node
    is returned, preventing false "multiple selected paths" errors.
    """
    selected_conversations: list[list[dict]] = []
    seen_conv_ids: set[str] = set()
    selected_messages: list[tuple[list[dict], dict]] = []
    seen_msg_ids: set[str] = set()
    for conv, path in iter_conversation_paths(conversations):
        if conv.get("selected") is True:
            cid = conv.get("id", "")
            if cid not in seen_conv_ids:
                seen_conv_ids.add(cid)
                selected_conversations.append(path)
        for msg in conv.get("messages", []):
            if msg.get("selected") is True:
                mid = msg.get("id", "")
                if mid not in seen_msg_ids:
                    seen_msg_ids.add(mid)
                    selected_messages.append((path, msg))
    return selected_conversations, selected_messages


def apply_selection_flags(
    conversations: list,
    selected_conversation_id: str | None,
    selected_message_id: str | None,
) -> None:
    """Rewrite selected flags so conversations on all paths to the node are marked.

    For diamond/DAG nodes, marks the union of all root-to-target paths rather
    than a single DFS path.
    """
    for conv, path in iter_conversation_paths(conversations):
        conv.pop("selected", None)
        for msg in conv.get("messages", []):
            msg.pop("selected", None)

    if not selected_conversation_id:
        return

    selected_ids = get_all_ancestor_ids(conversations, selected_conversation_id)
    for conv, path in iter_conversation_paths(conversations):
        if conv.get("id") in selected_ids:
            conv["selected"] = True
        if conv.get("id") == selected_conversation_id and selected_message_id:
            for msg in conv.get("messages", []):
                if msg.get("id") == selected_message_id:
                    msg["selected"] = True
                    break


def resolve_selection(
    conversations: list,
    selected_hint: Any,
    selected_message_hint: Any,
    *,
    strict: bool,
) -> tuple[str | None, str | None]:
    """Resolve conversation/message selection from explicit flags and legacy hints."""
    selected_hint_id = str(selected_hint).strip() if isinstance(selected_hint, str) and selected_hint.strip() else None
    selected_message_hint_id = (
        str(selected_message_hint).strip()
        if isinstance(selected_message_hint, str) and selected_message_hint.strip()
        else None
    )

    conv_paths, msg_refs = collect_selected_flags(conversations)
    if strict and len(msg_refs) > 1:
        raise StateValidationError("Selected messages must be a singleton")

    chosen_msg_path: list[dict] | None = None
    chosen_msg_id: str | None = None
    if msg_refs:
        chosen_msg_path, chosen_msg = msg_refs[0]
        chosen_msg_id = chosen_msg.get("id")
        if strict and selected_message_hint_id and selected_message_hint_id != chosen_msg_id:
            raise StateValidationError("selected_message conflicts with message selected=\"true\"")
    elif selected_message_hint_id:
        for conv, _path in iter_conversation_paths(conversations):
            for msg in conv.get("messages", []):
                if msg.get("id") == selected_message_hint_id:
                    chosen_msg_path = get_ancestor_chain(conversations, conv.get("id"))
                    chosen_msg_id = selected_message_hint_id
                    break
            if chosen_msg_id:
                break
        if strict and selected_message_hint_id and not chosen_msg_id:
            raise StateValidationError(f"Unknown selected_message: {selected_message_hint_id}")

    selected_conversation_id: str | None = None

    if chosen_msg_path:
        selected_conversation_id = chosen_msg_path[-1].get("id")

    if conv_paths:
        candidate_path = max(conv_paths, key=len)
        candidate_ids = [conv.get("id") for conv in candidate_path]
        terminal_id = candidate_ids[-1]
        # Pre-compute all ancestor IDs for the terminal node so we can
        # recognise diamond paths that legitimately diverge.
        all_ancestors = get_all_ancestor_ids(conversations, terminal_id)

        for path in conv_paths:
            path_ids = [conv.get("id") for conv in path]
            if candidate_ids[:len(path_ids)] != path_ids:
                # Divergent path — allow if every node is a diamond ancestor
                # of the terminal (e.g. beta2 in a vote diamond).
                if all(pid in all_ancestors for pid in path_ids):
                    continue
                if strict:
                    raise StateValidationError("Selected conversations must form one root-to-node path")
                candidate_path = path
                candidate_ids = path_ids
                break
        explicit_selected_ids = {path[-1].get("id") for path in conv_paths}
        # For diamonds, explicit_selected_ids includes nodes from multiple
        # paths — only error if extra IDs are NOT diamond ancestors.
        if strict:
            non_ancestor_ids = explicit_selected_ids - all_ancestors
            if non_ancestor_ids:
                raise StateValidationError("Selected conversations must mark every node on the selected path")
        if selected_conversation_id and selected_conversation_id != candidate_ids[-1]:
            if strict:
                raise StateValidationError("Selected message must belong to the terminal selected conversation")
        else:
            selected_conversation_id = candidate_ids[-1]

    if selected_hint_id:
        hint_path = get_ancestor_chain(conversations, selected_hint_id)
        if strict and not hint_path:
            raise StateValidationError(f"Unknown selected_conversation: {selected_hint_id}")
        if hint_path:
            if selected_conversation_id and selected_conversation_id != selected_hint_id:
                if strict:
                    raise StateValidationError("selected_conversation conflicts with selected conversation path")
            else:
                selected_conversation_id = selected_hint_id

    if selected_conversation_id:
        chain = get_ancestor_chain(conversations, selected_conversation_id)
        if strict and not chain:
            raise StateValidationError(f"Unknown selected_conversation: {selected_conversation_id}")
        if chosen_msg_id and chain and chosen_msg_path:
            chosen_ids = [conv.get("id") for conv in chosen_msg_path]
            chain_ids = [conv.get("id") for conv in chain]
            if strict and chosen_ids != chain_ids:
                raise StateValidationError("Selected message must lie on the selected conversation path")
    elif chosen_msg_id:
        selected_conversation_id = chosen_msg_path[-1].get("id") if chosen_msg_path else None

    return selected_conversation_id, chosen_msg_id
