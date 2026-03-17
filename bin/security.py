"""Security utilities for WikiOracle and BasicModel.

Consolidates:
  - Input guard / prompt injection detection (from basicmodel)
  - Rate limiting (sliding-window, in-process)
  - Content safety detectors (re-exported from truth.py)
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

# Import input guard from basicmodel (canonical implementation)
_BM_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "basicmodel", "bin")
if _BM_BIN not in sys.path:
    sys.path.insert(0, _BM_BIN)
from secure import detect_injection, guard_input  # noqa: F401
# Remove basicmodel bin/ to avoid shadowing WikiOracle's parse.py etc.
if _BM_BIN in sys.path:
    sys.path.remove(_BM_BIN)

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
