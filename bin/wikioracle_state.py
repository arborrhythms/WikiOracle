#!/usr/bin/env python3
"""State and merge utilities for WikiOracle local state files (JSONL format).

v2 grammar:  Dialogue → Conversation*,  Conversation → (Query|Response)* + Conversation*

llm.jsonl is a line-delimited JSON file where:
  Line 1: header  {"type":"header","version":2,...}
  Line N: record  {"type":"conversation"|"trust", ...}

Conversations form a tree via parent references in JSONL; in memory they are nested.
Messages within a conversation are an ordered array (no parent_id).
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_URL_V2 = "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/spec/llm_state_v2.json"
SCHEMA_URL_V1 = "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/spec/llm_state_v1.json"
SCHEMA_URL = SCHEMA_URL_V2
SCHEMA_BASENAME = "llm_state_v2.json"
STATE_VERSION = 2
STATE_SCHEMA_ID = "wikioracle.llm_state"


class StateValidationError(ValueError):
    """Raised when state payload shape is incompatible with expectations."""


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_iso8601_utc(timestamp: Any) -> bool:
    if not isinstance(timestamp, str):
        return False
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def _coerce_timestamp(value: Any) -> str:
    if _is_iso8601_utc(value):
        return str(value)
    return utc_now_iso()


def _timestamp_sort_key(timestamp: str) -> tuple:
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return (int(dt.replace(tzinfo=timezone.utc).timestamp()), timestamp)
    except ValueError:
        return (0, "")


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def schema_url_matches(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value in (SCHEMA_URL_V2, SCHEMA_URL_V1):
        return True
    basename = value.split("?")[0].split("#")[0].rsplit("/", 1)[-1]
    return basename in ("llm_state_v1.json", "llm_state_v2.json")


# ---------------------------------------------------------------------------
# XHTML helpers
# ---------------------------------------------------------------------------
def canonicalize_xhtml(fragment: Any) -> str:
    if not isinstance(fragment, str) or not fragment.strip():
        return "<div/>"
    candidate = fragment.strip()
    wrapped = f"<root>{candidate}</root>"
    try:
        root = ET.fromstring(wrapped)
        parts = []
        if root.text:
            parts.append(root.text)
        for child in list(root):
            parts.append(ET.tostring(child, encoding="unicode"))
        rendered = "".join(parts).strip()
        if not rendered:
            return "<div/>"
        if not list(root) and root.text:
            return f"<p>{html.escape(root.text)}</p>"
        return rendered
    except ET.ParseError:
        return f"<p>{html.escape(candidate)}</p>"


def ensure_xhtml(fragment: Any) -> str:
    return canonicalize_xhtml(fragment)


def strip_xhtml(content: str) -> str:
    return re.sub(r"<[^>]+>", "", content).strip()


# ---------------------------------------------------------------------------
# Hashing / ID helpers
# ---------------------------------------------------------------------------
def _stable_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _message_fingerprint(message: dict) -> str:
    username = str(message.get("username", "")).strip()
    timestamp = str(message.get("timestamp", "")).strip()
    content = canonicalize_xhtml(message.get("content", ""))
    return _stable_sha256(f"{username}|{timestamp}|{content}")


def _trust_fingerprint(entry: dict) -> str:
    title = str(entry.get("title", "")).strip()
    timestamp = str(entry.get("timestamp", "")).strip()
    certainty = str(entry.get("certainty", "")).strip()
    content = canonicalize_xhtml(entry.get("content", ""))
    return _stable_sha256(f"{title}|{timestamp}|{certainty}|{content}")


def ensure_message_id(message: dict) -> str:
    msg_id = str(message.get("id", "")).strip()
    if msg_id:
        return msg_id
    msg_id = "m_" + _message_fingerprint(message)[:16]
    message["id"] = msg_id
    return msg_id


def ensure_conversation_id(conv: dict) -> str:
    cid = str(conv.get("id", "")).strip()
    if cid:
        return cid
    # Derive from first message or title
    title = str(conv.get("title", "")).strip()
    msgs = conv.get("messages", [])
    seed = title
    if msgs:
        seed += "|" + str(msgs[0].get("id", "")) + "|" + str(msgs[0].get("timestamp", ""))
    cid = "c_" + _stable_sha256(seed)[:16]
    conv["id"] = cid
    return cid


def ensure_trust_id(entry: dict) -> str:
    trust_id = str(entry.get("id", "")).strip()
    if trust_id:
        return trust_id
    trust_id = "t_" + _trust_fingerprint(entry)[:16]
    entry["id"] = trust_id
    return trust_id


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _normalize_inner_message(raw: Any) -> dict:
    """Normalize a message inside a conversation (no parent_id, has role)."""
    item = dict(raw) if isinstance(raw, dict) else {}
    ensure_message_id(item)
    item["username"] = str(item.get("username", "Unknown"))
    item["timestamp"] = _coerce_timestamp(item.get("timestamp"))
    item["content"] = ensure_xhtml(item.get("content", ""))
    # Determine role from username if not set
    role = item.get("role", "")
    if role not in ("user", "assistant"):
        username = item["username"].lower()
        if any(kw in username for kw in ["llm", "oracle", "nanochat", "claude", "gpt", "anthropic"]):
            role = "assistant"
        else:
            role = "user"
    item["role"] = role
    # Strip legacy fields
    for key in ("parent_id", "type", "title"):
        item.pop(key, None)
    return item


def _normalize_conversation(raw: Any) -> dict:
    """Normalize a conversation node."""
    item = dict(raw) if isinstance(raw, dict) else {}
    ensure_conversation_id(item)
    item["title"] = str(item.get("title", "(untitled)"))
    msgs = item.get("messages", [])
    if not isinstance(msgs, list):
        msgs = []
    item["messages"] = [_normalize_inner_message(m) for m in msgs]
    children = item.get("children", [])
    if not isinstance(children, list):
        children = []
    item["children"] = [_normalize_conversation(c) for c in children]
    # Strip JSONL-only fields
    item.pop("parent", None)
    item.pop("type", None)
    return item


def _normalize_trust_entry(raw: Any) -> dict:
    item = dict(raw) if isinstance(raw, dict) else {}
    item["type"] = "trust"
    item["title"] = str(item.get("title", "Trust entry"))
    item["timestamp"] = _coerce_timestamp(item.get("timestamp"))
    certainty = item.get("certainty", 0.0)
    try:
        certainty = float(certainty)
    except (TypeError, ValueError):
        certainty = 0.0
    item["certainty"] = min(1.0, max(0.0, certainty))
    item["content"] = ensure_xhtml(item.get("content", ""))
    ensure_trust_id(item)
    return item


def _normalize_retrieval_prefs(raw: Any) -> dict:
    return dict(raw) if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# V1 → V2 migration
# ---------------------------------------------------------------------------
def migrate_v1_to_v2(v1_state: dict) -> dict:
    """Convert a v1 state (flat messages with parent_id) to v2 (conversation tree).

    Uses the same grouping algorithm as the client's groupConversations().
    """
    messages = v1_state.get("messages", [])
    if not messages:
        v2 = copy.deepcopy(v1_state)
        v2["version"] = STATE_VERSION
        v2["schema"] = SCHEMA_URL
        v2["conversations"] = []
        v2.pop("messages", None)
        v2.pop("active_path", None)
        v2["selected_conversation"] = None
        return v2

    # Build graph from parent_id
    by_id: dict = {}
    children: dict = {}
    root_ids: list = []
    ordered = sorted(messages, key=lambda m: (
        _timestamp_sort_key(m.get("timestamp", "")), m.get("id", "")
    ))
    prev_id = None
    for msg in ordered:
        mid = msg.get("id", "")
        by_id[mid] = msg
        pid = msg.get("parent_id", "__MISSING__")
        if pid == "__MISSING__":
            pid = prev_id
        if pid is None:
            root_ids.append(mid)
        else:
            children.setdefault(pid, []).append(mid)
        prev_id = mid

    # Walk chains to group into conversations
    def walk_chain(start_id):
        msgs = []
        cur = start_id
        while cur:
            msg = by_id.get(cur)
            if not msg:
                break
            msgs.append(msg)
            kids = children.get(cur, [])
            if len(kids) == 1:
                cur = kids[0]
            else:
                break
        return msgs

    def build_conv(start_id):
        chain = walk_chain(start_id)
        if not chain:
            return None
        last_msg = chain[-1]
        last_id = last_msg.get("id", "")
        kids = children.get(last_id, [])

        # Determine role for each message
        conv_messages = []
        for m in chain:
            username = m.get("username", "")
            is_assistant = any(kw in username.lower() for kw in
                             ["llm", "oracle", "nanochat", "claude", "gpt", "anthropic"])
            conv_messages.append({
                "id": m["id"],
                "role": "assistant" if is_assistant else "user",
                "username": username,
                "timestamp": m.get("timestamp", ""),
                "content": m.get("content", ""),
            })

        # Title from first user message
        first_user = next((m for m in conv_messages if m["role"] == "user"), None)
        title = ""
        if first_user:
            title = strip_xhtml(first_user["content"])[:50]
        if not title:
            title = strip_xhtml(conv_messages[0]["content"])[:50] if conv_messages else "(untitled)"

        child_convs = [build_conv(kid) for kid in kids]
        child_convs = [c for c in child_convs if c is not None]

        return {
            "id": "c_" + _stable_sha256(chain[0]["id"])[:16],
            "title": title,
            "messages": conv_messages,
            "children": child_convs,
        }

    conversations = [build_conv(rid) for rid in root_ids]
    conversations = [c for c in conversations if c is not None]

    v2 = copy.deepcopy(v1_state)
    v2["version"] = STATE_VERSION
    v2["schema"] = SCHEMA_URL
    v2["conversations"] = conversations
    v2.pop("messages", None)
    v2.pop("active_path", None)
    v2["selected_conversation"] = None
    return v2


# ---------------------------------------------------------------------------
# State as dict (internal canonical form)
# ---------------------------------------------------------------------------
def ensure_minimal_state(raw: Any, *, strict: bool = False) -> dict:
    """Normalize state to v2 shape. Auto-migrates v1."""
    if not isinstance(raw, dict):
        if strict:
            raise StateValidationError("State must be a JSON object")
        raw = {}

    state = copy.deepcopy(raw)

    version = state.get("version", STATE_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = STATE_VERSION

    # Auto-migrate v1 → v2
    if version == 1 or (version != 2 and "messages" in state and "conversations" not in state):
        state = migrate_v1_to_v2(state)
        version = 2

    if strict and version != STATE_VERSION:
        raise StateValidationError(f"Unsupported version: {version}")
    state["version"] = STATE_VERSION

    schema = state.get("schema", SCHEMA_URL)
    if strict and not schema_url_matches(schema):
        raise StateValidationError(f"Unsupported schema URL: {schema}")
    state["schema"] = str(schema) if isinstance(schema, str) and schema else SCHEMA_URL

    date = state.get("date")
    if strict and not _is_iso8601_utc(date):
        raise StateValidationError("State.date must be ISO8601 UTC")
    state["date"] = _coerce_timestamp(date)

    context = state.get("context", "<div/>")
    if strict and not isinstance(context, str):
        raise StateValidationError("State.context must be an XHTML string")
    state["context"] = ensure_xhtml(context)

    # Conversations tree
    convs = state.get("conversations")
    if strict and not isinstance(convs, list):
        raise StateValidationError("State.conversations must be an array")
    if not isinstance(convs, list):
        convs = []
    state["conversations"] = [_normalize_conversation(c) for c in convs]

    state["selected_conversation"] = state.get("selected_conversation", None)

    # Truth
    truth = state.get("truth", {"trust": [], "retrieval_prefs": {}})
    if strict and not isinstance(truth, dict):
        raise StateValidationError("State.truth must be an object")
    if not isinstance(truth, dict):
        truth = {"trust": [], "retrieval_prefs": {}}
    trust = truth.get("trust")
    if not isinstance(trust, list):
        trust = []
    state["truth"] = {
        "trust": [_normalize_trust_entry(v) for v in trust],
        "retrieval_prefs": _normalize_retrieval_prefs(truth.get("retrieval_prefs")),
    }

    # Clean up legacy fields
    state.pop("messages", None)
    state.pop("active_path", None)

    return state


# ---------------------------------------------------------------------------
# JSONL I/O (v2)
# ---------------------------------------------------------------------------
def _flatten_conversations(convs: list, parent_id: str | None = None) -> list:
    """Flatten nested conversations into JSONL records with 'parent' references."""
    records = []
    for conv in convs:
        record = {
            "type": "conversation",
            "id": conv["id"],
            "title": conv.get("title", ""),
            "messages": conv.get("messages", []),
        }
        if parent_id is not None:
            record["parent"] = parent_id
        records.append(record)
        # Recurse into children
        records.extend(_flatten_conversations(conv.get("children", []), parent_id=conv["id"]))
    return records


def _nest_conversations(flat_records: list) -> list:
    """Rebuild conversation tree from flat JSONL records with 'parent' references."""
    by_id: dict = {}
    roots: list = []

    # First pass: create all nodes
    for rec in flat_records:
        cid = rec.get("id", "")
        by_id[cid] = {
            "id": cid,
            "title": rec.get("title", ""),
            "messages": rec.get("messages", []),
            "children": [],
        }

    # Second pass: link parents
    for rec in flat_records:
        cid = rec.get("id", "")
        parent = rec.get("parent")
        node = by_id.get(cid)
        if not node:
            continue
        if parent and parent in by_id:
            by_id[parent]["children"].append(node)
        else:
            roots.append(node)

    return roots


def state_to_jsonl(state: dict) -> str:
    """Convert a v2 state dict to JSONL string."""
    lines = []

    header = {
        "type": "header",
        "version": state.get("version", STATE_VERSION),
        "schema": state.get("schema", SCHEMA_URL),
        "date": state.get("date", utc_now_iso()),
        "context": state.get("context", "<div/>"),
        "retrieval_prefs": state.get("truth", {}).get("retrieval_prefs", {}),
    }
    sel = state.get("selected_conversation")
    if sel is not None:
        header["selected_conversation"] = sel
    lines.append(json.dumps(header, ensure_ascii=False))

    # Conversation records (flattened)
    flat_convs = _flatten_conversations(state.get("conversations", []))
    for rec in flat_convs:
        lines.append(json.dumps(rec, ensure_ascii=False))

    # Trust records
    for entry in state.get("truth", {}).get("trust", []):
        record = {k: v for k, v in entry.items()}
        record["type"] = "trust"
        lines.append(json.dumps(record, ensure_ascii=False))

    return "\n".join(lines) + "\n"


def jsonl_to_state(text: str) -> dict:
    """Parse a JSONL string into a state dict (auto-detects v1 vs v2)."""
    state = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "date": utc_now_iso(),
        "context": "<div/>",
        "conversations": [],
        "truth": {"trust": [], "retrieval_prefs": {}},
        "selected_conversation": None,
    }

    conv_records = []
    v1_messages = []
    detected_version = None

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        record_type = obj.get("type", "")

        if record_type == "header":
            detected_version = obj.get("version", 1)
            state["version"] = detected_version
            state["schema"] = obj.get("schema", SCHEMA_URL)
            state["date"] = obj.get("date", state["date"])
            state["context"] = obj.get("context", state["context"])
            state["truth"]["retrieval_prefs"] = obj.get("retrieval_prefs", {})
            if "selected_conversation" in obj:
                state["selected_conversation"] = obj["selected_conversation"]
            # v1 compat
            if "active_path" in obj:
                state["_v1_active_path"] = obj["active_path"]
        elif record_type == "conversation":
            conv_records.append({k: v for k, v in obj.items() if k != "type"})
        elif record_type == "message":
            # v1 message record
            v1_messages.append({k: v for k, v in obj.items() if k != "type"})
        elif record_type == "trust":
            entry = {k: v for k, v in obj.items() if k != "type"}
            state["truth"]["trust"].append(entry)
        elif "messages" in obj and "version" in obj:
            return ensure_minimal_state(obj, strict=False)

    if conv_records:
        # v2: reconstruct tree from flat records
        state["conversations"] = _nest_conversations(conv_records)
    elif v1_messages:
        # v1: store temporarily for migration
        state["messages"] = v1_messages
        state["version"] = 1

    return state


def load_state_file(path: Path, *, strict: bool = True, max_bytes: int | None = None,
                    reject_symlinks: bool = False) -> dict:
    """Load state from a .jsonl (or legacy .json) file. Auto-migrates v1→v2."""
    if reject_symlinks and path.is_symlink():
        raise StateValidationError("State file cannot be a symlink")

    if max_bytes is not None and path.exists() and path.stat().st_size > max_bytes:
        raise StateValidationError(f"State file exceeds MAX_STATE_BYTES ({max_bytes})")

    if not path.exists():
        return ensure_minimal_state({}, strict=False)

    data = path.read_text(encoding="utf-8")
    if not data.strip():
        return ensure_minimal_state({}, strict=False)

    stripped = data.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and ("messages" in obj or "conversations" in obj):
                return ensure_minimal_state(obj, strict=strict)
        except json.JSONDecodeError:
            pass

    state = jsonl_to_state(data)
    return ensure_minimal_state(state, strict=strict)


def atomic_write_jsonl(path: Path, state: dict, *, reject_symlinks: bool = False) -> None:
    """Write state to a .jsonl file atomically."""
    if reject_symlinks and path.exists() and path.is_symlink():
        raise StateValidationError("Refusing to write symlink state file")

    path.parent.mkdir(parents=True, exist_ok=True)
    content = state_to_jsonl(state)

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, str(path))
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write state as monolithic JSON atomically (legacy compat)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, str(path))
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


# ---------------------------------------------------------------------------
# Conversation tree utilities
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


def add_message_to_conversation(conversations: list, conv_id: str, message: dict) -> bool:
    """Append a message to a conversation's messages array. Returns True if found."""
    conv = find_conversation(conversations, conv_id)
    if conv is None:
        return False
    conv.setdefault("messages", []).append(_normalize_inner_message(message))
    return True


