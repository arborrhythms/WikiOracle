#!/usr/bin/env python3
"""WikiOracle local shim (conversation-based hierarchy).

Local-first Flask server that owns one llm.jsonl file, proxies chat to an
upstream stateless endpoint (NanoChat, OpenAI, Anthropic), and supports
deterministic merge/import of exported llm_*.jsonl files.

REST API Endpoints:

| Route            | Methods      | Purpose                                                      |
|------------------|--------------|--------------------------------------------------------------|
| /health          | GET          | Liveness check                                               |
| /server_info     | GET          | Stateless flag + url_prefix                                  |
| /bootstrap       | GET          | One-shot seed for stateless clients (state + config)             |
| /info            | GET          | State/schema/provider metadata for diagnostics               |
| /state           | GET, POST    | Read or replace local state                                  |
| /state_size      | GET          | State file size in bytes (progress bar)                      |
| /chat            | POST         | Process chat turn (QueryBundle → ResponseBundle)             |
| /merge           | POST         | Merge imported state payloads/files                          |
| /config          | GET, POST    | GET: normalized config. POST: full config dict               |
| /                | GET          | Serve index.html                                             |
| /<path>          | GET          | Serve whitelisted static assets                              |

Usage:
    # Server mode (default)
    export WIKIORACLE_STATE_FILE="/abs/path/to/llm.jsonl"
    python bin/wikioracle.py

    # CLI merge mode
    python bin/wikioracle.py merge llm_2026.02.22.1441.jsonl llm_2026.02.23.0900.jsonl

Then open https://localhost:8888/
"""

from __future__ import annotations

import copy
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Any, Dict

from flask import Flask, request as flask_request, jsonify, send_from_directory

