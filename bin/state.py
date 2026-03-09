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
    parse_authority_block,
    parse_provider_block,
    _stable_sha256,
    _timestamp_sort_key,
    ensure_xhtml,
    strip_xhtml,
    user_guid,
    utc_now_iso,
)

# Graph algorithms live in graph.py; re-exported here for backward compatibility.
from graph import (  # noqa: F401
    iter_conversation_paths as _iter_conversation_paths,
    collect_selected_flags as _collect_selected_flags,
    apply_selection_flags as _apply_selection_flags,
    resolve_selection as _resolve_selection,
    find_conversation,
    get_ancestor_chain,
    get_all_ancestor_ids,
    get_context_messages,
    remove_conversation,
    all_conversation_ids,
    all_message_ids,
    flatten_conversations,
)


# ---------------------------------------------------------------------------
# State-level constants
# ---------------------------------------------------------------------------
SCHEMA_URL = "https://raw.githubusercontent.com/arborrhythms/WikiOracle/main/data/state.xsd"
SCHEMA_BASENAME = "state.xsd"  # Basename accepted when URL host/path vary.
STATE_VERSION = 2  # Current state grammar version.

DEFAULT_OUTPUT = ""  # Default output-format instruction when none is configured.

TRUTH_TAGS = ("fact", "feeling", "reference", "and", "or", "not", "non", "provider", "authority")
_TRUTH_TAG_SET = frozenset(TRUTH_TAGS)
_TRUTH_METADATA_ATTRS = frozenset({"id", "title", "DoT", "trust", "time", "place", "arg1", "arg2"})


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
    stem = SCHEMA_BASENAME.rsplit(".", 1)[0]  # "state"
    return basename.startswith(stem) and basename.endswith(".xsd")


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
def _coerce_selected_flag(value: Any) -> bool:
    """Coerce XML/JSON-ish selected values to a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"", "0", "false", "no", "off"}:
            return False
    return bool(value)


def _normalize_parent_id(value: Any) -> str | list[str] | None:
    """Normalize parentId to None, one ID string, or a list of IDs."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        raw_parts = value
    else:
        text = str(value).strip()
        if not text:
            return None
        raw_parts = text.split(",")
    parts: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        pid = str(part).strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        parts.append(pid)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return parts



# Selection helpers (_iter_conversation_paths, _collect_selected_flags,
# _apply_selection_flags, _resolve_selection) moved to graph.py.


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
    if _coerce_selected_flag(item.get("selected", False)):
        item["selected"] = True
    else:
        item.pop("selected", None)
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
    item["parentId"] = _normalize_parent_id(item.get("parentId"))
    if _coerce_selected_flag(item.get("selected", False)):
        item["selected"] = True
    else:
        item.pop("selected", None)
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

    # Backward compat: old "time" / "date" fields map to time_creation
    if "time_creation" not in state:
        old_time = state.get("time") or state.get("date")
        if old_time:
            state["time_creation"] = _coerce_timestamp(old_time)
    state.pop("time", None)
    state.pop("date", None)

    tc = state.get("time_creation")
    if strict and tc and not _is_iso8601_utc(tc):
        raise StateValidationError("State.time_creation must be ISO8601 UTC")
    state["time_creation"] = _coerce_timestamp(tc) if tc else utc_now_iso()

    tm = state.get("time_lastModified")
    state["time_lastModified"] = _coerce_timestamp(tm) if tm else state["time_creation"]

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
    selected_conversation, selected_message = _resolve_selection(
        state["conversations"],
        state.get("selected_conversation"),
        state.get("selected_message"),
        strict=strict,
    )
    state["selected_conversation"] = selected_conversation
    state["selected_message"] = selected_message
    _apply_selection_flags(state["conversations"], selected_conversation, selected_message)

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

    # User identity — name + user_id stored in state header.
    # Backward compat: old root-level "user_guid" maps to user.user_id.
    if "user_guid" in state and "user" not in state:
        state["user"] = {"name": "User", "user_id": state["user_guid"]}
    state.pop("user_guid", None)

    user = state.get("user")
    if isinstance(user, dict):
        user.setdefault("name", "User")
        user.setdefault("user_id", "")
    # If no user block, leave absent — populated later by the pipeline.

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


def _find_truth_content_root(content: str) -> ET.Element | None:
    """Return the first recognized truth element inside *content*."""
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        wrapper = ET.fromstring(f"<_w>{content}</_w>")
    except ET.ParseError:
        return None
    for child in wrapper:
        if child.tag in _TRUTH_TAG_SET:
            return child
    return None