def add_child_conversation(conversations: list, parent_conv_id: str, new_conv: dict) -> bool:
    """Add a new child conversation under the given parent. Returns True if found."""
    parent = find_conversation(conversations, parent_conv_id)
    if parent is None:
        return False
    parent.setdefault("children", []).append(_normalize_conversation(new_conv))
    return True


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


# ---------------------------------------------------------------------------
# Merge: collision-safe
# ---------------------------------------------------------------------------
def _resolve_id_collision(desired_id: str, payload: dict, existing: dict, *, prefix: str) -> str:
    if desired_id not in existing:
        return desired_id
    if existing[desired_id] == payload:
        return desired_id
    digest = _stable_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))[:8]
    alt = f"{desired_id}_{digest}"
    if alt not in existing:
        return alt
    i = 1
    while True:
        alt2 = f"{alt}_{i}"
        if alt2 not in existing:
            return alt2
        i += 1


def _flatten_all_conversations(convs: list) -> list:
    """Flatten tree into list of (conv_dict_without_children, parent_id) tuples."""
    result = []
    def _walk(conv_list, parent_id=None):
        for conv in conv_list:
            flat = {k: v for k, v in conv.items() if k != "children"}
            result.append((flat, parent_id))
            _walk(conv.get("children", []), conv.get("id"))
    _walk(convs)
    return result