# Ensure bin/ is on the path so sibling modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as config_mod
from config import (
    Config,
    PROVIDERS,
    _CONFIG_YAML,
    _CONFIG_YAML_STATUS,
    _build_providers,
    _normalize_config,
    _env_bool,
    _ensure_self_signed_cert,
    _load_config_yaml,
    config_to_yaml,
    load_config,
    parse_args,
)
from state import (
    SCHEMA_URL,
    STATE_VERSION,
    atomic_write_jsonl,
    build_context_draft,
    ensure_minimal_state,
    load_state_file,
    merge_llm_states,
)
from response import (
    _MEMORY_STATE,
    _build_bundle,
    _bundle_to_messages,
    _load_state,
    _save_state,
    _scan_and_merge_imports,
    process_chat,
    run_cli_merge,
)


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------
def create_app(cfg: Config, url_prefix: str = "") -> Flask:
    """Create and configure the WikiOracle Flask application instance."""
    app = Flask(__name__, static_folder=None)
    startup_merge_report = _scan_and_merge_imports(cfg) if not config_mod.STATELESS_MODE else {}

    # Store url_prefix in module-level config so all modules can read it
    config_mod.URL_PREFIX = url_prefix

    # Write CLI-supplied runtime values into _CONFIG_YAML so they
    # round-trip through config like everything else — no per-response
    # patching needed.
    config_mod._CONFIG_YAML.setdefault("server", {})
    config_mod._CONFIG_YAML["server"]["stateless"] = config_mod.STATELESS_MODE
    config_mod._CONFIG_YAML["server"]["url_prefix"] = url_prefix

    # Security headers (CORS + CSP)
    @app.after_request
    def add_security_headers(response):
        """Apply CORS and Content-Security-Policy headers."""
        origin = flask_request.headers.get("Origin", "")
        if origin and origin in cfg.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        # Content Security Policy (enforcing)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://d3js.org https://cdnjs.cloudflare.com; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response

    @app.route(url_prefix + "/health", methods=["GET"])
    def health():
        """Simple liveness endpoint for local health checks."""
        return jsonify({"ok": True})

    @app.route(url_prefix + "/server_info", methods=["GET"])
    def server_info():
        """Expose server-mode flags that do not require state access."""
        return jsonify({
            "stateless": config_mod.STATELESS_MODE,
            "url_prefix": url_prefix,
        })

    @app.route(url_prefix + "/bootstrap", methods=["GET"])
    def bootstrap():
        """One-shot seed for stateless clients: state + config + providers."""
        result: Dict[str, Any] = {}

        # Seed state from disk (or empty minimal state)
        try:
            seed_state = _load_state(cfg)
        except Exception:
            seed_state = ensure_minimal_state({}, strict=False)
        result["state"] = seed_state

        # Normalized config (YAML-shaped with defaults + runtime server fields)
        fresh = _load_config_yaml()
        if fresh:
            config_mod._CONFIG_YAML = fresh
            # Re-inject runtime fields lost by disk reload
            config_mod._CONFIG_YAML.setdefault("server", {})
            config_mod._CONFIG_YAML["server"]["stateless"] = config_mod.STATELESS_MODE
            config_mod._CONFIG_YAML["server"]["url_prefix"] = url_prefix
        result["config"] = _normalize_config(config_mod._CONFIG_YAML)

        return jsonify(result)

    @app.route(url_prefix + "/info", methods=["GET"])
    def info():
        """Return state/schema/provider metadata for UI diagnostics."""
        try:
            state = _load_state(cfg)
            return jsonify({
                "ok": True,
                "state_file_name": cfg.state_file.name,
                "schema": state.get("schema", SCHEMA_URL),
                "version": state.get("version", STATE_VERSION),
                "time": state.get("time"),
                "providers": list(PROVIDERS.keys()),
                "startup_merge": startup_merge_report,
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route(url_prefix + "/state", methods=["GET", "POST"])
    def state_endpoint():
        """Read or replace local state depending on HTTP method."""
        import response as response_mod

        if flask_request.method == "GET":
            try:
                if config_mod.STATELESS_MODE and response_mod._MEMORY_STATE is not None:
                    return jsonify({"state": response_mod._MEMORY_STATE})
                state = _load_state(cfg)
                if config_mod.STATELESS_MODE:
                    response_mod._MEMORY_STATE = state
                return jsonify({"state": state})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
        else:
            data = flask_request.get_json(force=True, silent=True)
            if not isinstance(data, dict):
                return jsonify({"ok": False, "error": "invalid_state"}), 400
            if config_mod.STATELESS_MODE:
                # Update in-memory state without writing to disk
                response_mod._MEMORY_STATE = data
                return jsonify({"ok": True})
            try:
                _save_state(cfg, data)
                return jsonify({"ok": True})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route(url_prefix + "/state_size", methods=["GET"])
    def state_size_endpoint():
        """Return the state file size in bytes (for progress bar)."""
        try:
            if cfg.state_file.exists():
                return jsonify({"ok": True, "size": cfg.state_file.stat().st_size})
            return jsonify({"ok": True, "size": 0})
        except Exception as exc:
            return jsonify({"ok": False, "size": 0, "error": str(exc)})

    @app.route(url_prefix + "/chat", methods=["POST", "OPTIONS"])
    def chat():
        """Process a chat turn, update conversation state, and return reply text."""
        import response as response_mod

        if flask_request.method == "OPTIONS":
            return ("", 204)

        body = flask_request.get_json(force=True, silent=True) or {}
        user_msg = (body.get("message") or "").strip()
        if not user_msg:
            return jsonify({"ok": False, "error": "missing_message"}), 400

        # ── Stateless mode: client must supply state + runtime_config ──
        if config_mod.STATELESS_MODE:
            if not isinstance(body.get("state"), dict):
                return jsonify({"ok": False, "error": "stateless_missing_state"}), 400
            if not isinstance(body.get("runtime_config"), dict):
                return jsonify({"ok": False, "error": "stateless_missing_runtime_config"}), 400

        # Config source: request payload (stateless) or disk (stateful)
        if config_mod.STATELESS_MODE:
            runtime_cfg = body["runtime_config"]
        else:
            fresh = _load_config_yaml()
            if fresh:
                config_mod._CONFIG_YAML = fresh
            runtime_cfg = config_mod._CONFIG_YAML

        path_only = isinstance(body.get("state"), dict) and body["state"].get("_path_only", False)

        try:
            if config_mod.STATELESS_MODE:
                # Client-supplied state is authoritative — no disk/memory reads.
                state = copy.deepcopy(body["state"])
                state.pop("_path_only", None)
                state = ensure_minimal_state(state, strict=False)
            else:
                state = _load_state(cfg)
                # In stateful mode, merge client-supplied trust/context/output
                if isinstance(body.get("state"), dict):
                    client_state = body["state"]
                    if "truth" in client_state:
                        state["truth"] = client_state["truth"]
                    if "context" in client_state:
                        state["context"] = client_state["context"]
                    if "output" in client_state:
                        state["output"] = client_state["output"]

            response_text, state = process_chat(cfg, state, body, runtime_cfg)

            if not config_mod.STATELESS_MODE:
                _save_state(cfg, state)
                # Reload after save to get normalized state
                state = _load_state(cfg)

            return jsonify({"ok": True, "text": response_text, "state": state})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.route(url_prefix + "/merge", methods=["POST", "OPTIONS"])
    def merge_endpoint():
        """Merge imported state payloads/files into the canonical local state."""
        if flask_request.method == "OPTIONS":
            return ("", 204)
        if config_mod.STATELESS_MODE:
            return jsonify({"ok": False, "error": "Server is in stateless mode — writes disabled"}), 403

        body = flask_request.get_json(force=True, silent=True) or {}

        if body.get("auto", False):
            root = cfg.state_file.parent
            import_files = sorted(list(root.glob("llm_*.jsonl")) + list(root.glob("llm_*.json")))
            import_files = [f for f in import_files if f.resolve() != cfg.state_file
                           and not f.name.endswith(cfg.merged_suffix)]
        elif "state" in body:
            try:
                base = _load_state(cfg)
                rewriter = None
                if cfg.auto_context_rewrite:
                    rewriter = lambda ctx, deltas: build_context_draft(ctx, deltas, cfg.max_context_chars)
                merged, meta = merge_llm_states(base, body["state"],
                                                 keep_base_context=True, context_rewriter=rewriter)
                _save_state(cfg, merged)
                return jsonify({"ok": True, "meta": meta, "state": merged})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
        else:
            filenames = body.get("files", [])
            import_files = [cfg.state_file.parent / f for f in filenames
                          if f.endswith(".jsonl") or f.endswith(".json")]

        base = _load_state(cfg)
        merged_count = 0
        merged_names = []
        for fp in import_files:
            if not fp.exists() or fp.resolve() == cfg.state_file:
                continue
            try:
                incoming = load_state_file(fp, strict=True)
                rewriter = None
                if cfg.auto_context_rewrite:
                    rewriter = lambda ctx, deltas: build_context_draft(ctx, deltas, cfg.max_context_chars)
                base, meta = merge_llm_states(base, incoming,
                                               keep_base_context=True, context_rewriter=rewriter)
                fp.rename(fp.with_name(fp.name + cfg.merged_suffix))
                merged_count += 1
                merged_names.append(fp.name)
            except Exception:
                continue

        if merged_count > 0:
            _save_state(cfg, base)
        return jsonify({"ok": True, "merged": merged_count, "files": merged_names})

    @app.route(url_prefix + "/config", methods=["GET", "POST"])
    def config_endpoint():
        """GET: normalized config (YAML-shaped).
        POST: accept full config dict; write config.yaml to disk.
        """
        # Re-read config.yaml to pick up hot-reloads
        fresh = _load_config_yaml()
        if fresh:
            config_mod._CONFIG_YAML = fresh
            # Re-inject runtime fields lost by disk reload
            config_mod._CONFIG_YAML.setdefault("server", {})
            config_mod._CONFIG_YAML["server"]["stateless"] = config_mod.STATELESS_MODE
            config_mod._CONFIG_YAML["server"]["url_prefix"] = url_prefix

        if flask_request.method == "GET":
            return jsonify({"config": _normalize_config(config_mod._CONFIG_YAML)})
        else:
            if config_mod.STATELESS_MODE:
                return jsonify({"ok": False, "error": "Server is in stateless mode — writes disabled"}), 403

            body = flask_request.get_json(force=True, silent=True) or {}

            try:
                project_root = Path(__file__).resolve().parent.parent
                cfg_path = project_root / "config.yaml"

                # Client sends { config: {...} } — the full YAML-shaped config dict
                if "config" not in body or not isinstance(body["config"], dict):
                    return jsonify({"ok": False, "error": "missing config dict"}), 400

                data = body["config"]
                cfg_path.write_text(config_to_yaml(data), encoding="utf-8")
                config_mod._CONFIG_YAML = _load_config_yaml()
                # Re-inject runtime fields lost by disk reload
                config_mod._CONFIG_YAML.setdefault("server", {})
                config_mod._CONFIG_YAML["server"]["stateless"] = config_mod.STATELESS_MODE
                config_mod._CONFIG_YAML["server"]["url_prefix"] = url_prefix
                PROVIDERS.clear()
                PROVIDERS.update(_build_providers())
                normalized = _normalize_config(config_mod._CONFIG_YAML)
                return jsonify({"ok": True, "config": normalized})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

    # Static file serving — all UI assets live in html/ subdirectory
    project_root = Path(__file__).resolve().parent.parent
    ui_dir = project_root / "html"

    @app.route(url_prefix + "/", methods=["GET"])
    def ui_index():
        """Serve the UI entrypoint page (never cached so script version bumps take effect)."""
        ui_path = ui_dir / "index.html"
        if ui_path.exists():
            resp = send_from_directory(str(ui_dir), "index.html")
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        return "<h3>WikiOracle Local Shim</h3><p>index.html not found.</p>", 404

    @app.route(url_prefix + "/<path:filename>", methods=["GET"])
    def static_files(filename):
        """Serve whitelisted static asset extensions from html/."""
        safe_ext = {".html", ".css", ".js", ".svg", ".png", ".ico", ".json", ".jsonl"}
        if Path(filename).suffix.lower() in safe_ext:
            fp = (ui_dir / filename).resolve()
            if fp.exists() and str(fp).startswith(str(ui_dir.resolve())):
                return send_from_directory(str(ui_dir), filename)
        return "", 404

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    """Entrypoint for server startup and one-shot CLI merge execution."""
    args = parse_args()
    config_mod.DEBUG_MODE = args.debug
    config_mod.STATELESS_MODE = args.stateless or _env_bool("WIKIORACLE_STATELESS", False)
    cfg = load_config()

    if args.cmd == "merge":
        incoming_files = [Path(p).expanduser().resolve() for p in args.incoming]
        return run_cli_merge(cfg, incoming_files)

    # Default: serve
    url_prefix = (args.url_prefix or os.environ.get("WIKIORACLE_URL_PREFIX", "")).strip().rstrip("/")
    config_mod.URL_PREFIX = url_prefix

    if not config_mod.STATELESS_MODE:
        cfg.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not cfg.state_file.exists():
            initial = ensure_minimal_state({}, strict=False)
            atomic_write_jsonl(cfg.state_file, initial, reject_symlinks=cfg.reject_symlinks)

    # Ensure TLS certificate exists
    _ensure_self_signed_cert(cfg.ssl_cert, cfg.ssl_key)

    print(f"\n{'='*60}")
    print(f"  WikiOracle Local Shim")
    print(f"{'='*60}")
    print(f"  State file : {cfg.state_file}{' (STATELESS — no writes)' if config_mod.STATELESS_MODE else ''}")
    print(f"  Bind       : {cfg.bind_host}:{cfg.bind_port}")
    print(f"  TLS cert   : {cfg.ssl_cert}")
    if url_prefix:
        print(f"  URL prefix : {url_prefix}")
    prov_info = []
    for k, p in PROVIDERS.items():
        has_key = bool(p.get("api_key"))
        model = p.get("default_model", "")
        url = p.get("url", "")
        status = "ok" if has_key or k == "wikioracle" else "NO KEY"
        parts = [status]
        if model:
            parts.append(model)
        if url:
            parts.append(url)
        prov_info.append(f"{k}({', '.join(parts)})")
    print(f"  Providers  :")
    for pi in prov_info:
        print(f"    {pi}")
    print(f"  Config YAML: {_CONFIG_YAML_STATUS}")
    print(f"  Stateless  : {'ON' if config_mod.STATELESS_MODE else 'off'}")
    print(f"  Debug      : {'ON' if config_mod.DEBUG_MODE else 'off'}")
    print(f"  UI         : https://{cfg.bind_host}:{cfg.bind_port}{url_prefix}/")
    if cfg.bind_host == "0.0.0.0":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))  # doesn't actually send anything
            lan_ip = s.getsockname()[0]
            s.close()
            print(f"  LAN        : https://{lan_ip}:{cfg.bind_port}{url_prefix}/")
        except Exception:
            pass
    print(f"{'='*60}\n")

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(str(cfg.ssl_cert), str(cfg.ssl_key))

    app = create_app(cfg, url_prefix=url_prefix)
    app.run(host=cfg.bind_host, port=cfg.bind_port, debug=False, ssl_context=ssl_ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
