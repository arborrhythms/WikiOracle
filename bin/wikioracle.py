#!/usr/bin/env python3
"""WikiOracle local shim (conversation-based hierarchy).

Local-first Flask server that owns one state.xml file, proxies chat to an
upstream stateless endpoint (NanoChat, OpenAI, Anthropic), and supports
deterministic merge/import of exported state files.

REST API Endpoints:

| Route            | Methods      | Purpose                                                      |
|------------------|--------------|--------------------------------------------------------------|
| /health          | GET          | Liveness check                                               |
| /nanochat_status | GET          | Probe upstream NanoChat server health                        |
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
    export WIKIORACLE_STATE_FILE="/abs/path/to/state.xml"
    python bin/wikioracle.py

    # CLI merge mode
    python bin/wikioracle.py merge state_2026.02.22.1441.xml state_2026.02.23.0900.xml

Then open https://localhost:8888/
"""

from __future__ import annotations

import copy
import json
import logging
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
    _PROJECT_ROOT,
    _build_providers,
    _find_xml,
    _normalize_config,
    _env_bool,
    _ensure_self_signed_cert,
    _load_config,
    config_to_xml,
    load_config,
    parse_args,
    reload_config,
)
from state import (
    SCHEMA_URL,
    STATE_VERSION,
    atomic_write_xml,
    build_context_draft,
    ensure_minimal_state,
    find_conversation,
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
from security import RateLimiter, guard_input


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------
def create_app(cfg: Config, url_prefix: str = "") -> Flask:
    """Create and configure the WikiOracle Flask application instance."""
    log = logging.getLogger("wikioracle")
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = cfg.max_state_bytes

    # Rate limiting (disabled when env var is 0)
    _chat_rpm = int(os.getenv("WIKIORACLE_RATE_LIMIT_CHAT", "30"))
    _default_rpm = int(os.getenv("WIKIORACLE_RATE_LIMIT_DEFAULT", "120"))
    _rate_limiter = RateLimiter(default_rpm=_default_rpm)
    if _chat_rpm > 0:
        _rate_limiter.set_limit(url_prefix + "/chat", _chat_rpm)

    startup_merge_report = _scan_and_merge_imports(cfg) if not config_mod.STATELESS_MODE else {}

    # Store url_prefix in module-level config so all modules can read it
    config_mod.URL_PREFIX = url_prefix

    def _inject_server_runtime() -> None:
        """Re-inject CLI runtime fields after a config reload from disk.

        ``stateless`` and ``url_prefix`` are set via CLI flags and must
        survive disk reloads.  ``allowed_urls`` is left as-is since it
        is authoritative from disk (admin-only).
        """
        srv = config_mod._CONFIG.setdefault("server", {})
        srv["stateless"] = config_mod.STATELESS_MODE
        srv["url_prefix"] = url_prefix

    _inject_server_runtime()

    # Persist auto-generated server_id to config.xml if not already on disk
    if not config_mod.STATELESS_MODE:
        _config_xml_path = _find_xml(_PROJECT_ROOT, "config.xml")
        if _config_xml_path is not None:
            _disk_cfg = config_mod._load_config_xml(_config_xml_path)
            if not _disk_cfg.get("server", {}).get("server_id"):
                normalized = _normalize_config(config_mod._CONFIG)
                new_sid = normalized.get("server", {}).get("server_id")
                if new_sid:
                    _disk_cfg.setdefault("server", {})["server_id"] = new_sid
                    try:
                        _config_xml_path.write_text(
                            config_to_xml(_disk_cfg), encoding="utf-8",
                        )
                        log.info("Persisted auto-generated server_id to config.xml")
                    except OSError as exc:
                        log.warning("Could not persist server_id: %s", exc)

    # Security headers (CORS + CSP)
    @app.after_request
    def add_security_headers(response):
        """Apply CORS and Content-Security-Policy headers."""
        origin = flask_request.headers.get("Origin", "")
        if origin and origin in cfg.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        # Content Security Policy (enforcing)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response

    @app.before_request
    def auth_check():
        """Enforce bearer-token auth (if configured) and CSRF header on POSTs."""
        # Bearer-token auth — skip for OPTIONS, /health, and static UI serving
        _PUBLIC_ENDPOINTS = {"health", "ui_index", "static_files", "nanochat_status", "basicmodel_status"}
        if cfg.api_token and flask_request.method != "OPTIONS":
            if flask_request.endpoint not in _PUBLIC_ENDPOINTS:
                auth = flask_request.headers.get("Authorization", "")
                if auth != f"Bearer {cfg.api_token}":
                    return jsonify({"ok": False, "error": "unauthorized"}), 401
        # CSRF header on POSTs
        if flask_request.method == "POST":
            if flask_request.headers.get("X-Requested-With") != "WikiOracle":
                return jsonify({"ok": False, "error": "missing_csrf_header"}), 403
        # Rate limiting (skip for health/OPTIONS)
        if flask_request.endpoint != "health" and flask_request.method != "OPTIONS":
            ip = flask_request.remote_addr or "unknown"
            if not _rate_limiter.allow(ip, flask_request.path):
                resp = jsonify({"ok": False, "error": "rate_limit_exceeded"})
                resp.headers["Retry-After"] = "60"
                return resp, 429

    @app.route(url_prefix + "/health", methods=["GET"])
    def health():
        """Simple liveness endpoint for local health checks."""
        return jsonify({"ok": True})

    @app.route(url_prefix + "/nanochat_status", methods=["GET"])
    def nanochat_status():
        """Probe the upstream NanoChat server and return its status."""
        import requests as _req
        chat_url = PROVIDERS.get("WikiOracle", {}).get("url") or (cfg.base_url + cfg.api_path)
        api_suffix = cfg.api_path or "/chat/completions"
        if isinstance(chat_url, str) and chat_url.endswith(api_suffix):
            url = chat_url[:-len(api_suffix)].rstrip("/")
        else:
            url = str(chat_url).rstrip("/")
        try:
            health_timeout = PROVIDERS.get("WikiOracle", {}).get("timeout") or 15
            resp = _req.get(url + "/health", timeout=health_timeout, verify=False)
            if resp.ok:
                return jsonify({"ok": True, "url": url, "status": "online"})
            return jsonify({"ok": False, "url": url, "status": f"HTTP {resp.status_code}"})
        except _req.ConnectionError:
            return jsonify({"ok": False, "url": url, "status": "offline"})
        except Exception as exc:
            return jsonify({"ok": False, "url": url, "status": str(exc)})

    @app.route(url_prefix + "/basicmodel_status", methods=["GET"])
    def basicmodel_status():
        """Probe the BasicModel inference server and return its status."""
        import requests as _req
        url = PROVIDERS.get("WikiOracle", {}).get("basicmodel_url", "http://127.0.0.1:8001")
        url = url.rstrip("/")
        try:
            resp = _req.get(url + "/health", timeout=5, verify=False)
            if resp.ok:
                return jsonify({"ok": True, "url": url, "status": "online"})
            return jsonify({"ok": False, "url": url, "status": f"HTTP {resp.status_code}"})
        except _req.ConnectionError:
            return jsonify({"ok": False, "url": url, "status": "offline"})
        except Exception as exc:
            return jsonify({"ok": False, "url": url, "status": str(exc)})

    @app.route(url_prefix + "/server_info", methods=["GET"])
    def server_info():
        """Expose server-mode flags that do not require state access."""
        tr = config_mod._CONFIG.get("server", {}).get("training", {})
        return jsonify({
            "stateless": config_mod.STATELESS_MODE,
            "url_prefix": url_prefix,
            "training": tr.get("enabled", False) and not config_mod.STATELESS_MODE,
        })

    @app.route(url_prefix + "/bootstrap", methods=["GET"])
    def bootstrap():
        """One-shot seed for stateless clients: state + config + providers."""
        result: Dict[str, Any] = {}

        # Seed state from disk (read-only).  In stateless mode the truth
        # table is loaded once from disk but never written back.
        try:
            seed_state = _load_state(cfg)
        except Exception:
            seed_state = ensure_minimal_state({}, strict=False)
        result["state"] = seed_state

        # Normalized config (with defaults + runtime server fields)
        fresh = _load_config()
        if fresh:
            config_mod._CONFIG = fresh
            _inject_server_runtime()
        result["config"] = _normalize_config(config_mod._CONFIG)

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
            log.exception("GET /info failed")
            return jsonify({"ok": False, "error": "Failed to load server info"}), 400

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
                log.exception("GET /state failed")
                return jsonify({"ok": False, "error": "Failed to load state"}), 400
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
                log.exception("POST /state failed")
                return jsonify({"ok": False, "error": "Failed to save state"}), 400

    @app.route(url_prefix + "/new", methods=["POST"])
    def new_session():
        """Reset state to an empty session and persist to disk."""
        import response as response_mod
        try:
            empty = ensure_minimal_state({})
            if config_mod.STATELESS_MODE:
                response_mod._MEMORY_STATE = empty
            else:
                _save_state(cfg, empty)
            return jsonify({"ok": True})
        except Exception as exc:
            log.exception("POST /new failed")
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route(url_prefix + "/state_size", methods=["GET"])
    def state_size_endpoint():
        """Return the state file size in bytes (for progress bar)."""
        try:
            if cfg.state_file.exists():
                return jsonify({"ok": True, "size": cfg.state_file.stat().st_size})
            return jsonify({"ok": True, "size": 0})
        except Exception as exc:
            log.exception("GET /state_size failed")
            return jsonify({"ok": False, "size": 0, "error": "Failed to check state size"})

    @app.route(url_prefix + "/chat", methods=["POST", "OPTIONS"])
    def chat():
        """Process a chat turn, update conversation state, and return reply text."""
        import response as response_mod

        if flask_request.method == "OPTIONS":
            return ("", 204)

        body = flask_request.get_json(force=True, silent=True) or {}
        user_msg = (body.get("message") or "").strip()
        conversation_id = body.get("conversation_id")
        branch_from = body.get("branch_from")

        # Input length validation
        _max_input_len = int(os.getenv("WIKIORACLE_MAX_INPUT_LEN", "50000"))
        if len(user_msg) > _max_input_len:
            return jsonify({"ok": False, "error": "input_too_long",
                            "max_length": _max_input_len}), 400

        # Prompt injection guard
        injection_reason = guard_input(user_msg)
        if injection_reason:
            log.warning("Blocked input from %s: %s",
                        flask_request.remote_addr, injection_reason)
            return jsonify({"ok": False, "error": "input_rejected"}), 400

        # Empty sends are allowed: at root (new conversation), at terminal
        # nodes (continue), or via branch_from.  All three create valid turns.

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
            fresh = _load_config()
            if fresh:
                config_mod._CONFIG = fresh
                _inject_server_runtime()
            runtime_cfg = config_mod._CONFIG

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
                    # context/output no longer live in state (moved to config.providers)

            response_text, state, symmetry_rejected = process_chat(cfg, state, body, runtime_cfg)

            if not config_mod.STATELESS_MODE:
                _save_state(cfg, state)

            if config_mod.STATELESS_MODE:
                # Stateless: client is the only copy — return full state
                resp = {"ok": True, "text": response_text, "state": state}
            else:
                # Stateful: truth flows client → server only.  Return
                # just the conversation delta so the client can merge it.
                sel = state.get("selected_conversation")
                conv = find_conversation(state.get("conversations", []), sel) if sel else None
                response_state = {
                    "conversations": [conv] if conv else [],
                    "selected_conversation": sel,
                }
                resp = {"ok": True, "text": response_text, "state": response_state}
            if symmetry_rejected:
                resp["symmetry_rejected"] = symmetry_rejected

            # ── Debug mode: include server truth table as authority entries ──
            # When debug mode is enabled and online training is active, return
            # the server's truth entries so the client can display them.
            # Entries are returned so the client can display them.
            if config_mod.DEBUG_MODE:
                ot = config_mod._CONFIG.get("server", {}).get("training", {})
                if ot.get("enabled", False) and not config_mod.STATELESS_MODE:
                    try:
                        from truth import load_server_truth
                        _st_path = Path(ot.get("truth_corpus_path", "data/truth.xml"))
                        _st_entries = load_server_truth(_st_path)
                        _server_id = config_mod._CONFIG.get("server", {}).get("server_id", "wikioracle")
                        server_truth = []
                        for entry in _st_entries:
                            server_truth.append({
                                "type": "authority",
                                "id": entry.get("id", ""),
                                "title": entry.get("title", ""),
                                "trust": entry.get("trust", 0.5),
                                "content": entry.get("content", ""),
                                "source": _server_id,
                            })
                        resp["server_truth"] = server_truth
                    except Exception as _st_exc:
                        log.warning("Debug server truth: %s", _st_exc)

            return jsonify(resp)
        except Exception as exc:
            log.exception("POST /chat failed")
            return jsonify({"ok": False, "error": "Chat request failed"}), 502

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
            import_files = sorted(list(root.glob("llm_*.xml")) + list(root.glob("llm_*.json")))
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
                log.exception("POST /merge failed")
                return jsonify({"ok": False, "error": "Merge failed"}), 400
        else:
            filenames = body.get("files", [])
            import_files = [cfg.state_file.parent / f for f in filenames
                          if (f.endswith(".json") or f.endswith(".xml"))
                          and ".." not in f and "/" not in f and "\\" not in f]

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
        """GET: normalized config.  POST: accept full config dict; write config.xml."""
        # Re-read config to pick up hot-reloads
        fresh = _load_config()
        if fresh:
            config_mod._CONFIG = fresh
            _inject_server_runtime()

        if flask_request.method == "GET":
            return jsonify({"config": _normalize_config(config_mod._CONFIG)})
        else:
            if config_mod.STATELESS_MODE:
                return jsonify({"ok": False, "error": "Server is in stateless mode — writes disabled"}), 403

            body = flask_request.get_json(force=True, silent=True) or {}

            try:
                cfg_xml = _find_xml(_PROJECT_ROOT, "config.xml") or _PROJECT_ROOT / "config.xml"

                # Client sends { config: {...} } — the full config dict
                if "config" not in body or not isinstance(body["config"], dict):
                    return jsonify({"ok": False, "error": "missing config dict"}), 400

                data = body["config"]
                # Strip runtime-only field (server.providers) — not user config.
                if isinstance(data.get("server"), dict):
                    data["server"].pop("providers", None)
                # Preserve the on-disk allowed_urls — clients must not
                # override this server-level security setting.
                disk_allowed = config_mod._CONFIG.get("server", {}).get("allowed_urls")
                if isinstance(data.get("server"), dict):
                    data["server"].pop("allowed_urls", None)
                if disk_allowed is not None:
                    data.setdefault("server", {})["allowed_urls"] = disk_allowed

                cfg_xml.write_text(config_to_xml(data), encoding="utf-8")

                config_mod._CONFIG = _load_config()
                _inject_server_runtime()
                PROVIDERS.clear()
                PROVIDERS.update(_build_providers())
                normalized = _normalize_config(config_mod._CONFIG)
                return jsonify({"ok": True, "config": normalized})
            except Exception as exc:
                log.exception("POST /config failed")
                return jsonify({"ok": False, "error": "Configuration update failed"}), 400

    # Static file serving — all UI assets live in client/ subdirectory
    ui_dir = _PROJECT_ROOT / "client"

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
        """Serve whitelisted static asset extensions from client/."""
        safe_ext = {".html", ".css", ".js", ".svg", ".png", ".ico", ".json", ".xml"}
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
    # Load custom config if specified (before anything reads _CONFIG).
    if args.config:
        reload_config(args.config)
    config_mod.DEBUG_MODE = args.debug
    # Stateless: CLI flag > config.xml > env var > default (False)
    if args.stateless:
        config_mod.STATELESS_MODE = True
    else:
        cfg_stateless = config_mod._CONFIG.get("server", {}).get("stateless")
        if cfg_stateless is not None:
            config_mod.STATELESS_MODE = bool(cfg_stateless)
        else:
            config_mod.STATELESS_MODE = _env_bool("WIKIORACLE_STATELESS", False)
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
            atomic_write_xml(cfg.state_file, initial, reject_symlinks=cfg.reject_symlinks)

    use_ssl = not args.no_ssl

    # Ensure TLS certificate exists
    if use_ssl:
        _ensure_self_signed_cert(cfg.ssl_cert, cfg.ssl_key)

    scheme = "https" if use_ssl else "http"

    print(f"\n{'='*60}")
    print(f"  WikiOracle Local Shim")
    print(f"{'='*60}")
    print(f"  State file : {cfg.state_file}{' (STATELESS — no writes)' if config_mod.STATELESS_MODE else ''}")
    print(f"  Bind       : {cfg.bind_host}:{cfg.bind_port}")
    if use_ssl:
        print(f"  TLS cert   : {cfg.ssl_cert}")
    if url_prefix:
        print(f"  URL prefix : {url_prefix}")
    prov_info = []
    for name, p in PROVIDERS.items():
        model = p.get("model", "")
        url = p.get("url", "")
        prov_type = p.get("type", "")
        status = "ok" if bool(p.get("api_key")) or prov_type == "wikioracle" else "no key"
        parts = [status]
        if model:
            parts.append(model)
        if url:
            parts.append(url)
        prov_info.append(f"{name}({', '.join(parts)})")
    print(f"  Providers  :")
    for pi in prov_info:
        print(f"    {pi}")
    print(f"  Config     : {config_mod._CONFIG_STATUS}")
    print(f"  Stateless  : {'ON' if config_mod.STATELESS_MODE else 'off'}")
    ot_cfg = config_mod._CONFIG.get("server", {}).get("training", {})
    ot_on = ot_cfg.get("enabled", False) and not config_mod.STATELESS_MODE
    ot_device = ot_cfg.get("device", "cpu")
    if ot_on:
        print(f"  Online trn : \033[32mON\033[0m (device={ot_device})")
    else:
        print(f"  Online trn : \033[31moff\033[0m")
    print(f"  Debug      : {'ON' if config_mod.DEBUG_MODE else 'off'}")
    print(f"  UI         : {scheme}://{cfg.bind_host}:{cfg.bind_port}{url_prefix}/")
    if cfg.bind_host == "0.0.0.0":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))  # doesn't actually send anything
            lan_ip = s.getsockname()[0]
            s.close()
            print(f"  LAN        : {scheme}://{lan_ip}:{cfg.bind_port}{url_prefix}/")
        except Exception:
            pass
    print(f"{'='*60}\n")

    ssl_ctx = None
    if use_ssl:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(str(cfg.ssl_cert), str(cfg.ssl_key))

    app = create_app(cfg, url_prefix=url_prefix)
    app.run(host=cfg.bind_host, port=cfg.bind_port, debug=False, ssl_context=ssl_ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