def _sort_by_timestamp(items: list) -> list:
    return sorted(items, key=lambda x: (_timestamp_sort_key(x.get("timestamp", "")), x.get("id", "")))


# ---------------------------------------------------------------------------
# Context delta extraction
# ---------------------------------------------------------------------------
def extract_context_deltas(conversations: Iterable[dict], limit: int = 12) -> list:
    """Heuristic context-delta extraction from new conversations."""
    deltas: list = []
    patterns = [
        re.compile(r"\b(decision|decid\w*|agreed|policy|rule)\b", re.IGNORECASE),
        re.compile(r"\b(file|path|directory|folder|repo|schema)\b", re.IGNORECASE),
        re.compile(r"\b(todo|task|next step|follow[- ]?up|action)\b", re.IGNORECASE),
        re.compile(r"\b(constraint|must|should|required|forbidden|do not)\b", re.IGNORECASE),
    ]
    for conv in conversations:
        for msg in conv.get("messages", []):
            text = re.sub(r"<[^>]+>", " ", str(msg.get("content", "")))
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            if any(p.search(text) for p in patterns):
                speaker = str(msg.get("username", "Unknown")).strip() or "Unknown"
                summary = text[:240].rstrip()
                deltas.append(f"{speaker}: {summary}")
                if len(deltas) >= limit:
                    return deltas
    return deltas


