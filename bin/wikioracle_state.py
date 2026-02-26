#!/usr/bin/env python3
"""State and merge utilities for WikiOracle local state files (JSONL format).

Grammar:  Dialogue → Conversation*,  Conversation → (Query|Response)* + Conversation*

llm.jsonl is a line-delimited JSON file where:
  Line 1: header  {"type":"header","version":2,"schema":"...","time":"..."}
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
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# Stable UUID-5 namespace for deterministic WikiOracle ID generation.
WIKIORACLE_UUID_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

SCHEMA_URL = "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/spec/llm_state.json"
SCHEMA_BASENAME = "llm_state.json"  # Basename accepted when URL host/path vary.
STATE_VERSION = 2  # Current state grammar version.
STATE_SCHEMA_ID = "wikioracle.llm_state"  # Stable schema family identifier.

DEFAULT_OUTPUT = ""  # Default output-format instruction when none is configured.


class StateValidationError(ValueError):
    """Raised when state payload shape is incompatible with expectations."""


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    """Return the current UTC timestamp in canonical ISO-8601 Zulu format."""
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_iso8601_utc(timestamp: Any) -> bool:
    """Validate strict YYYY-MM-DDTHH:MM:SSZ timestamp strings."""
    if not isinstance(timestamp, str):
        return False
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def _coerce_timestamp(value: Any) -> str:
    """Return value when valid; otherwise replace with current UTC timestamp."""
    if _is_iso8601_utc(value):
        return str(value)
    return utc_now_iso()


def _timestamp_sort_key(timestamp: str) -> tuple:
    """Convert timestamp into a deterministic sortable key tuple."""
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return (int(dt.replace(tzinfo=timezone.utc).timestamp()), timestamp)
    except ValueError:
        return (0, "")


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def schema_url_matches(value: Any) -> bool:
    """Accept schema URLs even if query/hash or version suffix differs."""
    if not isinstance(value, str) or not value:
        return False
    if value == SCHEMA_URL:
        return True
    basename = value.split("?")[0].split("#")[0].rsplit("/", 1)[-1]
    if basename == SCHEMA_BASENAME:
        return True
    # Accept versioned variants like llm_state_v2.json
    stem = SCHEMA_BASENAME.rsplit(".", 1)[0]  # "llm_state"
    return basename.startswith(stem) and basename.endswith(".json")


# ---------------------------------------------------------------------------
# XHTML helpers
# ---------------------------------------------------------------------------

# Regex for control characters that are invalid in XML 1.0 and problematic in
# JSON/JavaScript: C0 controls (except HT, LF, CR), DEL, and C1 controls.
_RE_CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)

# ChatGPT citation artifacts that survive PUA-stripping, e.g. ". citeturn0search3".
_RE_CITE_MARKER = re.compile(r"\s*\bciteturn\d+\w*\d*\b", re.IGNORECASE)


def sanitize_unicode(text: str) -> str:
    """Replace or remove problematic Unicode characters for safe XHTML/JSON.

    * U+2028 (Line Separator) and U+2029 (Paragraph Separator) → newline
    * C0 controls (except tab/LF/CR), DEL, C1 controls → removed
    * U+FEFF (BOM / zero-width no-break space) → removed
    * Normalize to NFC for consistent representation
    """
    if not isinstance(text, str):
        return text
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    text = text.replace("\ufeff", "")
    text = _RE_CONTROL.sub("", text)
    text = _RE_CITE_MARKER.sub("", text)
    text = unicodedata.normalize("NFC", text)
    return text


def _escape_plain_text(text: str) -> str:
    """Wrap plain text in a <p> element with proper HTML escaping."""
    return f"<p>{html.escape(text)}</p>"


def _canonicalize_xml_fragment(fragment: str) -> str:
    """Parse an XHTML fragment and return C14N-canonicalized inner content.

    Uses ET.canonicalize (C14N 2.0) for proper XML normalization.
    Raises ET.ParseError if fragment is not well-formed XML.
    """
    wrapped = f"<root>{fragment}</root>"
    canonical = ET.canonicalize(wrapped)
    inner = canonical.removeprefix("<root>").removesuffix("</root>").strip()
    return inner


def _is_plain_text(fragment: str) -> bool:
    """Check whether a fragment parsed as XML is just text (no child elements)."""
    root = ET.fromstring(f"<root>{fragment}</root>")
    return not list(root) and bool(root.text)


def ensure_xhtml(fragment: Any) -> str:
    """Normalize user content into safe, minimal XHTML fragments.

    Pipeline: sanitize_unicode → parse as XML → canonicalize, or escape as
    plain text.  Plain text (no markup) is wrapped in ``<p>`` with escaping.
    """
    if not isinstance(fragment, str) or not fragment.strip():
        return "<div/>"
    cleaned = sanitize_unicode(fragment).strip()
    try:
        if _is_plain_text(cleaned):
            return _escape_plain_text(cleaned)
        return _canonicalize_xml_fragment(cleaned) or "<div/>"
    except ET.ParseError:
        return _escape_plain_text(cleaned)


def strip_xhtml(content: str) -> str:
    """Remove tags and decode entities from XHTML content."""
    return html.unescape(re.sub(r"<[^>]+>", "", content)).strip()


# ---------------------------------------------------------------------------
# Hashing / ID helpers
# ---------------------------------------------------------------------------
def _stable_sha256(text: str) -> str:
    """Return SHA-256 hex digest for deterministic ID generation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _message_fingerprint(message: dict) -> str:
    """Build a stable hash input for message identity derivation."""
    username = str(message.get("username", "")).strip()
    timestamp = str(message.get("time", "")).strip()
    content = ensure_xhtml(message.get("content", ""))
    return _stable_sha256(f"{username}|{timestamp}|{content}")


