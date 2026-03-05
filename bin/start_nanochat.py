#!/usr/bin/env python3
"""Launch NanoChat with WikiOracle extensions (online training route).

This is a thin wrapper that:
  1. Imports NanoChat's FastAPI ``app`` (unchanged source).
  2. Mounts WikiOracle's ``POST /train`` route onto it.
  3. Starts uvicorn identically to ``scripts.chat_web.__main__``.

Usage (replaces ``python -m scripts.chat_web``):

    python bin/start_nanochat.py [--num-gpus N] [--port 8000] ...

All command-line arguments are the same as ``scripts.chat_web``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure bin/ is importable (for nanochat_ext)
sys.path.insert(0, str(Path(__file__).resolve().parent))

# NanoChat's chat_web module parses args at import time, so we must import
# it *after* sys.argv is set up (which it already is from our CLI).
from scripts.chat_web import app, args  # noqa: E402
from nanochat_ext import mount_train_route  # noqa: E402

mount_train_route(app)

if __name__ == "__main__":
    import uvicorn

    print("Starting NanoChat Web Server (with WikiOracle /train extension)")
    print(f"Temperature: {args.temperature}, Top-k: {args.top_k}, Max tokens: {args.max_tokens}")
    uvicorn.run(app, host=args.host, port=args.port)