def build_context_draft(base_context: str, deltas: list, max_context_chars: int = 8000) -> str:
    base = ensure_xhtml(base_context)
    if not deltas:
        return base
    now = utc_now_iso()
    escaped_items = "".join(f"<li>{html.escape(item)}</li>" for item in deltas)
    appendix = (
        "<div>"
        f"<h4>Merged Session Deltas ({now})</h4>"
        "<p>Auto-generated from newly imported conversations; review and curate as needed.</p>"
        f"<ul>{escaped_items}</ul>"
        "</div>"
    )
    draft = f"<div>{base}{appendix}</div>"
    if len(draft) > max_context_chars:
        return draft[:max_context_chars]
    return draft


# ---------------------------------------------------------------------------
# Main merge function
# ---------------------------------------------------------------------------
def merge_llm_states(
    base_raw: dict,
    incoming_raw: dict,
    *,
    keep_base_context: bool = True,
    context_rewriter: Callable | None = None,
) -> tuple:
    """Merge incoming state into base state. Returns (merged_state, merge_meta)."""
    base = ensure_minimal_state(base_raw, strict=True)
    incoming = ensure_minimal_state(incoming_raw, strict=True)

    # Merge trust entries
    existing_trust = {}
    for entry in base["truth"]["trust"]:
        existing_trust[entry["id"]] = entry
    new_trust = []
    for entry in incoming["truth"]["trust"]:
        resolved_id = _resolve_id_collision(entry["id"], entry, existing_trust, prefix="t")
        if resolved_id != entry["id"]:
            entry = dict(entry)
            entry["id"] = resolved_id
        if resolved_id not in existing_trust:
            existing_trust[resolved_id] = entry
            new_trust.append(entry)

    # Merge conversations by ID
    base_conv_ids = all_conversation_ids(base["conversations"])
    new_convs = []
    for flat_conv, parent_id in _flatten_all_conversations(incoming["conversations"]):
        cid = flat_conv.get("id", "")
        if cid not in base_conv_ids:
            new_convs.append(flat_conv)
            base_conv_ids.add(cid)
            # Try to attach to parent
            if parent_id and find_conversation(base["conversations"], parent_id):
                add_child_conversation(base["conversations"], parent_id, flat_conv)
            else:
                base["conversations"].append(_normalize_conversation(flat_conv))

    out = copy.deepcopy(base)
    out["truth"]["trust"] = _sort_by_timestamp(list(existing_trust.values()))

    base_prefs = out["truth"].get("retrieval_prefs") or {}
    incoming_prefs = incoming["truth"].get("retrieval_prefs") or {}
    out["truth"]["retrieval_prefs"] = base_prefs if base_prefs else incoming_prefs

    if keep_base_context:
        new_context = out["context"]
    else:
        new_context = incoming["context"]

    if context_rewriter is not None and new_convs:
        try:
            deltas = extract_context_deltas(new_convs)
            new_context = context_rewriter(new_context, deltas)
        except Exception:
            pass
    out["context"] = ensure_xhtml(new_context)
    out["date"] = utc_now_iso()

    merge_meta = {
        "conversations_added": len(new_convs),
        "trust_added": len(new_trust),
        "new_conversation_ids": [c.get("id", "") for c in new_convs],
        "new_trust_ids": [t["id"] for t in new_trust],
    }
    return out, merge_meta


