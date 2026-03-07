#!/usr/bin/env python3
"""Launch a detached background process, log output, and write a PID file."""

from __future__ import annotations

import argparse
import os
import subprocess
import ssl
import sys
import time
import urllib.request
from pathlib import Path


def _tail(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _wait_for_url(url: str, timeout: float, interval: float, *, insecure: bool) -> bool:
    deadline = time.monotonic() + timeout
    context = ssl._create_unverified_context() if insecure else None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2, context=context) as response:
                if 200 <= getattr(response, "status", 200) < 400:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True, help="Working directory for the child process.")
    parser.add_argument("--pid-file", required=True, help="Where to write the child PID.")
    parser.add_argument("--log-file", required=True, help="Where stdout/stderr should be appended.")
    parser.add_argument("--wait", type=float, default=1.0, help="Seconds to wait for early-exit detection.")
    parser.add_argument("--ready-url", help="HTTP(S) URL to poll until the service is ready.")
    parser.add_argument("--ready-timeout", type=float, default=45.0, help="Seconds to wait for ready-url.")
    parser.add_argument("--ready-interval", type=float, default=1.0, help="Polling interval for ready-url.")
    parser.add_argument("--ready-insecure", action="store_true", help="Disable TLS verification for ready-url.")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Environment override in KEY=VALUE form. May be repeated.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after '--'.")
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command after '--'")

    env = os.environ.copy()
    for item in args.env:
        if "=" not in item:
            parser.error(f"invalid --env value: {item!r}")
        key, value = item.split("=", 1)
        env[key] = value

    log_path = Path(args.log_file)
    pid_path = Path(args.pid_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "ab", buffering=0) as log_handle:
        proc = subprocess.Popen(
            command,
            cwd=args.cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    pid_path.write_text(f"{proc.pid}\n", encoding="ascii")
    time.sleep(max(args.wait, 0.0))
    ready_failed = False
    if proc.poll() is None:
        if not args.ready_url:
            print(proc.pid)
            return 0
        if _wait_for_url(
            args.ready_url,
            args.ready_timeout,
            args.ready_interval,
            insecure=args.ready_insecure,
        ):
            print(proc.pid)
            return 0
        ready_failed = True

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    pid_path.unlink(missing_ok=True)
    if ready_failed:
        print(f"Process did not become ready at {args.ready_url}", file=sys.stderr)
    else:
        print(f"Process exited early with code {proc.returncode}", file=sys.stderr)
    tail = _tail(log_path)
    if tail:
        print(tail, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
