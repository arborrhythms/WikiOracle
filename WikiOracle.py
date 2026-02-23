#!/usr/bin/env python3
"""WikiOracle local shim (conversation-based hierarchy).

Local-first Flask server that owns one llm.jsonl file, proxies chat to an
upstream stateless endpoint (NanoChat, OpenAI, Anthropic), and supports
deterministic merge/import of exported llm_*.jsonl files.

Usage:
    # Server mode (default)
    export WIKIORACLE_STATE_FILE="/abs/path/to/llm.jsonl"
    export WIKIORACLE_SHIM_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    python WikiOracle.py

    # CLI merge mode
    python WikiOracle.py merge llm_2026.02.22.1441.jsonl llm_2026.02.23.0900.jsonl

Then open http://127.0.0.1:8787/
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hmac
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import requests
from flask import Flask, request as flask_request, jsonify, send_from_directory

# Ensure bin/ is on the path so we can import wikioracle_state
sys.path.insert(0, str(Path(__file__).resolve().parent / "bin"))

from wikioracle_state import (
    SCHEMA_URL,
    STATE_VERSION,
    StateValidationError,
    add_child_conversation,
    add_message_to_conversation,
    atomic_write_jsonl,
    build_context_draft,
    ensure_conversation_id,
    ensure_message_id,
    ensure_minimal_state,
    ensure_xhtml,
    extract_context_deltas,
    find_conversation,
    get_ancestor_chain,
    get_context_messages,
    get_provider_entries,
    get_src_entries,
    load_state_file,
    merge_llm_states,
    parse_provider_block,
    resolve_api_key,
    resolve_src_content,
    strip_xhtml,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class Config:
    state_file: Path
    shim_token: str
    base_url: str = "https://wikioracle.org"
    api_path: str = "/chat/completions"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787
    timeout_s: float = 120.0
    max_state_bytes: int = 5_000_000
    max_context_chars: int = 40_000
    reject_symlinks: bool = True
    auto_merge_on_start: bool = True
    auto_context_rewrite: bool = False
    merged_suffix: str = ".merged"
    allowed_origins: set = field(default_factory=lambda: {
        "http://127.0.0.1:8787", "http://localhost:8787"
    })


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    state_file = Path(
        os.environ.get("WIKIORACLE_STATE_FILE", str(Path.cwd() / "llm.jsonl"))
    ).expanduser().resolve()

    shim_token = os.environ.get("WIKIORACLE_SHIM_TOKEN", "").strip()

    allowed_origins_raw = os.environ.get(
        "WIKIORACLE_ALLOWED_ORIGINS",
        "http://127.0.0.1:8787,http://localhost:8787",
    )
    allowed_origins = {v.strip() for v in allowed_origins_raw.split(",") if v.strip()}

    return Config(
        state_file=state_file,
        shim_token=shim_token,
        base_url=os.environ.get("WIKIORACLE_BASE_URL", "https://wikioracle.org").rstrip("/"),
        api_path=os.environ.get("WIKIORACLE_API_PATH", "/chat/chat/completions"),
        bind_host=os.environ.get("WIKIORACLE_BIND_HOST", "127.0.0.1"),
        bind_port=int(os.environ.get("WIKIORACLE_BIND_PORT", "8787")),
        timeout_s=float(os.environ.get("WIKIORACLE_TIMEOUT_S", "120")),
        max_state_bytes=int(os.environ.get("WIKIORACLE_MAX_STATE_BYTES", str(5_000_000))),
        max_context_chars=int(os.environ.get("WIKIORACLE_MAX_CONTEXT_CHARS", "40000")),
        reject_symlinks=_env_bool("WIKIORACLE_REJECT_SYMLINKS", True),
        auto_merge_on_start=_env_bool("WIKIORACLE_AUTO_MERGE_ON_START", True),
        auto_context_rewrite=_env_bool("WIKIORACLE_AUTO_CONTEXT_REWRITE", False),
        merged_suffix=os.environ.get("WIKIORACLE_MERGED_SUFFIX", ".merged").strip() or ".merged",
        allowed_origins=allowed_origins,
    )


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------
def _build_providers() -> Dict[str, Dict[str, Any]]:
    providers: Dict[str, Dict[str, Any]] = {
        "wikioracle": {
            "name": "WikiOracle NanoChat",
            "streaming": True,
        },
    }
    if os.getenv("OPENAI_API_KEY"):
        providers["openai"] = {
            "name": "OpenAI",
            "api_key": os.getenv("OPENAI_API_KEY"),
            "default_model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "streaming": False,
        }
    if os.getenv("ANTHROPIC_API_KEY"):
        providers["anthropic"] = {
            "name": "Anthropic",
            "api_key": os.getenv("ANTHROPIC_API_KEY"),
            "default_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "streaming": False,
        }
    return providers


PROVIDERS = _build_providers()


# ---------------------------------------------------------------------------
# State I/O wrappers
# ---------------------------------------------------------------------------
def _load_state(cfg: Config, *, strict: bool = True) -> Dict[str, Any]:
    return load_state_file(
        cfg.state_file, strict=strict,
        max_bytes=cfg.max_state_bytes,
        reject_symlinks=cfg.reject_symlinks,
    )


def _save_state(cfg: Config, state: Dict[str, Any]) -> None:
    normalized = ensure_minimal_state(state, strict=True)
    normalized["date"] = utc_now_iso()
    serialized = json.dumps(normalized, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > cfg.max_state_bytes:
        raise StateValidationError("State exceeds MAX_STATE_BYTES")
    atomic_write_jsonl(cfg.state_file, normalized, reject_symlinks=cfg.reject_symlinks)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def _auth_ok(expected_token: str) -> bool:
    if not expected_token:
        return True  # No token configured = no auth required
    header = flask_request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer "):], expected_token)


# ---------------------------------------------------------------------------
# Upstream providers (v2: conversation-aware context building)
# ---------------------------------------------------------------------------
def _build_messages_for_upstream(
    state: Dict[str, Any],
    user_message: str,
    prefs: Dict[str, Any],
    conversation_id: str | None = None,
) -> List[Dict[str, str]]:
    """Build OpenAI-compatible messages array from state + new message.

    Uses the conversation tree to build context from ancestor chain.
    """
    messages: List[Dict[str, str]] = []

    # 1) Always inject context
    context_text = strip_xhtml(state.get("context", ""))
    if context_text:
        messages.append({"role": "user", "content": f"[Context] {context_text}"})
        messages.append({"role": "assistant", "content": "Understood. I have the project context."})

    # 2) Inject relevant trust entries if RAG enabled
    if prefs.get("tools", {}).get("rag", True):
        trust_entries = state.get("truth", {}).get("trust", [])
        retrieval_prefs = state.get("truth", {}).get("retrieval_prefs", {})
        max_entries = retrieval_prefs.get("max_entries", 8)
        min_certainty = retrieval_prefs.get("min_certainty", 0.0)

        relevant = [t for t in trust_entries if t.get("certainty", 0) >= min_certainty]
        relevant.sort(key=lambda t: t.get("certainty", 0), reverse=True)
        relevant = relevant[:max_entries]

        if relevant:
            trust_text = "\n".join(
                f"- [{t.get('title', 'untitled')}] (certainty: {t.get('certainty', 0):.2f}): "
                f"{strip_xhtml(t.get('content', ''))}"
                for t in relevant
            )
            messages.append({"role": "user", "content": f"[Reference Documents]\n{trust_text}"})
            messages.append({"role": "assistant", "content": "I've noted the reference documents and their certainty levels."})

    # 3) Sliding window of conversation context (ancestor chain)
    conversations = state.get("conversations", [])
    if conversation_id:
        context_msgs = get_context_messages(conversations, conversation_id)
    else:
        context_msgs = []

    window_size = prefs.get("message_window", 40)
    recent = context_msgs[-window_size:]
    for msg in recent:
        role = msg.get("role", "user")
        content = strip_xhtml(msg.get("content", ""))
        messages.append({"role": role, "content": content})

    # 4) Current user message
    messages.append({"role": "user", "content": user_message})
    return messages


def _call_nanochat(cfg: Config, messages: List[Dict], temperature: float) -> str:
    """Call NanoChat /chat/completions (SSE streaming, buffered)."""
    url = cfg.base_url + cfg.api_path
    payload = {"messages": messages, "temperature": temperature, "max_tokens": 1024}
    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"},
                         timeout=cfg.timeout_s, stream=True)
    if resp.status_code >= 400:
        return f"[Error from upstream: HTTP {resp.status_code}] {resp.text[:500]}"

    full_text = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
            if data.get("done"):
                break
            if "token" in data:
                full_text.append(data["token"])
        except json.JSONDecodeError:
            continue
    return "".join(full_text) if full_text else "[No response from upstream]"


def _call_openai(messages: List[Dict], temperature: float, provider_cfg: Dict) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": provider_cfg.get("default_model", "gpt-4o"),
        "messages": messages, "temperature": temperature, "max_tokens": 2048,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {provider_cfg['api_key']}"}
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    if resp.status_code >= 400:
        return f"[Error from OpenAI: HTTP {resp.status_code}] {resp.text[:500]}"
    return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "[No content]")


def _call_anthropic(messages: List[Dict], temperature: float, provider_cfg: Dict) -> str:
    system_text = ""
    api_messages = []
    for msg in messages:
        if msg["role"] == "user" and msg["content"].startswith("[Context]") and not api_messages:
            system_text = msg["content"]
            continue
        if msg["role"] == "assistant" and not api_messages:
            continue
        api_messages.append(msg)

    cleaned = []
    last_role = None
    for msg in api_messages:
        if msg["role"] == last_role:
            cleaned[-1]["content"] += "\n" + msg["content"]
        else:
            cleaned.append(dict(msg))
            last_role = msg["role"]
    if cleaned and cleaned[0]["role"] != "user":
        cleaned.insert(0, {"role": "user", "content": "(continuing conversation)"})

    payload: Dict[str, Any] = {
        "model": provider_cfg.get("default_model", "claude-sonnet-4-20250514"),
        "max_tokens": 2048, "messages": cleaned,
    }
    if system_text:
        payload["system"] = system_text
    if temperature > 0:
        payload["temperature"] = temperature
    headers = {
        "Content-Type": "application/json",
        "x-api-key": provider_cfg["api_key"],
        "anthropic-version": "2023-06-01",
    }
    resp = requests.post("https://api.anthropic.com/v1/messages", json=payload,
                         headers=headers, timeout=120)
    if resp.status_code >= 400:
        return f"[Error from Anthropic: HTTP {resp.status_code}] {resp.text[:500]}"
    blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or "[No content]"


def _call_provider(cfg: Config, messages: List[Dict], temperature: float, provider: str) -> str:
    if provider == "wikioracle":
        return _call_nanochat(cfg, messages, temperature)
    pcfg = PROVIDERS.get(provider)
    if not pcfg:
        return f"[Unknown provider: {provider}. Available: {', '.join(PROVIDERS.keys())}]"
    if provider == "openai":
        return _call_openai(messages, temperature, pcfg)
    if provider == "anthropic":
        return _call_anthropic(messages, temperature, pcfg)
    return f"[Provider '{provider}' not implemented]"


# ---------------------------------------------------------------------------
# Dynamic provider call (from trust entry <provider> block)
# ---------------------------------------------------------------------------
def _call_dynamic_provider(
    provider_config: dict, messages: List[Dict], temperature: float, cfg: Config,
) -> str:
    api_url = provider_config.get("api_url", "")
    raw_key = provider_config.get("api_key", "")
    model = provider_config.get("model", "")
    timeout = provider_config.get("timeout") or int(cfg.timeout_s)
    max_tokens = provider_config.get("max_tokens") or 2048

    api_key = resolve_api_key(raw_key) if raw_key else ""

    if "anthropic.com" in api_url:
        return _call_dynamic_anthropic(api_url, api_key, model, messages, temperature, timeout, max_tokens)
    elif "wikioracle.org" in api_url:
        return _call_nanochat(cfg, messages, temperature)
    else:
        return _call_dynamic_openai(api_url, api_key, model, messages, temperature, timeout, max_tokens)


def _call_dynamic_openai(
    api_url: str, api_key: str, model: str,
    messages: List[Dict], temperature: float, timeout: int, max_tokens: int,
) -> str:
    url = api_url or "https://api.openai.com/v1/chat/completions"
    payload = {"model": model or "gpt-4o", "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        return f"[Error: HTTP {resp.status_code}] {resp.text[:300]}"
    return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "[No content]")


def _call_dynamic_anthropic(
    api_url: str, api_key: str, model: str,
    messages: List[Dict], temperature: float, timeout: int, max_tokens: int,
) -> str:
    system_text = ""
    api_messages = []
    for msg in messages:
        if msg["role"] == "user" and msg["content"].startswith("[Context]") and not api_messages:
            system_text = msg["content"]
            continue
        if msg["role"] == "assistant" and not api_messages:
            continue
        api_messages.append(msg)

    cleaned = []
    last_role = None
    for msg in api_messages:
        if msg["role"] == last_role:
            cleaned[-1]["content"] += "\n" + msg["content"]
        else:
            cleaned.append(dict(msg))
            last_role = msg["role"]
    if cleaned and cleaned[0]["role"] != "user":
        cleaned.insert(0, {"role": "user", "content": "(continuing conversation)"})

    payload: Dict[str, Any] = {"model": model or "claude-sonnet-4-20250514",
                                "max_tokens": max_tokens, "messages": cleaned}
    if system_text:
        payload["system"] = system_text
    if temperature > 0:
        payload["temperature"] = temperature

    headers = {"Content-Type": "application/json",
               "x-api-key": api_key,
               "anthropic-version": "2023-06-01"}
    resp = requests.post(api_url or "https://api.anthropic.com/v1/messages",
                         json=payload, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        return f"[Error: HTTP {resp.status_code}] {resp.text[:300]}"
    blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or "[No content]"


# ---------------------------------------------------------------------------
# Fan-out orchestration
# ---------------------------------------------------------------------------
def _build_upstream_with_transient_rag(
    state: Dict[str, Any],
    user_message: str,
    prefs: Dict[str, Any],
    transient_snippets: List[Dict],
    conversation_id: str | None = None,
) -> List[Dict[str, str]]:
    """Build upstream messages including transient RAG snippets from secondary providers."""
    messages: List[Dict[str, str]] = []

    # 1) Context
    context_text = strip_xhtml(state.get("context", ""))
    if context_text:
        messages.append({"role": "user", "content": f"[Context] {context_text}"})
        messages.append({"role": "assistant", "content": "Understood. I have the project context."})

    # 2) Normal trust entries (non-provider, non-src)
    if prefs.get("tools", {}).get("rag", True):
        trust_entries = state.get("truth", {}).get("trust", [])
        retrieval_prefs = state.get("truth", {}).get("retrieval_prefs", {})
        max_entries = retrieval_prefs.get("max_entries", 8)
        min_certainty = retrieval_prefs.get("min_certainty", 0.0)

        normal = [t for t in trust_entries
                  if t.get("certainty", 0) >= min_certainty
                  and "<provider" not in t.get("content", "")
                  and "<src" not in t.get("content", "")]
        normal.sort(key=lambda t: t.get("certainty", 0), reverse=True)
        normal = normal[:max_entries]

        src_entries = get_src_entries(trust_entries)
        for entry, src_config in src_entries:
            if entry.get("certainty", 0) < min_certainty:
                continue
            try:
                content = resolve_src_content(src_config)
                if content:
                    normal.append({
                        "title": entry.get("title", src_config.get("name", "Source")),
                        "certainty": entry.get("certainty", 0),
                        "content": f"<p>{content[:4000]}</p>",
                    })
            except Exception:
                pass

        if normal:
            trust_text = "\n".join(
                f"- [{t.get('title', 'untitled')}] (certainty: {t.get('certainty', 0):.2f}): "
                f"{strip_xhtml(t.get('content', ''))}"
                for t in normal
            )
            messages.append({"role": "user", "content": f"[Reference Documents]\n{trust_text}"})
            messages.append({"role": "assistant", "content": "I've noted the reference documents and their certainty levels."})

    # 3) Transient RAG snippets from secondary providers
    if transient_snippets:
        snippet_text = "\n".join(
            f"- [{s.get('source', '?')}] (certainty: {s.get('certainty', 0):.2f}): "
            f"{s.get('content', '')[:2000]}"
            for s in transient_snippets
        )
        messages.append({"role": "user", "content": f"[Provider Consultations]\n{snippet_text}"})
        messages.append({"role": "assistant", "content": "I've reviewed the provider consultations."})

    # 4) Conversation context from ancestor chain
    conversations = state.get("conversations", [])
    if conversation_id:
        context_msgs = get_context_messages(conversations, conversation_id)
    else:
        context_msgs = []

    window_size = prefs.get("message_window", 40)
    recent = context_msgs[-window_size:]
    for msg in recent:
        role = msg.get("role", "user")
        content = strip_xhtml(msg.get("content", ""))
        messages.append({"role": role, "content": content})

    # 5) Current user message
    messages.append({"role": "user", "content": user_message})
    return messages


def _fan_out_and_aggregate(
    cfg: Config,
    state: Dict[str, Any],
    user_message: str,
    prefs: Dict[str, Any],
    conversation_id: str | None = None,
) -> tuple:
    trust_entries = state.get("truth", {}).get("trust", [])
    provider_entries = get_provider_entries(trust_entries)
    temperature = max(0.0, min(2.0, float(prefs.get("temp", 0.7))))

    if not provider_entries:
        raise ValueError("No provider trust entries found")

    primary_entry, primary_config = provider_entries[0]
    secondaries = provider_entries[1:]

    base_messages = _build_messages_for_upstream(state, user_message, prefs, conversation_id)

    transient_snippets: List[Dict] = []

    if secondaries:
        def _call_secondary(pair):
            entry, pconfig = pair
            try:
                result = _call_dynamic_provider(pconfig, base_messages, temperature, cfg)
                if result and not result.startswith("[Error"):
                    return {
                        "source": pconfig.get("name", "unknown"),
                        "certainty": entry.get("certainty", 0),
                        "content": result[:4000],
                        "timestamp": utc_now_iso(),
                    }
            except Exception:
                pass
            return None

        max_workers = min(len(secondaries), 4)
        overall_timeout = max(int(cfg.timeout_s), 60)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_call_secondary, s): s for s in secondaries}
            done, _ = concurrent.futures.wait(futures, timeout=overall_timeout)
            for fut in done:
                try:
                    result = fut.result(timeout=0)
                    if result:
                        transient_snippets.append(result)
                except Exception:
                    pass

    final_messages = _build_upstream_with_transient_rag(
        state, user_message, prefs, transient_snippets, conversation_id
    )

    response_text = _call_dynamic_provider(primary_config, final_messages, temperature, cfg)

    if response_text.startswith("[Error"):
        for entry, pconfig in secondaries:
            try:
                fallback_text = _call_dynamic_provider(pconfig, final_messages, temperature, cfg)
                if not fallback_text.startswith("[Error"):
                    return fallback_text, transient_snippets
            except Exception:
                continue

    return response_text, transient_snippets


# ---------------------------------------------------------------------------
# Merge scan
# ---------------------------------------------------------------------------
def _scan_and_merge_imports(cfg: Config) -> Dict[str, Any]:
    report: Dict[str, Any] = {"found": 0, "merged": 0, "errors": [], "files": []}
    if not cfg.auto_merge_on_start:
        return report

    state = _load_state(cfg, strict=False)
    state = ensure_minimal_state(state, strict=True)

    root = cfg.state_file.parent
    candidates = sorted(list(root.glob("llm_*.jsonl")) + list(root.glob("llm_*.json")))
    for path in candidates:
        if path.resolve() == cfg.state_file:
            continue
        if path.name.endswith(cfg.merged_suffix):
            continue
        report["found"] += 1
        try:
            incoming = load_state_file(path, strict=True)
            rewriter = None
            if cfg.auto_context_rewrite:
                rewriter = lambda ctx, deltas: build_context_draft(ctx, deltas, cfg.max_context_chars)
            merged_state, meta = merge_llm_states(state, incoming,
                                                   keep_base_context=True,
                                                   context_rewriter=rewriter)
            state = merged_state
            report["merged"] += 1
            report["files"].append({"file": path.name, **meta})
            path.rename(path.with_name(path.name + cfg.merged_suffix))
        except Exception as exc:
            report["errors"].append({"file": path.name, "error": str(exc)})

    if report["merged"] > 0:
        _save_state(cfg, state)
    return report


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------
def create_app(cfg: Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    startup_merge_report = _scan_and_merge_imports(cfg)

    # CORS
    @app.after_request
    def add_cors_headers(response):
        origin = flask_request.headers.get("Origin", "")
        if origin and origin in cfg.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True})

    @app.route("/info", methods=["GET"])
    def info():
        if not _auth_ok(cfg.shim_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            state = _load_state(cfg)
            return jsonify({
                "ok": True,
                "state_file_name": cfg.state_file.name,
                "schema": state.get("schema", SCHEMA_URL),
                "version": state.get("version", STATE_VERSION),
                "date": state.get("date"),
                "providers": list(PROVIDERS.keys()),
                "startup_merge": startup_merge_report,
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/state", methods=["GET", "POST"])
    def state_endpoint():
        if not _auth_ok(cfg.shim_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        if flask_request.method == "GET":
            try:
                state = _load_state(cfg)
                return jsonify({"state": state})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
        else:
            data = flask_request.get_json(force=True, silent=True)
            if not isinstance(data, dict):
                return jsonify({"ok": False, "error": "invalid_state"}), 400
            version = data.get("version")
            if version not in (1, 2):
                return jsonify({"ok": False, "error": "unsupported_version"}), 400
            try:
                _save_state(cfg, data)
                return jsonify({"ok": True})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/chat", methods=["POST", "OPTIONS"])
    def chat():
        if flask_request.method == "OPTIONS":
            return ("", 204)
        if not _auth_ok(cfg.shim_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        body = flask_request.get_json(force=True, silent=True) or {}
        user_msg = (body.get("message") or "").strip()
        if not user_msg:
            return jsonify({"ok": False, "error": "missing_message"}), 400

        prefs = body.get("prefs", {}) if isinstance(body.get("prefs"), dict) else {}
        provider = prefs.get("provider", "wikioracle")
        temperature = max(0.0, min(2.0, float(prefs.get("temp", 0.7))))

        # v2 conversation routing
        conversation_id = body.get("conversation_id")  # append to this conversation
        branch_from = body.get("branch_from")           # create child of this conversation

        try:
            state = _load_state(cfg)

            # Determine which conversation to use for upstream context
            context_conv_id = conversation_id or branch_from

            # Check for dynamic provider trust entries
            trust = state.get("truth", {}).get("trust", [])
            dyn_providers = get_provider_entries(trust)

            if dyn_providers:
                response_text, _transient = _fan_out_and_aggregate(
                    cfg, state, user_msg, prefs, context_conv_id
                )
                primary_entry, primary_config = dyn_providers[0]
                llm_provider_name = primary_config.get("name", "unknown")
                llm_model = primary_config.get("model", "")
            else:
                messages = _build_messages_for_upstream(state, user_msg, prefs, context_conv_id)
                response_text = _call_provider(cfg, messages, temperature, provider)
                llm_provider_name = PROVIDERS.get(provider, {}).get("name", provider)
                llm_model = prefs.get("model", PROVIDERS.get(provider, {}).get("default_model", provider))

            # Build message records
            user_content = ensure_xhtml(user_msg)
            assistant_content = ensure_xhtml(response_text)
            now = utc_now_iso()
            username = prefs.get("username", "User")
            provider_name = llm_provider_name
            model_name = llm_model
            llm_username = f"{provider_name} ({model_name})" if model_name else provider_name

            user_entry = {
                "role": "user",
                "username": username,
                "timestamp": now,
                "content": user_content,
            }
            ensure_message_id(user_entry)

            assistant_entry = {
                "role": "assistant",
                "username": llm_username,
                "timestamp": now,
                "content": assistant_content,
            }
            ensure_message_id(assistant_entry)

            conversations = state.get("conversations", [])

            if conversation_id:
                # Append to existing conversation
                add_message_to_conversation(conversations, conversation_id, user_entry)
                add_message_to_conversation(conversations, conversation_id, assistant_entry)
                state["selected_conversation"] = conversation_id
            elif branch_from:
                # Create new child conversation
                first_words = strip_xhtml(user_content)[:50]
                new_conv = {
                    "title": first_words,
                    "messages": [user_entry, assistant_entry],
                    "children": [],
                }
                ensure_conversation_id(new_conv)
                add_child_conversation(conversations, branch_from, new_conv)
                state["selected_conversation"] = new_conv["id"]
            else:
                # New root conversation
                first_words = strip_xhtml(user_content)[:50]
                new_conv = {
                    "title": first_words,
                    "messages": [user_entry, assistant_entry],
                    "children": [],
                }
                ensure_conversation_id(new_conv)
                from wikioracle_state import _normalize_conversation
                conversations.append(_normalize_conversation(new_conv))
                state["selected_conversation"] = new_conv["id"]

            state["conversations"] = conversations
            _save_state(cfg, state)

            # Reload after save to get normalized state
            state = _load_state(cfg)

            return jsonify({"ok": True, "text": response_text, "state": state})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.route("/merge", methods=["POST", "OPTIONS"])
    def merge_endpoint():
        if flask_request.method == "OPTIONS":
            return ("", 204)
        if not _auth_ok(cfg.shim_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401

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

    @app.route("/providers", methods=["GET"])
    def providers():
        if not _auth_ok(cfg.shim_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        result = {}
        for key, pcfg in PROVIDERS.items():
            result[key] = {
                "name": pcfg["name"],
                "streaming": pcfg.get("streaming", False),
                "model": pcfg.get("default_model", ""),
            }
        return jsonify({"providers": result})

    # Static file serving — all UI assets live in html/ subdirectory
    try:
        ui_dir = Path(__file__).resolve().parent / "html"
    except NameError:
        ui_dir = Path.cwd() / "html"

    @app.route("/", methods=["GET"])
    def ui_index():
        ui_path = ui_dir / "index.html"
        if ui_path.exists():
            return send_from_directory(str(ui_dir), "index.html")
        return "<h3>WikiOracle Local Shim</h3><p>index.html not found.</p>", 404

    @app.route("/<path:filename>", methods=["GET"])
    def static_files(filename):
        safe_ext = {".html", ".css", ".js", ".svg", ".png", ".ico", ".json", ".jsonl"}
        if Path(filename).suffix.lower() in safe_ext:
            fp = (ui_dir / filename).resolve()
            if fp.exists() and str(fp).startswith(str(ui_dir.resolve())):
                return send_from_directory(str(ui_dir), filename)
        return "", 404

    return app


# ---------------------------------------------------------------------------
# CLI merge
# ---------------------------------------------------------------------------
def run_cli_merge(cfg: Config, incoming_files: List[Path]) -> int:
    base = _load_state(cfg, strict=False)
    summaries: List[Dict] = []

    for file in incoming_files:
        try:
            incoming = load_state_file(file, strict=True)
            rewriter = None
            if cfg.auto_context_rewrite:
                rewriter = lambda ctx, deltas: build_context_draft(ctx, deltas, cfg.max_context_chars)
            base, meta = merge_llm_states(base, incoming,
                                           keep_base_context=True, context_rewriter=rewriter)
            summaries.append({"file": str(file), **meta})
        except Exception as exc:
            print(json.dumps({"file": str(file), "error": str(exc)}, indent=2))
            return 2

    _save_state(cfg, base)
    print(json.dumps({"ok": True, "merged": summaries, "state_file": str(cfg.state_file)}, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WikiOracle local shim")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Run Flask shim server (default)")
    merge_parser = sub.add_parser("merge", help="Merge llm_*.jsonl files into state")
    merge_parser.add_argument("incoming", nargs="+", help="incoming llm state files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()

    if args.cmd == "merge":
        incoming_files = [Path(p).expanduser().resolve() for p in args.incoming]
        return run_cli_merge(cfg, incoming_files)

    # Default: serve
    cfg.state_file.parent.mkdir(parents=True, exist_ok=True)
    if not cfg.state_file.exists():
        initial = ensure_minimal_state({}, strict=False)
        atomic_write_jsonl(cfg.state_file, initial, reject_symlinks=cfg.reject_symlinks)

    print(f"\n{'='*60}")
    print(f"  WikiOracle Local Shim")
    print(f"{'='*60}")
    print(f"  State file : {cfg.state_file}")
    print(f"  Bind       : {cfg.bind_host}:{cfg.bind_port}")
    print(f"  Providers  : {', '.join(PROVIDERS.keys())}")
    print(f"  UI         : http://{cfg.bind_host}:{cfg.bind_port}/")
    print(f"{'='*60}\n")

    app = create_app(cfg)
    app.run(host=cfg.bind_host, port=cfg.bind_port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