def merge_many_states(
    base_raw: dict,
    incoming_states: Iterable[dict],
    *,
    keep_base_context: bool = True,
    context_rewriter: Callable | None = None,
) -> tuple:
    current = ensure_minimal_state(base_raw, strict=True)
    history: list = []
    for incoming in incoming_states:
        current, meta = merge_llm_states(
            current, incoming,
            keep_base_context=keep_base_context,
            context_rewriter=context_rewriter,
        )
        history.append(meta)
    return current, history


# ---------------------------------------------------------------------------
# Compat shims for server code that still uses v1 names
# ---------------------------------------------------------------------------
def build_message_graph(messages: list) -> dict:
    """DEPRECATED: v1 compat. Build graph from flat messages with parent_id."""
    by_id: dict = {}
    children: dict = {}
    root_ids: list = []
    ordered = sorted(messages, key=lambda m: (
        _timestamp_sort_key(m.get("timestamp", "")), m.get("id", "")
    ))
    prev_id = None
    for msg in ordered:
        mid = msg.get("id", "")
        by_id[mid] = msg
        pid = msg.get("parent_id", "__MISSING__")
        if pid == "__MISSING__":
            pid = prev_id
        if pid is None:
            root_ids.append(mid)
        else:
            children.setdefault(pid, []).append(mid)
        prev_id = mid
    return {"by_id": by_id, "children": children, "root_ids": root_ids, "all_ids": set(by_id.keys())}


