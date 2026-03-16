"""Security utilities for WikiOracle and BasicModel.

Consolidates:
  - Rate limiting (sliding-window, in-process)
  - Prompt injection detection (input guard)
  - Content safety detectors (re-exported from truth.py)
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

# Re-export content safety detectors from truth.py (canonical implementations)
from truth import detect_identifiability, detect_asymmetric_claim  # noqa: F401


# ---------------------------------------------------------------------------
# Rate Limiting — sliding-window counter, keyed by IP
# ---------------------------------------------------------------------------

class RateLimiter:
    """In-process sliding-window rate limiter.

    No external dependencies. Suitable for single-process Flask servers.

    Usage::

        limiter = RateLimiter(default_rpm=120)
        limiter.set_limit("/chat", 30)  # tighter limit for chat endpoint

        @app.before_request
        def check_rate():
            if not limiter.allow(request.remote_addr, request.path):
                return jsonify({"error": "Rate limit exceeded"}), 429
    """

    def __init__(self, default_rpm: int = 120, window_seconds: int = 60):
        self.default_rpm = default_rpm
        self.window = window_seconds
        self._path_limits: dict[str, int] = {}
        self._buckets: dict[str, list[float]] = {}

    def set_limit(self, path_prefix: str, rpm: int) -> None:
        """Set a per-minute limit for requests matching a path prefix."""
        self._path_limits[path_prefix] = rpm

    def _get_limit(self, path: str) -> int:
        """Return the applicable RPM limit for a given path."""
        for prefix, rpm in self._path_limits.items():
            if path.startswith(prefix):
                return rpm
        return self.default_rpm

    def allow(self, ip: str, path: str = "/") -> bool:
        """Return True if the request is within the rate limit."""
        limit = self._get_limit(path)
        if limit <= 0:
            return True
        now = time.monotonic()
        key = f"{ip}:{path}"
        window = self._buckets.setdefault(key, [])
        cutoff = now - self.window
        self._buckets[key] = window = [t for t in window if t > cutoff]
        if len(window) >= limit:
            return False
        window.append(now)
        return True


# ---------------------------------------------------------------------------
# Input Guard — prompt injection detection
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?prior\s+instructions",
        r"disregard\s+(all\s+)?previous",
        r"you\s+are\s+now\s+a",
        r"new\s+instructions?\s*:",
        r"system\s+prompt\s*:",
        r"act\s+as\s+(if\s+)?you\s+are",
        r"pretend\s+(that\s+)?you\s+are",
        r"override\s+(your\s+)?instructions",
        r"forget\s+(all\s+)?(your\s+)?instructions",
        r"reveal\s+(your\s+)?system\s+prompt",
        r"output\s+(your\s+)?system\s+(message|prompt)",
        r"what\s+is\s+your\s+system\s+prompt",
    ]
]

# Base64-encoded instruction blocks (common injection vector)
_BASE64_BLOCK = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

# Excessive control characters (non-printable, non-whitespace)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]{3,}")


def detect_injection(content: str) -> Optional[str]:
    """Detect common prompt injection patterns.

    Returns a reason string if injection is detected, or None if clean.
    """
    if not isinstance(content, str) or not content.strip():
        return None

    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(content)
        if m:
            return f"prompt injection pattern: '{m.group(0)}'"

    # Check for suspiciously long base64 blocks (possible encoded instructions)
    if _BASE64_BLOCK.search(content):
        # Only flag if the block is a significant portion of the input
        b64_matches = _BASE64_BLOCK.findall(content)
        total_b64 = sum(len(m) for m in b64_matches)
        if total_b64 > len(content) * 0.5 and total_b64 > 100:
            return "suspicious base64-encoded content"

    if _CONTROL_CHARS.search(content):
        return "excessive control characters"

    return None


# Configurable guard: when disabled, logs but does not block
_GUARD_ENABLED = os.getenv("WIKIORACLE_INPUT_GUARD", "true").lower() in ("true", "1", "yes")


def guard_input(content: str) -> Optional[str]:
    """Check input for injection. Returns reason if blocked, None if allowed.

    When WIKIORACLE_INPUT_GUARD is false, detection still runs but the
    function returns None (log-only mode). The detection result is stored
    in ``guard_input.last_detection`` for logging.
    """
    reason = detect_injection(content)
    guard_input.last_detection = reason
    if reason and _GUARD_ENABLED:
        return reason
    return None

guard_input.last_detection = None