def _trust_fingerprint(entry: dict) -> str:
    """Build a stable hash input for trust-entry identity derivation."""
    title = str(entry.get("title", "")).strip()
    timestamp = str(entry.get("time", "")).strip()
    certainty = str(entry.get("certainty", "")).strip()
    content = ensure_xhtml(entry.get("content", ""))
    return _stable_sha256(f"{title}|{timestamp}|{certainty}|{content}")


def ensure_message_id(message: dict) -> str:
    """Ensure a message has an ID, deriving a deterministic UUID if missing."""
    msg_id = str(message.get("id", "")).strip()
    if msg_id:
        return msg_id
    msg_id = str(uuid.uuid5(WIKIORACLE_UUID_NS, _message_fingerprint(message)))
    message["id"] = msg_id
    return msg_id


def ensure_conversation_id(conv: dict) -> str:
    """Ensure a conversation has an ID, deriving a deterministic UUID from title/first message."""
    cid = str(conv.get("id", "")).strip()
    if cid:
        return cid
    # Derive from first message or title
    title = str(conv.get("title", "")).strip()
    msgs = conv.get("messages", [])
    seed = title
    if msgs:
        seed += "|" + str(msgs[0].get("id", "")) + "|" + str(msgs[0].get("time", ""))
    cid = str(uuid.uuid5(WIKIORACLE_UUID_NS, seed))
    conv["id"] = cid
    return cid


def ensure_trust_id(entry: dict) -> str:
    """Ensure a trust entry has an ID, deriving a deterministic UUID if missing."""
    trust_id = str(entry.get("id", "")).strip()
    if trust_id:
        return trust_id
    trust_id = str(uuid.uuid5(WIKIORACLE_UUID_NS, _trust_fingerprint(entry)))
    entry["id"] = trust_id
    return trust_id


def _implication_fingerprint(entry: dict) -> str:
    """Build a stable hash input for implication identity derivation."""
    content = ensure_xhtml(entry.get("content", ""))
    return _stable_sha256(f"implication|{content}")


def ensure_implication_id(entry: dict) -> str:
    """Ensure an implication entry has an ID, deriving a deterministic UUID if missing."""
    iid = str(entry.get("id", "")).strip()
    if iid:
        return iid
    iid = str(uuid.uuid5(WIKIORACLE_UUID_NS, _implication_fingerprint(entry)))
    entry["id"] = iid
    return iid


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _normalize_inner_message(raw: Any) -> dict:
    """Normalize a message inside a conversation (no parent_id, has role)."""
    item = dict(raw) if isinstance(raw, dict) else {}
    ensure_message_id(item)
    item["username"] = str(item.get("username", "Unknown"))
    item["time"] = _coerce_timestamp(item.get("time"))
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


def _derive_conversation_title(messages: list) -> str:
    """Derive a title from the first user message, or first message if no user."""
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    if first_user:
        return strip_xhtml(first_user.get("content", ""))[:50] or "(untitled)"
    if messages:
        return strip_xhtml(messages[0].get("content", ""))[:50] or "(untitled)"
    return "(untitled)"