def resolve_cwd(messages: list, active_path: list | None = None) -> list:
    """DEPRECATED: v1 compat."""
    if not messages:
        return []
    graph = build_message_graph(messages)
    if active_path and all(mid in graph["all_ids"] for mid in active_path):
        return list(active_path)
    def _dfs(nid):
        kids = graph["children"].get(nid, [])
        if not kids:
            return [nid]
        longest = []
        for kid in kids:
            p = _dfs(kid)
            if len(p) > len(longest):
                longest = p
        return [nid] + longest
    best = []
    for rid in graph["root_ids"]:
        c = _dfs(rid)
        if len(c) > len(best):
            best = c
    return best


def get_messages_on_path(messages: list, cwd: list) -> list:
    """DEPRECATED: v1 compat."""
    if not cwd:
        return list(messages)
    by_id = {m.get("id"): m for m in messages}
    return [by_id[mid] for mid in cwd if mid in by_id]


def get_branch_points(messages: list, cwd: list) -> dict:
    """DEPRECATED: v1 compat."""
    graph = build_message_graph(messages)
    result = {}
    for mid in cwd:
        kids = graph["children"].get(mid, [])
        if len(kids) > 1:
            result[mid] = kids
    return result


def get_children(messages: list, parent_id: str | None = None) -> list:
    """DEPRECATED: v1 compat."""
    graph = build_message_graph(messages)
    if parent_id is None:
        return list(graph["root_ids"])
    return graph["children"].get(parent_id, [])