def _clone_element_without_metadata(el: ET.Element) -> ET.Element:
    """Deep-copy an XML element and strip envelope metadata attributes."""
    clone = copy.deepcopy(el)
    for attr in list(clone.attrib):
        if attr in _TRUTH_METADATA_ATTRS:
            del clone.attrib[attr]
    return clone


def _element_has_explicit_config(el: ET.Element | None, key: str) -> bool:
    """Return True when a provider/authority config key is present in XML."""
    if el is None:
        return False
    return key in el.attrib or el.find(key) is not None


def _append_text_child(parent: ET.Element, tag: str, value: Any) -> None:
    """Append a simple text child when *value* is non-empty."""
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    child = ET.SubElement(parent, tag)
    child.text = text


def _flatten_text(el: ET.Element | None) -> str:
    """Return all text content under *el*."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _truth_entry_to_xml_element(entry: dict) -> ET.Element:
    """Serialize one internal truth entry dict to a typed XML element."""
    norm = _normalize_trust_entry(entry)
    content_root = _find_truth_content_root(norm.get("content", ""))
    tag = content_root.tag if content_root is not None else "fact"

    if tag == "provider":
        root_el = ET.Element("provider")
        provider_cfg = parse_provider_block(norm.get("content", "")) or {}
        source = content_root
        for key in ("api_url", "api_key", "model", "system"):
            _append_text_child(root_el, key, provider_cfg.get(key, ""))
        if provider_cfg.get("authority_url"):
            authority_el = ET.SubElement(root_el, "authority")
            _append_text_child(authority_el, "url", provider_cfg.get("authority_url"))
        if provider_cfg.get("conversation") is True or _element_has_explicit_config(source, "conversation"):
            _append_text_child(root_el, "conversation", "true" if provider_cfg.get("conversation", False) else "false")
        if provider_cfg.get("timeout") or _element_has_explicit_config(source, "timeout"):
            _append_text_child(root_el, "timeout", provider_cfg.get("timeout", 0))
        if provider_cfg.get("max_tokens") or _element_has_explicit_config(source, "max_tokens"):
            _append_text_child(root_el, "max_tokens", provider_cfg.get("max_tokens", 0))
    elif tag == "authority":
        root_el = ET.Element("authority")
        authority_cfg = parse_authority_block(norm.get("content", "")) or {}
        source = content_root
        _append_text_child(root_el, "url", authority_cfg.get("url", ""))
        if authority_cfg.get("refresh", 3600) != 3600 or _element_has_explicit_config(source, "refresh"):
            _append_text_child(root_el, "refresh", authority_cfg.get("refresh", 3600))
    elif tag == "reference":
        root_el = ET.Element("reference")
        href = ""
        anchor_source = None
        if content_root is not None:
            href = content_root.get("href", "")
            anchor_source = content_root.find("a")
            if anchor_source is not None and anchor_source.get("href"):
                href = anchor_source.get("href", "")
        anchor_el = ET.SubElement(root_el, "a")
        if href:
            anchor_el.set("href", href)
        if anchor_source is not None:
            anchor_el.text = anchor_source.text
            for child in anchor_source:
                anchor_el.append(copy.deepcopy(child))
        else:
            anchor_el.text = _flatten_text(content_root) or href
    else:
        root_el = _clone_element_without_metadata(content_root) if content_root is not None else ET.Element("fact")

    root_el.set("id", str(norm.get("id", "")))
    if norm.get("title"):
        root_el.set("title", str(norm["title"]))
    if norm.get("time"):
        root_el.set("time", str(norm["time"]))
    if norm.get("place"):
        root_el.set("place", str(norm["place"]))
    if tag != "feeling":
        trust_val = norm.get("trust", 0.0)
        root_el.set("DoT", str(trust_val))
    if norm.get("arg1"):
        root_el.set("arg1", str(norm["arg1"]))
    if norm.get("arg2"):
        root_el.set("arg2", str(norm["arg2"]))
    return root_el


def _truth_entry_from_xml_element(el: ET.Element) -> dict:
    """Parse one typed truth XML element into the internal dict shape."""
    entry: dict = {"id": el.get("id", "")}
    if el.get("title"):
        entry["title"] = el.get("title")
    if el.get("time"):
        entry["time"] = el.get("time")
    if el.get("place"):
        entry["place"] = el.get("place")
    dot_str = el.get("DoT")
    if dot_str is None:
        dot_str = el.get("trust")
    if dot_str is not None:
        try:
            entry["trust"] = float(dot_str)
        except ValueError:
            entry["trust"] = None
    if el.get("arg1"):
        entry["arg1"] = el.get("arg1")
    if el.get("arg2"):
        entry["arg2"] = el.get("arg2")

    content_el = _clone_element_without_metadata(el)
    entry["content"] = ET.tostring(content_el, encoding="unicode", method="xml").strip()
    return _normalize_trust_entry(entry)


def _conv_to_xml(conv: dict, parent_el: ET.Element, _seen_ids: set | None = None) -> None:
    """Recursively serialize a conversation dict to XML elements.

    Diamond nodes (same ID under multiple parents) are fully serialized at
    each position, but ``selected="true"`` is only written on the first
    occurrence to keep the selected path unambiguous when re-parsed.
    """
    if _seen_ids is None:
        _seen_ids = set()
    conv_id = conv.get("id", "")
    is_first = conv_id not in _seen_ids
    _seen_ids.add(conv_id)

    conv_el = ET.SubElement(parent_el, "conversation")
    conv_el.set("id", conv_id)
    pid = conv.get("parentId")
    if pid is not None:
        if isinstance(pid, list):
            conv_el.set("parentId", ",".join(pid))
        else:
            conv_el.set("parentId", str(pid))
    if conv.get("selected") is True and is_first:
        conv_el.set("selected", "true")

    title_el = ET.SubElement(conv_el, "title")
    title_el.text = conv.get("title", "(untitled)")

    for msg in conv.get("messages", []):
        msg_el = ET.SubElement(conv_el, "message")
        msg_el.set("id", msg.get("id", ""))
        msg_el.set("role", msg.get("role", "user"))
        msg_el.set("username", msg.get("username", "Unknown"))
        msg_el.set("time", msg.get("time", ""))
        if msg.get("selected") is True and is_first:
            msg_el.set("selected", "true")
        _set_xhtml_content(msg_el, "content", msg.get("content", ""))

    children = conv.get("children", [])
    for child_conv in children:
        _conv_to_xml(child_conv, conv_el, _seen_ids)


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
    if _coerce_selected_flag(conv_el.get("selected", False)):
        conv["selected"] = True

    title_el = conv_el.find("title")
    if title_el is not None and title_el.text:
        conv["title"] = title_el.text

    for child in conv_el:
        if child.tag == "message":
            msg_el = child
            content_el = msg_el.find("content")
            msg = {
                "id": msg_el.get("id", ""),
                "role": msg_el.get("role", "user"),
                "username": msg_el.get("username", "Unknown"),
                "time": msg_el.get("time", ""),
                "content": _get_xhtml_content(content_el) if content_el is not None else "",
            }
            if _coerce_selected_flag(msg_el.get("selected", False)):
                msg["selected"] = True
            conv["messages"].append(msg)
        elif child.tag == "conversation":
            conv["children"].append(_conv_from_xml(child))

    return conv


def state_to_xml(state: dict) -> str:
    """Convert a state dict to XML string (WikiOracle State format).

    Conversations nest naturally in XML — no flatten/unflatten needed.
    Truth entries serialize as typed XML elements with envelope metadata
    stored on the truth element itself.
    """
    state = ensure_minimal_state(state, strict=False)
    root = ET.Element("state")

    # -- Header --
    header_el = ET.SubElement(root, "header")

    ver_el = ET.SubElement(header_el, "version")
    ver_el.text = str(state.get("version", STATE_VERSION))

    schema_el = ET.SubElement(header_el, "schema")
    schema_el.text = state.get("schema", SCHEMA_URL)

    tc_el = ET.SubElement(header_el, "time_creation")
    tc_el.text = state.get("time_creation", utc_now_iso())

    tm_el = ET.SubElement(header_el, "time_lastModified")
    tm_el.text = utc_now_iso()

    title_el = ET.SubElement(header_el, "title")
    title_el.text = state.get("title", "WikiOracle")

    _set_xhtml_content(header_el, "context", state.get("context", "<div/>"))

    user_data = state.get("user")
    if isinstance(user_data, dict) and (user_data.get("name") or user_data.get("user_id")):
        user_el = ET.SubElement(header_el, "user")
        name_el = ET.SubElement(user_el, "name")
        name_el.text = user_data.get("name", "User")
        uid_el = ET.SubElement(user_el, "user_id")
        uid_el.text = str(user_data.get("user_id", ""))

    output = state.get("output")
    if output:
        output_el = ET.SubElement(header_el, "output")
        output_el.text = str(output)

    # -- Conversations --
    for conv in state.get("conversations", []):
        _conv_to_xml(conv, root)

    # -- Truth --
    truth_entries = state.get("truth") or []
    if truth_entries:
        truth_el = ET.SubElement(root, "truth")
        for entry in truth_entries:
            truth_el.append(_truth_entry_to_xml_element(entry))

    _indent_xml(root)
    xml_str = ET.tostring(root, encoding="unicode", method="xml")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}\n'


def xml_to_state(text: str) -> dict:
    """Parse an XML string (WikiOracle State format) into a state dict."""
    state = {
        "version": STATE_VERSION,
        "schema": SCHEMA_URL,
        "time_creation": utc_now_iso(),
        "time_lastModified": utc_now_iso(),
        "title": "WikiOracle",
        "context": "<div/>",
        "conversations": [],
        "truth": [],
        "selected_conversation": None,
        "selected_message": None,
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
        tc_el = header_el.find("time_creation")
        if tc_el is not None and tc_el.text:
            state["time_creation"] = tc_el.text
        tm_el = header_el.find("time_lastModified")
        if tm_el is not None and tm_el.text:
            state["time_lastModified"] = tm_el.text
        # Backward compat: old <time> maps to time_creation
        if tc_el is None:
            old_time_el = header_el.find("time")
            if old_time_el is not None and old_time_el.text:
                state["time_creation"] = old_time_el.text
                if tm_el is None:
                    state["time_lastModified"] = old_time_el.text
        title_el = header_el.find("title")
        if title_el is not None and title_el.text:
            state["title"] = title_el.text
        context_el = header_el.find("context")
        if context_el is not None:
            state["context"] = _get_xhtml_content(context_el) or "<div/>"
        sel_el = header_el.find("selected_conversation")
        if sel_el is not None and sel_el.text:
            state["selected_conversation"] = sel_el.text
        # New format: <user><name>...</name><user_id>...</user_id></user>
        user_el = header_el.find("user")
        if user_el is not None:
            user_name_el = user_el.find("name")
            user_id_el = user_el.find("user_id")
            state["user"] = {
                "name": user_name_el.text if user_name_el is not None and user_name_el.text else "User",
                "user_id": user_id_el.text if user_id_el is not None and user_id_el.text else "",
            }
        else:
            # Backward compat: old <user_guid> maps to user.user_id
            guid_el = header_el.find("user_guid")
            if guid_el is not None and guid_el.text:
                state["user"] = {"name": "User", "user_id": guid_el.text}
        output_el = header_el.find("output")
        if output_el is not None and output_el.text:
            state["output"] = output_el.text.strip()

    # -- Conversations --
    for conv_el in root.findall("conversation"):
        state["conversations"].append(_conv_from_xml(conv_el))

    # -- Truth --
    truth_el = root.find("truth")
    if truth_el is not None:
        for child in truth_el:
            if child.tag in _TRUTH_TAG_SET:
                state["truth"].append(_truth_entry_from_xml_element(child))

    return ensure_minimal_state(state, strict=False)


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
# Conversation tree utilities (moved to graph.py, re-exported above)
# ---------------------------------------------------------------------------

def add_message_to_conversation(conversations: list, conv_id: str, message: dict) -> bool:
    """Append a message to a conversation's messages array. Returns True if found."""
    conv = find_conversation(conversations, conv_id)
    if conv is None:
        return False
    messages = conv.setdefault("messages", [])
    was_empty = len(messages) == 0
    normalized = _normalize_inner_message(message)
    messages.append(normalized)
    if (
        was_empty
        and normalized.get("role") == "user"
        and not str(conv.get("title", "")).strip()
    ):
        conv["title"] = _derive_conversation_title(messages)
    return True


def add_child_conversation(conversations: list, parent_conv_id: str, new_conv: dict) -> bool:
    """Add a new child conversation under the given parent. Returns True if found."""
    parent = find_conversation(conversations, parent_conv_id)
    if parent is None:
        return False
    parent.setdefault("children", []).append(normalize_conversation(new_conv, parent_id=parent_conv_id))
    return True


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


_flatten_all_conversations = flatten_conversations


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
    out["time_lastModified"] = utc_now_iso()

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
