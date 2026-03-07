#!/usr/bin/env python3
"""Shared NanoChat lifecycle helpers for integration tests."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import requests

_project = Path(__file__).resolve().parent.parent

DEFAULT_TEST_NANO_PORT = 8198
DEFAULT_STARTUP_TIMEOUT = 45

ENV_NANOCHAT_URL = "WIKIORACLE_TEST_NANOCHAT_URL"
ENV_NANOCHAT_BOOT_ERROR = "WIKIORACLE_TEST_NANOCHAT_BOOT_ERROR"
ENV_NANOCHAT_LOG = "WIKIORACLE_TEST_NANOCHAT_LOG"


def wait_for_server(url: str, timeout: int = DEFAULT_STARTUP_TIMEOUT) -> bool:
    """Poll *url*/docs until it responds or *timeout* expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{url}/docs", timeout=2)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _tail_text(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


class NanoChatServer:
    """Own a local NanoChat server process for tests when needed."""

    def __init__(
        self,
        port: int = DEFAULT_TEST_NANO_PORT,
        *,
        host: str = "127.0.0.1",
        log_path: Path | None = None,
    ):
        self.port = port
        self.host = host
        self.url = f"http://{host}:{port}"
        self.log_path = log_path or (_project / "output" / f"test_nanochat_{port}.log")
        self.pid_name = f".nano_test_{port}.pid"
        self.pid_path = _project / self.pid_name
        self.managed = False
        self.owned = False

    def _run_make(self, target: str) -> subprocess.CompletedProcess[str]:
        cmd = [
            "make",
            target,
            f"NANO_PORT={self.port}",
            f"NANO_HOST={self.host}",
            f"NANO_PID={self.pid_name}",
        ]
        self.log_path.parent.mkdir(exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as log_handle:
            log_handle.write(f"$ {' '.join(cmd)}\n")
            return subprocess.run(
                cmd,
                cwd=str(_project),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

    def start(self, timeout: int = DEFAULT_STARTUP_TIMEOUT) -> str:
        """Start NanoChat via the Makefile unless a healthy server is present."""
        if wait_for_server(self.url, timeout=1):
            return self.url

        self.log_path.write_text("", encoding="utf-8")
        result = self._run_make("nano_start")
        self.managed = result.returncode == 0
        if result.returncode != 0:
            tail = _tail_text(self.log_path)
            message = f"make nano_start failed for {self.url}"
            if tail:
                message = f"{message}\n{tail}"
            raise RuntimeError(message)

        if wait_for_server(self.url, timeout=timeout):
            self.owned = True
            return self.url

        tail = _tail_text(self.log_path)
        self.stop()
        message = f"NanoChat failed to start on {self.url} (no /docs response after {timeout}s)"
        if tail:
            message = f"{message}\n{tail}"
        raise RuntimeError(message)

    def stop(self) -> None:
        """Stop the Makefile-managed server and clean its PID file."""
        if self.managed:
            self._run_make("nano_stop")
        if self.pid_path.exists():
            self.pid_path.unlink()
        self.managed = False
        self.owned = False