# ---------------------------------------------------------------------------
# Provider / Src parsing (unchanged from v1)
# ---------------------------------------------------------------------------
ALLOWED_KEY_DIR = Path.home() / ".wikioracle" / "keys"


def parse_provider_block(content: str) -> dict | None:
    if not isinstance(content, str) or "<provider" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    prov = root.find(".//provider")
    if prov is None:
        return None
    def _text(tag, default=""):
        el = prov.find(tag)
        return (el.text or "").strip() if el is not None else default
    result = {
        "name": _text("name", "unknown"),
        "api_url": _text("api_url"),
        "api_key": _text("api_key"),
        "model": _text("model"),
        "timeout": 0,
        "max_tokens": 0,
    }
    try:
        result["timeout"] = int(_text("timeout", "0"))
    except ValueError:
        result["timeout"] = 0
    try:
        result["max_tokens"] = int(_text("max_tokens", "0"))
    except ValueError:
        result["max_tokens"] = 0
    return result


def parse_src_block(content: str) -> dict | None:
    if not isinstance(content, str) or "<src" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    src = root.find(".//src")
    if src is None:
        return None
    def _text(tag, default=""):
        el = src.find(tag)
        return (el.text or "").strip() if el is not None else default
    return {
        "name": _text("name", "unknown"),
        "path": _text("path"),
        "format": _text("format", "text"),
    }


