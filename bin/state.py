"""WikiOracle state management: data model, I/O, conversation tree, merge logic.

State data model and persistence:
  - XML serialization and deserialization of conversation state
  - Conversation tree structure and traversal
  - State merging logic for multi-branch conversations
  - Snapshot and session management utilities

The canonical state format is XML ("WikiOracle State").
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from truth import (
    StateValidationError,
    WIKIORACLE_UUID_NS,
    _coerce_timestamp,
    _is_iso8601_utc,
    _normalize_trust_entry,
    _stable_sha256,
    _timestamp_sort_key,
    ensure_xhtml,
    strip_xhtml,
    user_guid,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# State-level constants
# ---------------------------------------------------------------------------
SCHEMA_URL = "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/llm_state.json"
SCHEMA_BASENAME = "llm_state.json"  # Basename accepted when URL host/path vary.
STATE_VERSION = 2  # Current state grammar version.
STATE_SCHEMA_ID = "wikioracle.llm_state"  # Stable schema family identifier.

DEFAULT_OUTPUT = ""  # Default output-format instruction when none is configured.


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
# Message ID helpers
# ---------------------------------------------------------------------------
def _message_fingerprint(message: dict) -> str:
    """Build a stable hash input for message identity derivation."""
    username = str(message.get("username", "")).strip()
    timestamp = str(message.get("time", "")).strip()
    content = ensure_xhtml(message.get("content", ""))
    return _stable_sha256(f"{username}|{timestamp}|{content}")


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


def normalize_conversation(raw: Any, parent_id: str | None = None) -> dict:
    """Normalize a conversation node."""
    item = dict(raw) if isinstance(raw, dict) else {}
    ensure_conversation_id(item)
    msgs = item.get("messages", [])
    if not isinstance(msgs, list):
        msgs = []
    item["messages"] = [_normalize_inner_message(m) for m in msgs]
    # Keep explicit title if provided; otherwise derive from messages
    if not item.get("title"):
        item["title"] = _derive_conversation_title(item["messages"])
    # parentId: use explicit value if already present, otherwise derive from tree
    if "parentId" not in item:
        item["parentId"] = parent_id
    children = item.get("children", [])
    if not isinstance(children, list):
        children = []
    conv_id = item["id"]
    item["children"] = [normalize_conversation(c, parent_id=conv_id) for c in children]
    # Strip legacy flat-format fields
    item.pop("parent", None)
    item.pop("type", None)
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

    # Title (human-readable document name; defaults to "WikiOracle")
    title = state.get("title")
    state["title"] = title.strip() if isinstance(title, str) and title.strip() else "WikiOracle"

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

    # Truth — flat array of truth entries
    # Legacy compat: accept old {"truth": {"trust": [...]}} or new {"truth": [...]}
    raw_truth = state.get("truth", [])
    if isinstance(raw_truth, dict):
        raw_truth = raw_truth.get("trust", [])
    if not isinstance(raw_truth, list):
        if strict:
            raise StateValidationError("State.truth must be an array")
        raw_truth = []
    state["truth"] = [_normalize_trust_entry(v) for v in raw_truth]

    # User GUID — deterministic pseudonymous identity stored at root level.
    # Derived from user.name in config.xml when available; preserved if
    # already present in the state (e.g. round-tripping through XML).
    if not state.get("user_guid"):
        # We can't access config.xml here (truth.py has no config dep),
        # so user_guid is populated later by the pipeline (response.py).
        # If already set on the raw input, preserve it.
        pass

    # Clean up legacy fields
    state.pop("messages", None)
    state.pop("active_path", None)

    return state




def load_state_file(path: Path, *, strict: bool = True, max_bytes: int | None = None,
                    reject_symlinks: bool = False) -> dict:
    """Load state from an ``.xml`` or legacy ``.json`` file.

    Auto-detects format by file extension and content:
      - ``.xml`` → ``xml_to_state()``
      - ``.json`` (legacy monolithic) → ``json.loads()`` → ``ensure_minimal_state()``
      - Content starting with ``<?xml`` or ``<state`` → XML
      - Content starting with ``{`` → legacy JSON
    """
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

    # XML detection: by extension or content
    if path.suffix.lower() == ".xml" or stripped.startswith("<?xml") or stripped.startswith("<state"):
        state = xml_to_state(data)
        return ensure_minimal_state(state, strict=strict)

    # Legacy monolithic JSON
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and ("messages" in obj or "conversations" in obj):
                return ensure_minimal_state(obj, strict=strict)
        except json.JSONDecodeError:
            pass

    return ensure_minimal_state({}, strict=False)


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
# XML I/O  (WikiOracle State format)
# ---------------------------------------------------------------------------

def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Add indentation whitespace to an ElementTree for pretty-printing."""
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def _xml_escape(text: str) -> str:
    """Escape text for safe embedding in XML element text."""
    if not text:
        return ""
    return html.escape(text, quote=False)


def _set_xhtml_content(parent: ET.Element, tag: str, xhtml_str: str) -> None:
    """Add an element with XHTML content.

    XHTML fragments may contain child elements, so we parse them
    and attach as subelements.  If parsing fails, fall back to text.
    """
    el = ET.SubElement(parent, tag)
    if not xhtml_str or not xhtml_str.strip() or xhtml_str.strip() == "<div/>":
        el.text = ""
        return
    try:
        wrapper = ET.fromstring(f"<_w>{xhtml_str}</_w>")
        el.text = wrapper.text or ""
        for child in wrapper:
            el.append(child)
    except ET.ParseError:
        el.text = xhtml_str


def _get_xhtml_content(el: ET.Element) -> str:
    """Extract XHTML content from an element (text + child elements)."""
    if el is None:
        return ""
    parts = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(ET.tostring(child, encoding="unicode", method="xml"))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip() or ""


def _conv_to_xml(conv: dict, parent_el: ET.Element) -> None:
    """Recursively serialize a conversation dict to XML elements."""
    conv_el = ET.SubElement(parent_el, "conversation")
    conv_el.set("id", conv.get("id", ""))
    pid = conv.get("parentId")
    if pid is not None:
        if isinstance(pid, list):
            conv_el.set("parentId", ",".join(pid))
        else:
            conv_el.set("parentId", str(pid))

    title_el = ET.SubElement(conv_el, "title")
    title_el.text = conv.get("title", "(untitled)")

    msgs_el = ET.SubElement(conv_el, "messages")
    for msg in conv.get("messages", []):
        msg_el = ET.SubElement(msgs_el, "message")
        msg_el.set("id", msg.get("id", ""))
        msg_el.set("role", msg.get("role", "user"))
        msg_el.set("username", msg.get("username", "Unknown"))
        msg_el.set("time", msg.get("time", ""))
        _set_xhtml_content(msg_el, "content", msg.get("content", ""))

    children = conv.get("children", [])
    if children:
        children_el = ET.SubElement(conv_el, "children")
        for child_conv in children:
            _conv_to_xml(child_conv, children_el)


def _conv_from_xml(conv_el: ET.Element) -> dict:
    """Recursively deserialize a conversation XML element to dict."""
    conv = {
        "id": conv_el.get("id", ""),
        "title": "",
        "messages": [],
        "children": [],
    }
    pid = conv_el.get("parentId")
    if pid is not None:
        if "," in pid:
            conv["parentId"] = [p.strip() for p in pid.split(",")]
        else:
            conv["parentId"] = pid

    title_el = conv_el.find("title")
    if title_el is not None and title_el.text:
        conv["title"] = title_el.text

    msgs_el = conv_el.find("messages")
    if msgs_el is not None:
        for msg_el in msgs_el.findall("message"):
            content_el = msg_el.find("content")
            msg = {
                "id": msg_el.get("id", ""),
                "role": msg_el.get("role", "user"),
                "username": msg_el.get("username", "Unknown"),
                "time": msg_el.get("time", ""),
                "content": _get_xhtml_content(content_el) if content_el is not None else "",
            }
            conv["messages"].append(msg)

    children_el = conv_el.find("children")
    if children_el is not None:
        for child_el in children_el.findall("conversation"):
            conv["children"].append(_conv_from_xml(child_el))

    return conv


def state_to_xml(state: dict) -> str:
    """Convert a state dict to XML string (WikiOracle State format).

    Conversations nest naturally in XML — no flatten/unflatten needed.
    Truth entries serialize with their XHTML content preserved.
    """
    root = ET.Element("state")

    # -- Header --
    header_el = ET.SubElement(root, "header")

    ver_el = ET.SubElement(header_el, "version")
    ver_el.text = str(state.get("version", STATE_VERSION))

    schema_el = ET.SubElement(header_el, "schema")
    schema_el.text = state.get("schema", SCHEMA_URL)

    time_el = ET.SubElement(header_el, "time")
    time_el.text = state.get("time", utc_now_iso())

    title_el = ET.SubElement(header_el, "title")
    title_el.text = state.get("title", "WikiOracle")

    _set_xhtml_content(header_el, "context", state.get("context", "<div/>"))

    sel = state.get("selected_conversation")
    if sel is not None:
        sel_el = ET.SubElement(header_el, "selected_conversation")
        sel_el.text = str(sel)

    uguid = state.get("user_guid")
    if uguid:
        guid_el = ET.SubElement(header_el, "user_guid")
        guid_el.text = str(uguid)

    output = state.get("output")
    if output:
        output_el = ET.SubElement(header_el, "output")
        output_el.text = str(output)

    # -- Conversations --
    convs_el = ET.SubElement(root, "conversations")
    for conv in state.get("conversations", []):
        _conv_to_xml(conv, convs_el)

    # -- Truth --
    truth_el = ET.SubElement(root, "truth")
    for entry in (state.get("truth") or []):
        entry_el = ET.SubElement(truth_el, "entry")
        entry_el.set("id", str(entry.get("id", "")))
        if entry.get("title"):
            entry_el.set("title", str(entry["title"]))
        trust_val = entry.get("trust")
        if trust_val is not None:
            entry_el.set("trust", str(trust_val))
        if entry.get("time"):
            entry_el.set("time", str(entry["time"]))
        if entry.get("arg1"):
            entry_el.set("arg1", str(entry["arg1"]))
        if entry.get("arg2"):
            entry_el.set("arg2", str(entry["arg2"]))
        _set_xhtml_content(entry_el, "content", entry.get("content", ""))

    _indent_xml(root)
    xml_str = ET.tostring(root, encoding="unicode", method="xml")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}\n'