def normalize_conversation(raw: Any) -> dict:
    """Normalize a conversation node."""
    item = dict(raw) if isinstance(raw, dict) else {}
    ensure_conversation_id(item)
    msgs = item.get("messages", [])
    if not isinstance(msgs, list):
        msgs = []
    item["messages"] = [_normalize_inner_message(m) for m in msgs]
    # Title is always derived from messages (never stored in JSONL)
    item["title"] = _derive_conversation_title(item["messages"])
    children = item.get("children", [])
    if not isinstance(children, list):
        children = []
    item["children"] = [normalize_conversation(c) for c in children]
    # Strip JSONL-only fields
    item.pop("parent", None)
    item.pop("type", None)
    return item


def _normalize_trust_entry(raw: Any) -> dict:
    """Normalize a trust record and clamp certainty into [-1.0, 1.0] (Kleene ternary)."""
    item = dict(raw) if isinstance(raw, dict) else {}
    item["type"] = "trust"
    item["title"] = str(item.get("title", "Trust entry"))
    item["time"] = _coerce_timestamp(item.get("time"))
    certainty = item.get("certainty", 0.0)
    try:
        certainty = float(certainty)
    except (TypeError, ValueError):
        certainty = 0.0
    item["certainty"] = min(1.0, max(-1.0, certainty))
    item["content"] = ensure_xhtml(item.get("content", ""))
    # Use i_ prefix for implication entries, t_ for all others
    if "<implication" in item.get("content", ""):
        ensure_implication_id(item)
    else:
        ensure_trust_id(item)
    return item