def resolve_api_key(raw_key: str) -> str:
    if not raw_key or not raw_key.startswith("file://"):
        return raw_key
    rel_path = raw_key[len("file://"):]
    key_path = Path(rel_path).expanduser().resolve()
    allowed = ALLOWED_KEY_DIR.resolve()
    try:
        key_path.relative_to(allowed)
    except ValueError:
        raise StateValidationError(f"API key path outside allowlist: {key_path}")
    raw_path = Path(rel_path).expanduser()
    if raw_path.is_symlink() or key_path.is_symlink():
        raise StateValidationError(f"API key path is a symlink: {raw_path}")
    if ".." in Path(rel_path).parts:
        raise StateValidationError(f"Path traversal in API key path: {rel_path}")
    if not key_path.exists():
        raise StateValidationError(f"API key file not found: {key_path}")
    return key_path.read_text(encoding="utf-8").strip()


def resolve_src_content(src_config: dict) -> str:
    path = src_config.get("path", "")
    if not path:
        return ""
    if path.startswith("file://"):
        rel_path = path[len("file://"):]
        src_path = Path(rel_path).expanduser().resolve()
        allowed = ALLOWED_KEY_DIR.resolve()
        try:
            src_path.relative_to(allowed)
        except ValueError:
            raise StateValidationError(f"Src path outside allowlist: {src_path}")
        raw_path = Path(rel_path).expanduser()
        if raw_path.is_symlink() or src_path.is_symlink():
            raise StateValidationError(f"Src path is a symlink: {raw_path}")
        if ".." in Path(rel_path).parts:
            raise StateValidationError(f"Path traversal in src path: {rel_path}")
        if not src_path.exists():
            raise StateValidationError(f"Src file not found: {src_path}")
        return src_path.read_text(encoding="utf-8")
    return ""


def _provider_sort_key(entry: dict) -> tuple:
    certainty = entry.get("certainty", 0.0)
    ts = entry.get("timestamp", "")
    eid = entry.get("id", "")
    return (-certainty, _timestamp_sort_key(ts)[0] * -1, eid)


def get_provider_entries(trust_entries: list) -> list:
    result = []
    for entry in trust_entries:
        prov = parse_provider_block(entry.get("content", ""))
        if prov is not None:
            result.append((entry, prov))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


def get_src_entries(trust_entries: list) -> list:
    result = []
    for entry in trust_entries:
        src = parse_src_block(entry.get("content", ""))
        if src is not None:
            result.append((entry, src))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


def get_primary_provider(trust_entries: list) -> tuple | None:
    entries = get_provider_entries(trust_entries)
    return entries[0] if entries else None
