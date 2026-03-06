#!/usr/bin/env python3
"""Convert ChatGPT/Claude conversation JSON exports to WikiOracle XML format.

Usage::

    python bin/migrate_conversations_to_xml.py                  # convert output/conversations/*.json → all.xml
    python bin/migrate_conversations_to_xml.py --dry-run        # preview without writing
    python bin/migrate_conversations_to_xml.py file1.json ...   # convert specific files
    python bin/migrate_conversations_to_xml.py -o out.xml       # custom output path

With no FILE arguments, processes all ``*.json`` in ``output/conversations/``.
Output is written to ``output/conversations/all.xml`` by default.
Conversations already present (by ID) are skipped for idempotent re-runs.

The output file contains a security canary token that triggers GitHub
push protection, preventing accidental check-in of conversation data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Import WikiOracle utilities from this directory (bin/).
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from state import (  # noqa: E402
    atomic_write_xml,
    ensure_minimal_state,
    find_conversation,
    load_state_file,
)
from truth import WIKIORACLE_UUID_NS, ensure_xhtml, utc_now_iso  # noqa: E402

# ---------------------------------------------------------------------------
# Security canary — a fake GitHub PAT that triggers push protection.
# This is embedded as an XML comment in every output file so that GitHub
# will refuse to accept the file if someone accidentally tries to push it.
# ---------------------------------------------------------------------------
_CANARY_TOKEN = "ghp_DONOTCHECKINTHISFILEINTOGITHUB000000"
_CANARY_COMMENT = (
    f"<!-- SECURITY CANARY — DO NOT REMOVE.\n"
    f"     This token triggers GitHub push protection to prevent\n"
    f"     accidental check-in of conversation data: {_CANARY_TOKEN} -->"
)

# Sentinel root parent used by Claude exports.
_CLAUDE_SENTINEL = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def unix_ms_to_iso(timestamp_ms: int | float) -> str:
    """Convert a Unix-millisecond timestamp to ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)."""
    try:
        dt = datetime.fromtimestamp(int(timestamp_ms) / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OSError):
        return utc_now_iso()


def derive_username(role: str, service_id: str, user_name: str) -> str:
    """Map message role + conversation serviceId to a display username."""
    if role == "user":
        return user_name
    if service_id == "chatgpt":
        return "ChatGPT"
    if service_id == "claude":
        return "Claude"
    return "Assistant"


# Regex to strip ChatGPT's internal citation markup (PUA Unicode characters).
# \ue200...\ue201 wraps citation references like "cite\ue202turn0search3".
# \ue203...\ue204 wraps cited text.  \ue206 is a citation block terminator.
# Other PUA chars (U+E000–U+F8FF) may appear for icons/glyphs.
_RE_CITATION_REF = re.compile(r"[\ue200][^\ue201]*[\ue201]")
_RE_PUA = re.compile(r"[\ue000-\uf8ff]")
_RE_CITE_PLAIN = re.compile(r"\s*\bciteturn\d+\w*\d*\b", re.IGNORECASE)
_RE_DOUBLE_SPACE = re.compile(r"  +")


def _strip_chatgpt_citations(content: str) -> str:
    """Remove ChatGPT PUA citation markers and collapse leftover whitespace."""
    content = _RE_CITATION_REF.sub("", content)   # remove citation refs
    content = _RE_PUA.sub("", content)             # remove remaining PUA chars
    content = _RE_CITE_PLAIN.sub("", content)      # remove plaintext cite markers
    content = _RE_DOUBLE_SPACE.sub(" ", content)   # collapse double spaces
    return content.strip()


def is_tool_artifact(content: str) -> bool:
    """Return True if *content* is empty or looks like a tool-call payload (JSON object)."""
    stripped = content.strip()
    if not stripped:
        return True
    if stripped.startswith("{"):
        try:
            json.loads(stripped)
            return True
        except json.JSONDecodeError:
            pass
    return False


# ---------------------------------------------------------------------------
# Message tree → conversation tree
# ---------------------------------------------------------------------------
def _build_children_map(messages: list) -> dict[str, list[dict]]:
    """Build a mapping of parent_id → [child messages] from the raw message list."""
    children: dict[str, list[dict]] = {}
    for msg in messages:
        parent = msg.get("parent")
        if parent is None or (isinstance(parent, str) and parent.startswith("00000000")):
            parent = None
        key = parent or "__root__"
        children.setdefault(key, []).append(msg)
    return children


def _find_main_path(messages: list, current_message_id: str) -> list[dict]:
    """Walk from *current_message_id* back to root via parent links, return chronological path."""
    by_id = {m["id"]: m for m in messages}
    path: list[dict] = []
    visited: set[str] = set()
    cur = current_message_id

    while cur and cur not in visited:
        visited.add(cur)
        msg = by_id.get(cur)
        if msg is None:
            break
        path.append(msg)
        parent = msg.get("parent")
        if parent is None or (isinstance(parent, str) and parent.startswith("00000000")):
            break
        cur = parent

    path.reverse()
    return path


def _follow_branch(start_msg: dict, children_map: dict[str, list[dict]]) -> list[dict]:
    """Follow a single-child chain from *start_msg* down the tree (longest path for ties)."""
    chain = [start_msg]
    current = start_msg
    while True:
        kids = children_map.get(current["id"], [])
        if not kids:
            break
        # Pick the child with the latest timestamp (approximation of "longest/main" sub-branch).
        best = max(kids, key=lambda m: m.get("timestamp", 0))
        chain.append(best)
        current = best
    return chain


def _collect_branches(
    messages: list,
    main_path_ids: set[str],
    children_map: dict[str, list[dict]],
    root_conv_id: str,
) -> list[dict]:
    """Find all branches off the main path and return WikiOracle conversation records for them."""
    branch_records: list[dict] = []

    for msg in messages:
        if msg["id"] not in main_path_ids:
            continue
        kids = children_map.get(msg["id"], [])
        # Siblings that are NOT on the main path are branch heads.
        for kid in kids:
            if kid["id"] in main_path_ids:
                continue
            branch_chain = _follow_branch(kid, children_map)
            branch_id = str(uuid.uuid5(WIKIORACLE_UUID_NS, f"{msg['id']}|{kid['id']}"))
            branch_records.append({
                "_branch_chain": branch_chain,
                "_branch_id": branch_id,
                "_parent_conv_id": root_conv_id,
            })

    return branch_records


# ---------------------------------------------------------------------------
# Single-message conversion
# ---------------------------------------------------------------------------
def convert_message(
    msg: dict, service_id: str, user_name: str
) -> dict | None:
    """Convert a source message dict to WikiOracle format, or None to skip."""
    role = msg.get("role", "")
    content = msg.get("content", "")

    # Skip tool messages.
    if role == "tool":
        return None
    # Skip assistant messages that are tool-call artifacts (JSON payloads).
    if role == "assistant" and is_tool_artifact(content):
        return None
    if role not in ("user", "assistant"):
        return None

    time_iso = unix_ms_to_iso(msg.get("timestamp")) if msg.get("timestamp") else utc_now_iso()
    username = derive_username(role, service_id, user_name)
    content = _strip_chatgpt_citations(content)
    content_xhtml = ensure_xhtml(content)

    return {
        "id": msg["id"],  # preserve source UUID
        "role": role,
        "username": username,
        "time": time_iso,
        "content": content_xhtml,
    }


# ---------------------------------------------------------------------------
# Whole-conversation conversion
# ---------------------------------------------------------------------------
def convert_conversation(source: dict, user_name: str) -> list[dict]:
    """Convert a source conversation to WikiOracle conversation records.

    Returns a list of conversation records (root + any branch children).
    Returns an empty list if no convertible messages exist.
    """
    source_id = source.get("id", "")
    service_id = source.get("serviceId", "unknown")
    title = source.get("title", "(untitled)")
    current_msg_id = source.get("currentMessage", "")
    raw_messages = source.get("messages", [])

    if not raw_messages:
        return []

    children_map = _build_children_map(raw_messages)

    # Determine main path.
    if current_msg_id:
        main_path = _find_main_path(raw_messages, current_msg_id)
    else:
        # Fallback: use messages in source order.
        main_path = list(raw_messages)

    main_path_ids = {m["id"] for m in main_path}

    # Convert main-path messages.
    converted_main: list[dict] = []
    for msg in main_path:
        cm = convert_message(msg, service_id, user_name)
        if cm is not None:
            converted_main.append(cm)

    if not converted_main:
        return []

    root_record = {
        "type": "conversation",
        "id": source_id,  # preserve source UUID
        "title": title,
        "messages": converted_main,
    }

    records = [root_record]

    # Detect branches and create child conversations.
    branch_infos = _collect_branches(raw_messages, main_path_ids, children_map, source_id)
    for info in branch_infos:
        branch_msgs: list[dict] = []
        for msg in info["_branch_chain"]:
            cm = convert_message(msg, service_id, user_name)
            if cm is not None:
                branch_msgs.append(cm)
        if not branch_msgs:
            continue

        # Derive branch title from first user message, fallback to root title.
        branch_title = title
        first_user = next((m for m in branch_msgs if m["role"] == "user"), None)
        if first_user:
            from truth import strip_xhtml
            branch_title = strip_xhtml(first_user["content"])[:50] or title

        records.append({
            "type": "conversation",
            "id": info["_branch_id"],
            "title": branch_title,
            "parent": info["_parent_conv_id"],
            "messages": branch_msgs,
        })

    return records


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------
def load_existing_ids(path: Path) -> set[str]:
    """Load the set of conversation IDs already present in the output state file."""
    if not path.exists():
        return set()
    state = load_state_file(path, strict=False)
    ids: set[str] = set()

    def _collect(convs):
        for c in convs:
            ids.add(c.get("id", ""))
            _collect(c.get("children", []))

    _collect(state.get("conversations", []))
    return ids


def _inject_canary(path: Path) -> None:
    """Insert the security canary comment into *path* after the XML declaration."""
    text = path.read_text(encoding="utf-8")
    if _CANARY_TOKEN in text:
        return  # already present
    if text.startswith("<?xml"):
        idx = text.index("?>") + 2
        text = text[:idx] + "\n" + _CANARY_COMMENT + text[idx:]
    else:
        text = _CANARY_COMMENT + "\n" + text
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------
def _read_config_username(config_path: Path) -> str | None:
    """Try to read user.name from config.xml.  Returns None if unavailable."""
    xml_path = config_path if config_path.suffix == ".xml" else config_path.parent / "config.xml"
    if xml_path.exists():
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(xml_path)
            name_el = tree.find("user/name")
            if name_el is not None and name_el.text:
                return name_el.text.strip()
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert ChatGPT/Claude JSON exports to WikiOracle XML format.",
    )
    parser.add_argument(
        "files", nargs="*",
        help="JSON files to convert.  If omitted, all *.json in output/conversations/.",
    )
    parser.add_argument(
        "--user", default=None,
        help="Username for user-role messages (default: from config.xml, else 'User').",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without writing.",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output XML file path (default: output/conversations/all.xml).",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    conversations_dir = project_root / "output" / "conversations"

    # Determine username.
    user_name = args.user
    if user_name is None:
        user_name = _read_config_username(project_root / "config.xml") or "User"

    # Determine output path.
    output_path = Path(args.output) if args.output else conversations_dir / "all.xml"

    # Determine input files.
    if args.files:
        input_files = [Path(f) for f in args.files]
    else:
        input_files = sorted(conversations_dir.glob("*.json"))

    if not input_files:
        print("No JSON files found.", file=sys.stderr)
        sys.exit(1)

    # Load or create state.
    if output_path.exists():
        state = load_state_file(output_path, strict=False)
    else:
        state = ensure_minimal_state({}, strict=False)

    # Load existing IDs for deduplication.
    existing_ids = load_existing_ids(output_path)

    # Process files, accumulate conversations.
    converted = 0
    skipped_dup = 0
    skipped_empty = 0
    errors = 0
    branches_total = 0

    for json_path in input_files:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                source = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"ERROR: {json_path.name}: {exc}", file=sys.stderr)
            errors += 1
            continue

        records = convert_conversation(source, user_name)

        if not records:
            skipped_empty += 1
            continue

        root_id = records[0]["id"]
        if root_id in existing_ids:
            skipped_dup += 1
            continue

        for rec in records:
            if args.dry_run:
                kind = "ROOT" if rec.get("parent") is None else "BRANCH"
                print(f"  {kind}: {rec['id']}  {rec.get('title', '')}")
            else:
                conv = {
                    "id": rec["id"],
                    "title": rec.get("title", ""),
                    "messages": rec["messages"],
                    "children": [],
                }
                if "parent" in rec:
                    parent = find_conversation(state["conversations"], rec["parent"])
                    if parent:
                        parent.setdefault("children", []).append(conv)
                    else:
                        state["conversations"].append(conv)
                else:
                    state["conversations"].append(conv)
                existing_ids.add(rec["id"])

        converted += 1
        branches_total += len(records) - 1  # root is not a branch

    # Write once, then inject the security canary.
    if not args.dry_run:
        atomic_write_xml(output_path, state)
        _inject_canary(output_path)

    # Summary.
    print(f"Converted: {converted} conversations ({branches_total} branches)")
    print(f"Skipped (duplicate): {skipped_dup}")
    print(f"Skipped (empty): {skipped_empty}")
    print(f"Errors: {errors}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