def xml_to_state(text: str) -> dict:
    """Parse an XML string (WikiOracle State format) into a state dict."""
    state = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time": utc_now_iso(),
        "context": "<div/>",
        "conversations": [],
        "truth": [],
        "selected_conversation": None,
    }

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return state

    if root.tag != "state":
        return state

    # -- Header --
    header_el = root.find("header")
    if header_el is not None:
        ver_el = header_el.find("version")
        if ver_el is not None and ver_el.text:
            try:
                state["version"] = int(ver_el.text)
            except ValueError:
                pass
        schema_el = header_el.find("schema")
        if schema_el is not None and schema_el.text:
            state["schema"] = schema_el.text
        time_el = header_el.find("time")
        if time_el is not None and time_el.text:
            state["time"] = time_el.text
        title_el = header_el.find("title")
        if title_el is not None and title_el.text:
            state["title"] = title_el.text
        context_el = header_el.find("context")
        if context_el is not None:
            state["context"] = _get_xhtml_content(context_el) or "<div/>"
        sel_el = header_el.find("selected_conversation")
        if sel_el is not None and sel_el.text:
            state["selected_conversation"] = sel_el.text
        guid_el = header_el.find("user_guid")
        if guid_el is not None and guid_el.text:
            state["user_guid"] = guid_el.text
        output_el = header_el.find("output")
        if output_el is not None and output_el.text:
            state["output"] = output_el.text.strip()

    # -- Conversations --
    convs_el = root.find("conversations")
    if convs_el is not None:
        for conv_el in convs_el.findall("conversation"):
            state["conversations"].append(_conv_from_xml(conv_el))

    # -- Truth --
    truth_el = root.find("truth")
    if truth_el is not None:
        for entry_el in truth_el.findall("entry"):
            entry = {
                "id": entry_el.get("id", ""),
            }
            if entry_el.get("title"):
                entry["title"] = entry_el.get("title")
            trust_str = entry_el.get("trust")
            if trust_str is not None:
                try:
                    entry["trust"] = float(trust_str)
                except ValueError:
                    entry["trust"] = None
            if entry_el.get("time"):
                entry["time"] = entry_el.get("time")
            if entry_el.get("arg1"):
                entry["arg1"] = entry_el.get("arg1")
            if entry_el.get("arg2"):
                entry["arg2"] = entry_el.get("arg2")
            content_el = entry_el.find("content")
            if content_el is not None:
                entry["content"] = _get_xhtml_content(content_el)
            else:
                entry["content"] = ""
            state["truth"].append(entry)

    return state


def atomic_write_xml(path: Path, state: dict, *, reject_symlinks: bool = False) -> None:
    """Write state to an XML file atomically (WikiOracle State format)."""
    if reject_symlinks and path.exists() and path.is_symlink():
        raise StateValidationError("Refusing to write symlink state file")

    path.parent.mkdir(parents=True, exist_ok=True)
    content = state_to_xml(state)

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
    parent.setdefault("children", []).append(normalize_conversation(new_conv, parent_id=parent_conv_id))
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

    # Merge truth entries
    existing_trust = {}
    for entry in base["truth"]:
        existing_trust[entry["id"]] = entry
    new_trust = []
    for entry in incoming["truth"]:
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
    out["truth"] = _sort_by_timestamp(list(existing_trust.values()))

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
    # Title: incoming wins if base is default
    if incoming.get("title") and (not out.get("title") or out["title"] == "WikiOracle"):
        out["title"] = incoming["title"]
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