# ---------------------------------------------------------------------------
# State as dict (internal canonical form)
# ---------------------------------------------------------------------------
def ensure_minimal_state(raw: Any, *, strict: bool = False) -> dict:
    """Normalize state to canonical shape (conversation-based hierarchy)."""
    if not isinstance(raw, dict):
        if strict:
            raise StateValidationError("State must be a JSON object")
        raw = {}

    state = copy.deepcopy(raw)
    state["version"] = STATE_VERSION

    schema = state.get("schema", SCHEMA_URL)
    if strict and not schema_url_matches(schema):
        raise StateValidationError(f"Unsupported schema URL: {schema}")
    state["schema"] = str(schema) if isinstance(schema, str) and schema else SCHEMA_URL

    time_val = state.get("time") or state.get("date")  # compat: accept "date" from old files
    if strict and not _is_iso8601_utc(time_val):
        raise StateValidationError("State.time must be ISO8601 UTC")
    state["time"] = _coerce_timestamp(time_val)
    state.pop("date", None)  # clean up legacy key

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
    state["conversations"] = [normalize_conversation(c) for c in convs]

    state["selected_conversation"] = state.get("selected_conversation", None)

    # Output format instructions (always present; defaults like context)
    output = state.get("output")
    if isinstance(output, str) and output.strip():
        state["output"] = output.strip()
    else:
        state["output"] = DEFAULT_OUTPUT

    # Truth (retrieval_prefs now lives in config.yaml)
    truth = state.get("truth", {"trust": []})
    if strict and not isinstance(truth, dict):
        raise StateValidationError("State.truth must be an object")
    if not isinstance(truth, dict):
        truth = {"trust": []}
    trust = truth.get("trust")
    if not isinstance(trust, list):
        trust = []
    state["truth"] = {
        "trust": [_normalize_trust_entry(v) for v in trust],
    }

    # Clean up legacy fields
    state.pop("messages", None)
    state.pop("active_path", None)

    return state


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------
def _flatten_conversations(convs: list, parent_id: str | None = None) -> list:
    """Flatten nested conversations into JSONL records with 'parent' references."""
    records = []
    for conv in convs:
        record = {
            "type": "conversation",
            "id": conv["id"],
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
    """Convert a state dict to JSONL string."""
    lines = []

    header = {
        "type": "header",
        "version": state.get("version", STATE_VERSION),
        "schema": state.get("schema", SCHEMA_URL),
        "time": state.get("time", utc_now_iso()),
        "context": state.get("context", "<div/>"),
        "output": state.get("output", DEFAULT_OUTPUT),
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
    """Parse a JSONL string into a state dict (conversation-based)."""
    state = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time": utc_now_iso(),
        "context": "<div/>",
        "conversations": [],
        "truth": {"trust": []},
        "selected_conversation": None,
    }

    conv_records = []

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
            state["version"] = obj.get("version", STATE_VERSION)
            state["schema"] = obj.get("schema", SCHEMA_URL)
            state["time"] = obj.get("time") or obj.get("date") or state["time"]
            state["context"] = obj.get("context", state["context"])
            if "selected_conversation" in obj:
                state["selected_conversation"] = obj["selected_conversation"]
            if "output" in obj and isinstance(obj["output"], str) and obj["output"].strip():
                state["output"] = obj["output"].strip()
        elif record_type == "conversation":
            conv_records.append({k: v for k, v in obj.items() if k != "type"})
        elif record_type == "trust":
            entry = {k: v for k, v in obj.items() if k != "type"}
            state["truth"]["trust"].append(entry)
        elif "messages" in obj and "version" in obj:
            return ensure_minimal_state(obj, strict=False)

    if conv_records:
        state["conversations"] = _nest_conversations(conv_records)

    return state


def load_state_file(path: Path, *, strict: bool = True, max_bytes: int | None = None,
                    reject_symlinks: bool = False) -> dict:
    """Load state from a .jsonl (or legacy .json) file."""
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
        """Depth-first search that returns the first root-to-target path found."""
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
    parent.setdefault("children", []).append(normalize_conversation(new_conv))
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
    """Resolve ID collisions deterministically with hash and numeric suffixes."""
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
        """Traverse all conversations and collect flat node/parent tuples."""
        for conv in conv_list:
            flat = {k: v for k, v in conv.items() if k != "children"}
            result.append((flat, parent_id))
            _walk(conv.get("children", []), conv.get("id"))
    _walk(convs)
    return result


def _sort_by_timestamp(items: list) -> list:
    """Sort records by timestamp then ID for deterministic merge output."""
    return sorted(items, key=lambda x: (_timestamp_sort_key(x.get("time", "")), x.get("id", "")))


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
    """Append merge deltas to base context, capped by max_context_chars."""
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
                base["conversations"].append(normalize_conversation(flat_conv))

    out = copy.deepcopy(base)
    out["truth"]["trust"] = _sort_by_timestamp(list(existing_trust.values()))

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
    out["time"] = utc_now_iso()

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
    """Merge multiple incoming states sequentially and return merge history."""
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
# Provider / Src parsing
# ---------------------------------------------------------------------------
ALLOWED_DATA_DIR = Path.home() / ".wikioracle" / "keys"


def parse_provider_block(content: str) -> dict | None:
    """Parse the first <provider> XML block from trust-entry content.

    Supports both child-element style and attribute style:
      Child:  <provider><name>claude</name><api_url>...</api_url></provider>
      Attr:   <provider name="claude" api_url="..." model="..." />
    Attributes take precedence only when the corresponding child element is
    absent or empty, so either style (or a mix) works.
    """
    if not isinstance(content, str) or "<provider" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    prov = root.find(".//provider")
    if prov is None:
        return None
    def _val(tag, default=""):
        """Read from child element first, fall back to XML attribute."""
        el = prov.find(tag)
        text = (el.text or "").strip() if el is not None else ""
        if text:
            return text
        # Fall back to attribute on the <provider> element itself
        return prov.get(tag, default)
    result = {
        "name": _val("name", "unknown"),
        "api_url": _val("api_url"),
        "api_key": _val("api_key"),
        "model": _val("model"),
        "timeout": 0,
        "max_tokens": 0,
    }
    try:
        result["timeout"] = int(_val("timeout", "0"))
    except ValueError:
        result["timeout"] = 0
    try:
        result["max_tokens"] = int(_val("max_tokens", "0"))
    except ValueError:
        result["max_tokens"] = 0
    return result


def parse_src_block(content: str) -> dict | None:
    """Parse the first <src> XML block from trust-entry content."""
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
        """Read and strip child text from src XML nodes."""
        el = src.find(tag)
        return (el.text or "").strip() if el is not None else default
    return {
        "name": _text("name", "unknown"),
        "path": _text("path"),
        "format": _text("format", "text"),
    }


def parse_implication_block(content: str) -> dict | None:
    """Parse the first <implication> XML block from trust-entry content.

    Returns { antecedent, consequent, type } where antecedent and consequent
    are trust entry IDs and type is one of: material, strict, relevant.
    """
    if not isinstance(content, str) or "<implication" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    impl = root.find(".//implication")
    if impl is None:
        return None
    def _text(tag, default=""):
        el = impl.find(tag)
        return (el.text or "").strip() if el is not None else default
    antecedent = _text("antecedent")
    consequent = _text("consequent")
    if not antecedent or not consequent:
        return None
    impl_type = _text("type", "material")
    if impl_type not in ("material", "strict", "relevant"):
        impl_type = "material"
    return {
        "antecedent": antecedent,
        "consequent": consequent,
        "type": impl_type,
    }


def get_implication_entries(trust_entries: list) -> list:
    """Extract trust entries that contain valid <implication> blocks."""
    result = []
    for entry in trust_entries:
        impl = parse_implication_block(entry.get("content", ""))
        if impl is not None:
            result.append((entry, impl))
    return result


# ---------------------------------------------------------------------------
# Derived truth: Kleene implication engine
# ---------------------------------------------------------------------------
def compute_derived_truth(trust_entries: list) -> dict:
    """Evaluate all implication entries and return a derived truth table.

    Returns: { entry_id: derived_certainty } for ALL entries (including those
    unchanged), suitable for overlaying onto the trust table during RAG ranking.

    Uses Strong Kleene material implication on the [-1,+1] certainty scale:
      negation:    not(A) = -A
      disjunction: A or B = max(A, B)
      implication: A -> B = max(-A, B)   (i.e. not-A or B)

    Iterates to fixed point (implications can chain). Max 100 iterations.
    """
    # Build certainty lookup from static values
    certainty = {}
    for entry in trust_entries:
        eid = entry.get("id", "")
        if eid:
            certainty[eid] = entry.get("certainty", 0.0)

    # Extract implications
    implications = []
    for entry in trust_entries:
        impl = parse_implication_block(entry.get("content", ""))
        if impl is not None:
            implications.append(impl)

    if not implications:
        return certainty

    # Only entries that start at 0.0 (ignorance) are derivable.
    # Entries with explicit positive or negative certainty are ground truth
    # and should not be overridden by implication chains.
    derivable = {eid for eid, c in certainty.items() if c == 0.0}

    # Fixed-point iteration
    for _ in range(100):
        changed = False
        for impl in implications:
            ant_id = impl["antecedent"]
            con_id = impl["consequent"]
            if con_id not in derivable:
                continue  # Don't override explicit certainty
            ant_c = certainty.get(ant_id, 0.0)
            con_c = certainty.get(con_id, 0.0)

            # Modus ponens: if antecedent is believed (positive), the
            # consequent's derived certainty is raised to match.
            # Only applies to derivable entries (initial certainty 0.0).
            if ant_c > 0 and con_id in certainty:
                new_con = max(con_c, ant_c)
                if abs(new_con - con_c) > 1e-9:
                    certainty[con_id] = new_con
                    changed = True

        if not changed:
            break

    return certainty


def resolve_api_key(raw_key: str) -> str:
    """Resolve file:// API keys from allowlisted paths; otherwise return raw value."""
    if not raw_key or not raw_key.startswith("file://"):
        return raw_key
    rel_path = raw_key[len("file://"):]
    key_path = Path(rel_path).expanduser().resolve()
    allowed = ALLOWED_DATA_DIR.resolve()
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
    """Load file-backed <src> content from allowlisted paths."""
    path = src_config.get("path", "")
    if not path:
        return ""
    if path.startswith("file://"):
        rel_path = path[len("file://"):]
        src_path = Path(rel_path).expanduser().resolve()
        allowed = ALLOWED_DATA_DIR.resolve()
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
    """Sort trust entries by certainty (desc), timestamp (desc), then ID."""
    certainty = entry.get("certainty", 0.0)
    ts = entry.get("time", "")
    eid = entry.get("id", "")
    return (-certainty, _timestamp_sort_key(ts)[0] * -1, eid)


def get_provider_entries(trust_entries: list) -> list:
    """Extract and rank trust entries that contain valid <provider> blocks."""
    result = []
    for entry in trust_entries:
        prov = parse_provider_block(entry.get("content", ""))
        if prov is not None:
            result.append((entry, prov))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


def get_src_entries(trust_entries: list) -> list:
    """Extract and rank trust entries that contain valid <src> blocks."""
    result = []
    for entry in trust_entries:
        src = parse_src_block(entry.get("content", ""))
        if src is not None:
            result.append((entry, src))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


def get_primary_provider(trust_entries: list) -> tuple | None:
    """Return the highest-ranked provider entry/config pair, if any."""
    entries = get_provider_entries(trust_entries)
    return entries[0] if entries else None
