#!/usr/bin/env python3
"""Live testpoint: create a root conversation and one child branch.

Assumes WikiOracle and NanoChat are already running, e.g. via:

    make up

The script:
1. Saves the current server state.
2. Resets the server to an empty session.
3. Creates one new root conversation.
4. Branches one child conversation from that root.
5. Verifies both conversations exist with the expected structure.
6. Restores the original server state.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project / "bin"))

from state import find_conversation


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-s", "--server",
        default="https://127.0.0.1:8888",
        help="WikiOracle server URL (default: https://127.0.0.1:8888)",
    )
    parser.add_argument(
        "-k", "--insecure",
        action="store_true",
        help="Skip TLS verification",
    )
    parser.add_argument(
        "-t", "--token",
        default=None,
        help="Optional API bearer token",
    )
    parser.add_argument(
        "--provider",
        default="wikioracle",
        help="Provider to use for chat requests (default: wikioracle)",
    )
    parser.add_argument(
        "--root-text",
        default="Create the root conversation for the root/child testpoint.",
        help="Prompt used to create the root conversation",
    )
    parser.add_argument(
        "--child-text",
        default="Create the child conversation for the root/child testpoint.",
        help="Prompt used to create the child conversation",
    )
    return parser.parse_args()


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Requested-With": "WikiOracle",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _url(server: str, path: str) -> str:
    return f"{server.rstrip('/')}{path}"


def _get_json(server: str, path: str, *, verify: bool, token: str | None) -> dict:
    context = None if verify else ssl._create_unverified_context()
    request = urllib.request.Request(
        _url(server, path),
        headers=_headers(token),
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(
    server: str,
    path: str,
    body: dict,
    *,
    verify: bool,
    token: str | None,
) -> dict:
    context = None if verify else ssl._create_unverified_context()
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        _url(server, path),
        data=payload,
        headers=_headers(token),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _verify_root_state(state: dict, root_text: str) -> str:
    conversations = state.get("conversations", [])
    _assert(len(conversations) == 1, f"Expected exactly 1 root conversation, got {len(conversations)}")

    root = conversations[0]
    root_id = root.get("id")
    _assert(bool(root_id), "Root conversation is missing an id")
    _assert(root.get("parentId") in (None, ""), f"Root parentId should be empty, got {root.get('parentId')!r}")
    _assert(len(root.get("messages", [])) == 2, f"Root should have 2 messages, got {len(root.get('messages', []))}")
    _assert(root["messages"][0]["role"] == "user", "Root first message should be from the user")
    _assert(root["messages"][1]["role"] == "assistant", "Root second message should be from the assistant")
    _assert(root_text in root["messages"][0].get("content", ""), "Root user message content mismatch")
    _assert(root.get("children", []) == [], "Fresh root should not have children yet")
    _assert(state.get("selected_conversation") == root_id, "selected_conversation should point to the root after step 1")
    return root_id


def _verify_child_state(state: dict, root_id: str, child_text: str) -> tuple[str, dict, dict]:
    conversations = state.get("conversations", [])
    root = find_conversation(conversations, root_id)
    _assert(root is not None, f"Root conversation {root_id} not found after child branch")

    children = root.get("children", [])
    _assert(len(children) == 1, f"Expected exactly 1 child under root, got {len(children)}")
    child = children[0]
    child_id = child.get("id")
    _assert(bool(child_id), "Child conversation is missing an id")
    _assert(child.get("parentId") == root_id, f"Child parentId should be {root_id}, got {child.get('parentId')!r}")
    _assert(len(child.get("messages", [])) == 2, f"Child should have 2 messages, got {len(child.get('messages', []))}")
    _assert(child["messages"][0]["role"] == "user", "Child first message should be from the user")
    _assert(child["messages"][1]["role"] == "assistant", "Child second message should be from the assistant")
    _assert(child_text in child["messages"][0].get("content", ""), "Child user message content mismatch")
    _assert(state.get("selected_conversation") == child_id, "selected_conversation should point to the child after step 2")
    return child_id, root, child


def main() -> int:
    args = _parse_args()
    verify = not args.insecure

    original_state = _get_json(args.server, "/state", verify=verify, token=args.token)["state"]

    try:
        _post_json(args.server, "/new", {}, verify=verify, token=args.token)

        root_resp = _post_json(
            args.server,
            "/chat",
            {
                "message": args.root_text,
                "config": {"provider": args.provider},
            },
            verify=verify,
            token=args.token,
        )
        _assert(root_resp.get("ok") is True, f"Root chat failed: {root_resp}")

        state_after_root = _get_json(args.server, "/state", verify=verify, token=args.token)["state"]
        root_id = _verify_root_state(state_after_root, args.root_text)

        child_resp = _post_json(
            args.server,
            "/chat",
            {
                "message": args.child_text,
                "branch_from": root_id,
                "config": {"provider": args.provider},
            },
            verify=verify,
            token=args.token,
        )
        _assert(child_resp.get("ok") is True, f"Child chat failed: {child_resp}")

        state_after_child = _get_json(args.server, "/state", verify=verify, token=args.token)["state"]
        child_id, root, child = _verify_child_state(state_after_child, root_id, args.child_text)

        print("Root/child testpoint passed.")
        print(f"  Root : {root_id}  title={root.get('title')!r}")
        print(f"  Child: {child_id}  title={child.get('title')!r}")
        return 0
    finally:
        _post_json(
            args.server,
            "/state",
            original_state,
            verify=verify,
            token=args.token,
        )


if __name__ == "__main__":
    raise SystemExit(main())
