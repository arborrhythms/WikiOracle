#!/usr/bin/env python3
"""WikiOracle local shim (conversation-based hierarchy).

Local-first Flask server that owns one llm.jsonl file, proxies chat to an
upstream stateless endpoint (NanoChat, OpenAI, Anthropic), and supports
deterministic merge/import of exported llm_*.jsonl files.

Usage:
    # Server mode (default)
    export WIKIORACLE_STATE_FILE="/abs/path/to/llm.jsonl"
    python WikiOracle.py

    # CLI merge mode
    python WikiOracle.py merge llm_2026.02.22.1441.jsonl llm_2026.02.23.0900.jsonl

Then open http://127.0.0.1:8787/
"""

from __future__ import annotations

import argparse
import concurrent.futures
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
    normalize_conversation,
    compute_derived_truth,
    parse_provider_block,
    resolve_api_key,
    resolve_src_content,
    strip_xhtml,
    utc_now_iso,
)
from prompt_bundle import (
    DEFAULT_OUTPUT,
    PromptBundle,
    Source,
    build_prompt_bundle,
    evaluate_providers,
    rank_retrieval_entries,
    to_anthropic_payload,
    to_nanochat_messages,
    to_openai_messages,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """Runtime configuration for the local shim process."""

    state_file: Path  # Canonical on-disk state location (ignored in stateless mode).
    base_url: str = "https://wikioracle.org"  # Upstream NanoChat-compatible base URL.
    api_path: str = "/chat/completions"  # Upstream endpoint path appended to base_url.
    bind_host: str = "127.0.0.1"  # Local interface to bind the Flask server.
    bind_port: int = 8787  # Local port for browser/UI traffic.
    timeout_s: float = 120.0  # Network timeout for provider requests.
    max_state_bytes: int = 5_000_000  # Hard upper bound for serialized state size.
    max_context_chars: int = 40_000  # Context rewrite cap for merge appendix generation.
    reject_symlinks: bool = True  # Refuse symlinked state files for safer local ownership.
    auto_merge_on_start: bool = True  # Auto-import llm_*.jsonl/.json files at startup.
    auto_context_rewrite: bool = False  # Enable delta-based context append during merges.
    merged_suffix: str = ".merged"  # Suffix applied to files after successful import.
    allowed_origins: set = field(default_factory=lambda: {
        "http://127.0.0.1:8787", "http://localhost:8787"
    })


def _env_bool(name: str, default: bool) -> bool:
    """Read a permissive boolean env var with a default fallback."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    """Build Config from environment variables with safe defaults."""
    state_file = Path(
        os.environ.get("WIKIORACLE_STATE_FILE", str(Path.cwd() / "llm.jsonl"))
    ).expanduser().resolve()

    allowed_origins_raw = os.environ.get(
        "WIKIORACLE_ALLOWED_ORIGINS",
        "http://127.0.0.1:8787,http://localhost:8787",
    )
    allowed_origins = {v.strip() for v in allowed_origins_raw.split(",") if v.strip()}

    return Config(
        state_file=state_file,
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
# config.yaml loader
# ---------------------------------------------------------------------------
_CONFIG_YAML_STATUS = ""  # human-readable load status for startup banner

def _load_config_yaml() -> Dict[str, Any]:
    """Load config.yaml from the project directory (next to WikiOracle.py)."""
    global _CONFIG_YAML_STATUS
    try:
        import yaml
    except ImportError:
        _CONFIG_YAML_STATUS = "pyyaml not installed (pip install pyyaml)"
        return {}
    cfg_path = Path(__file__).resolve().parent / "config.yaml"
    if not cfg_path.exists():
        _CONFIG_YAML_STATUS = f"not found at {cfg_path}"
        return {}
    try:
        with open(cfg_path) as f:
            data = yaml.safe_load(f) or {}
        if data:
            _CONFIG_YAML_STATUS = f"loaded ({len(data)} keys) from {cfg_path}"
        else:
            _CONFIG_YAML_STATUS = f"empty or unparseable at {cfg_path}"
        return data
    except Exception as exc:
        _CONFIG_YAML_STATUS = f"parse error: {exc}"
        return {}


_CONFIG_YAML = _load_config_yaml()



# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------
def _build_providers() -> Dict[str, Dict[str, Any]]:
    """Construct provider registry from defaults + config.yaml overrides."""
    yaml_providers = _CONFIG_YAML.get("providers", {})

    providers: Dict[str, Dict[str, Any]] = {
        "wikioracle": {
            "name": "WikiOracle NanoChat",
            "streaming": True,
        },
        "openai": {
            "name": "OpenAI",
            "url": "https://api.openai.com/v1/chat/completions",
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "default_model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "streaming": False,
        },
        "anthropic": {
            "name": "Anthropic",
            "url": "https://api.anthropic.com/v1/messages",
            "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "default_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "streaming": False,
        },
    }

    # Merge config.yaml values (YAML overrides defaults; env vars still win)
    for key, ycfg in yaml_providers.items():
        if not isinstance(ycfg, dict):
            continue
        if key not in providers:
            providers[key] = {"name": key, "streaming": False}
        pcfg = providers[key]
        if ycfg.get("name"):
            pcfg["name"] = ycfg["name"]
        if ycfg.get("username"):
            pcfg["username"] = ycfg["username"]
        if ycfg.get("url"):
            pcfg["url"] = ycfg["url"]
        if ycfg.get("default_model"):
            pcfg.setdefault("default_model", ycfg["default_model"])
        # YAML api_key fills in when no env var is set
        if ycfg.get("api_key") and not pcfg.get("api_key"):
            pcfg["api_key"] = ycfg["api_key"]

    return providers


PROVIDERS = _build_providers()


# ---------------------------------------------------------------------------
# State I/O wrappers
# ---------------------------------------------------------------------------
def _load_state(cfg: Config, *, strict: bool = True) -> Dict[str, Any]:
    """Load and validate state from cfg.state_file with configured guardrails."""
    return load_state_file(
        cfg.state_file, strict=strict,
        max_bytes=cfg.max_state_bytes,
        reject_symlinks=cfg.reject_symlinks,
    )


def _save_state(cfg: Config, state: Dict[str, Any]) -> None:
    """Normalize, size-check, and atomically persist state to disk."""
    normalized = ensure_minimal_state(state, strict=True)
    normalized["time"] = utc_now_iso()
    serialized = json.dumps(normalized, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > cfg.max_state_bytes:
        raise StateValidationError("State exceeds MAX_STATE_BYTES")
    atomic_write_jsonl(cfg.state_file, normalized, reject_symlinks=cfg.reject_symlinks)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Upstream providers
# ---------------------------------------------------------------------------
def _build_bundle(
    state: Dict[str, Any],
    user_message: str,
    prefs: Dict[str, Any],
    conversation_id: str | None = None,
    transient_snippets: List[Dict] | None = None,
) -> PromptBundle:
    """Build a PromptBundle from state + user message (convenience wrapper)."""
    return build_prompt_bundle(
        state, user_message, prefs,
        conversation_id=conversation_id,
        transient_snippets=transient_snippets,
    )


def _bundle_to_messages(bundle: PromptBundle, provider: str) -> List[Dict[str, str]]:
    """Convert a PromptBundle to provider-appropriate messages list."""
    if provider == "wikioracle":
        return to_nanochat_messages(bundle)
    elif provider == "openai":
        return to_openai_messages(bundle)
    elif provider == "anthropic":
        # For Anthropic we return OpenAI-format messages; the caller
        # uses to_anthropic_payload() directly for the full payload.
        return to_openai_messages(bundle)
    else:
        return to_openai_messages(bundle)


def _call_nanochat(cfg: Config, messages: List[Dict], temperature: float) -> str:
    """Call NanoChat /chat/completions (SSE streaming, buffered)."""
    url = cfg.base_url + cfg.api_path
    if DEBUG_MODE:
        print(f"[DEBUG] NanoChat → {url}")
        print(f"[DEBUG] NanoChat messages ({len(messages)}):")
        for i, m in enumerate(messages):
            print(f"  [{i}] {m['role']}: {m['content'][:200]}{'...' if len(m['content']) > 200 else ''}")
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
    """Call an OpenAI-compatible chat/completions endpoint and return text."""
    url = provider_cfg.get("url", "https://api.openai.com/v1/chat/completions")
    payload = {
        "model": provider_cfg.get("default_model", "gpt-4o"),
        "messages": messages, "temperature": temperature, "max_tokens": 2048,
    }
    if DEBUG_MODE:
        print(f"[DEBUG] OpenAI → {url}")
        print(f"[DEBUG] OpenAI messages ({len(messages)}):")
        for i, m in enumerate(messages):
            print(f"  [{i}] {m['role']}: {m['content'][:200]}{'...' if len(m['content']) > 200 else ''}")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {provider_cfg['api_key']}"}
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    if resp.status_code >= 400:
        return f"[Error from OpenAI: HTTP {resp.status_code}] {resp.text[:500]}"
    return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "[No content]")


def _build_anthropic_payload_from_messages(
    messages: List[Dict], model: str, max_tokens: int, temperature: float,
) -> Dict[str, Any]:
    """Build an Anthropic API payload from raw messages (shared by legacy callers).

    Extracts [Context]-prefixed first user message as system text, merges
    consecutive same-role messages, and ensures the first message is 'user'.
    """
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
        "model": model, "max_tokens": max_tokens, "messages": cleaned,
    }
    if system_text:
        payload["system"] = system_text
    if temperature > 0:
        payload["temperature"] = temperature
    return payload


def _call_anthropic(bundle: PromptBundle | None, temperature: float, provider_cfg: Dict,
                     messages: List[Dict] | None = None) -> str:
    """Call Anthropic API. Prefers bundle-based payload; falls back to legacy messages."""
    url = provider_cfg.get("url", "https://api.anthropic.com/v1/messages")

    if bundle is not None:
        payload = to_anthropic_payload(
            bundle,
            model=provider_cfg.get("default_model", "claude-sonnet-4-20250514"),
            max_tokens=2048,
            temperature=temperature,
        )
    else:
        payload = _build_anthropic_payload_from_messages(
            messages or [],
            model=provider_cfg.get("default_model", "claude-sonnet-4-20250514"),
            max_tokens=2048,
            temperature=temperature,
        )

    if DEBUG_MODE:
        print(f"[DEBUG] Anthropic → {url}")
        sys_preview = payload.get("system", "(none)")
        if isinstance(sys_preview, str) and len(sys_preview) > 200:
            sys_preview = sys_preview[:200] + "..."
        print(f"[DEBUG] Anthropic system: {sys_preview}")
        msgs = payload.get("messages", [])
        print(f"[DEBUG] Anthropic messages ({len(msgs)}):")
        for i, m in enumerate(msgs):
            print(f"  [{i}] {m['role']}: {m['content'][:200]}{'...' if len(m['content']) > 200 else ''}")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": provider_cfg["api_key"],
        "anthropic-version": "2023-06-01",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    if resp.status_code >= 400:
        return f"[Error from Anthropic: HTTP {resp.status_code}] {resp.text[:500]}"
    blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or "[No content]"


def _call_provider(cfg: Config, bundle: PromptBundle | None, temperature: float,
                    provider: str, client_api_key: str = "",
                    client_model: str = "",
                    messages: List[Dict] | None = None) -> str:
    """Call a provider using a PromptBundle (preferred) or legacy messages."""
    if provider == "wikioracle":
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_nanochat (wikioracle.org)")
        nano_msgs = to_nanochat_messages(bundle) if bundle else (messages or [])
        return _call_nanochat(cfg, nano_msgs, temperature)
    pcfg = PROVIDERS.get(provider)
    if not pcfg:
        return f"[Unknown provider: {provider}. Available: {', '.join(PROVIDERS.keys())}]"
    # Build effective config: merge client + server keys
    effective_cfg = dict(pcfg)
    if client_model:
        effective_cfg["default_model"] = client_model
    # Key precedence:
    #   Stateless mode: client key → server key (client owns state)
    #   Server mode:    server key → hot-reload → client key (server owns state)
    if STATELESS_MODE:
        if client_api_key:
            effective_cfg["api_key"] = client_api_key
        # Fall through to server key if client didn't provide one
    else:
        if not effective_cfg.get("api_key") and client_api_key:
            effective_cfg["api_key"] = client_api_key
    if not effective_cfg.get("api_key"):
        if not STATELESS_MODE:
            # Hot-reload config.yaml in case keys were added after server start
            fresh = _load_config_yaml()
            fresh_key = (fresh.get("providers", {}).get(provider) or {}).get("api_key", "")
            if fresh_key:
                effective_cfg["api_key"] = fresh_key
                # Update cached PROVIDERS so subsequent calls don't need to reload
                if provider in PROVIDERS:
                    PROVIDERS[provider]["api_key"] = fresh_key
        if not effective_cfg.get("api_key"):
            return f"[No API key for {provider}. Add it to config.yaml.]"
    if provider == "openai":
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_openai ({effective_cfg.get('url', '?')}, model={effective_cfg.get('default_model')})")
        oai_msgs = to_openai_messages(bundle) if bundle else (messages or [])
        return _call_openai(oai_msgs, temperature, effective_cfg)
    if provider == "anthropic":
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_anthropic ({effective_cfg.get('url', '?')}, model={effective_cfg.get('default_model')})")
        return _call_anthropic(bundle, temperature, effective_cfg, messages=messages)
    return f"[Provider '{provider}' not implemented]"


# ---------------------------------------------------------------------------
# Dynamic provider call (from trust entry <provider> block)
# ---------------------------------------------------------------------------
def _resolve_dynamic_api_key(raw_key: str, api_url: str) -> str:
    """Resolve a dynamic provider's API key with fallback to PROVIDERS/env vars.

    Precedence:
      1. trust entry <api_key> (env-var syntax like $ANTHROPIC_API_KEY resolved)
      2. PROVIDERS registry (matches api_url to known provider URLs)
      3. Hot-reload config.yaml (for keys added after server start)
      4. Direct env-var lookup by URL pattern
    """
    if raw_key:
        resolved = resolve_api_key(raw_key)
        if resolved:
            return resolved

    # Fallback: match api_url to a known PROVIDERS entry
    matched_provider_key = None
    if api_url:
        for _key, pcfg in PROVIDERS.items():
            prov_url = pcfg.get("url", "")
            if prov_url and (prov_url in api_url or api_url in prov_url):
                if pcfg.get("api_key"):
                    return pcfg["api_key"]
                matched_provider_key = _key
                break

    # Hot-reload config.yaml (mirrors _call_provider hot-reload logic)
    if matched_provider_key and not STATELESS_MODE:
        fresh = _load_config_yaml()
        fresh_key = (fresh.get("providers", {}).get(matched_provider_key) or {}).get("api_key", "")
        if fresh_key:
            # Cache so subsequent calls don't need to reload
            if matched_provider_key in PROVIDERS:
                PROVIDERS[matched_provider_key]["api_key"] = fresh_key
            return fresh_key

    # Last resort: try env vars directly by URL pattern
    if api_url:
        if "anthropic.com" in api_url:
            return os.getenv("ANTHROPIC_API_KEY", "")
        if "openai.com" in api_url:
            return os.getenv("OPENAI_API_KEY", "")
    return ""


def _call_dynamic_provider(
    provider_config: dict, messages: List[Dict], temperature: float, cfg: Config,
) -> str:
    """Route a trust-entry provider config to Anthropic, NanoChat, or OpenAI path."""
    api_url = provider_config.get("api_url", "")
    raw_key = provider_config.get("api_key", "")
    model = provider_config.get("model", "")
    timeout = provider_config.get("timeout") or int(cfg.timeout_s)
    max_tokens = provider_config.get("max_tokens") or 2048

    api_key = _resolve_dynamic_api_key(raw_key, api_url)

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
    """Call a dynamic OpenAI-compatible endpoint from a <provider> trust entry."""
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
    """Call a dynamic Anthropic endpoint from a <provider> trust entry."""
    payload = _build_anthropic_payload_from_messages(
        messages,
        model=model or "claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        temperature=temperature,
    )
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
def _fan_out_and_aggregate(
    cfg: Config,
    state: Dict[str, Any],
    user_message: str,
    prefs: Dict[str, Any],
    conversation_id: str | None = None,
    temperature: float = 0.7,
) -> tuple:
    """HME fan-out: evaluate secondary providers, feed results to primary.

    1. Build a base bundle (with RAG, without provider sources).
    2. Evaluate all secondary <provider> entries in parallel with a
       RAG-free bundle — each gets system, history, query, output only.
    3. Their responses become Source(kind="provider") entries wrapped
       in <div class="provider-response">.
    4. Rebuild the final bundle with those provider sources included.
    5. Send to primary provider (mastermind).
    """
    trust_entries = state.get("truth", {}).get("trust", [])
    provider_entries = get_provider_entries(trust_entries)

    if not provider_entries:
        raise ValueError("No provider trust entries found")

    primary_entry, primary_config = provider_entries[0]
    secondaries = provider_entries[1:]

    # Build a preliminary bundle to extract system/history/query/output
    base_bundle = _build_bundle(state, user_message, prefs, conversation_id)

    # Evaluate secondaries: each gets a RAG-free bundle
    provider_sources: List[Source] = []
    if secondaries:
        def _call_for_eval(pconfig, messages):
            """Adapter used by evaluate_providers for secondary fan-out calls."""
            return _call_dynamic_provider(pconfig, messages, temperature, cfg)

        provider_sources = evaluate_providers(
            secondaries,
            system=base_bundle.system,
            history=base_bundle.history,
            query=base_bundle.query,
            output=base_bundle.output,
            call_fn=_call_for_eval,
            timeout_s=max(int(cfg.timeout_s), 60),
        )

    # Build the final bundle: RAG sources + provider HME sources
    final_bundle = build_prompt_bundle(
        state, user_message, prefs,
        conversation_id=conversation_id,
        provider_sources=provider_sources,
    )

    # Route to primary provider using appropriate adapter
    api_url = primary_config.get("api_url", "")
    if "anthropic.com" in api_url:
        model = primary_config.get("model", "claude-sonnet-4-20250514")
        max_tokens = primary_config.get("max_tokens") or 2048
        payload = to_anthropic_payload(final_bundle, model=model,
                                       max_tokens=max_tokens, temperature=temperature)
        raw_key = primary_config.get("api_key", "")
        api_key = _resolve_dynamic_api_key(raw_key, api_url)
        timeout = primary_config.get("timeout") or int(cfg.timeout_s)
        headers = {"Content-Type": "application/json",
                   "x-api-key": api_key,
                   "anthropic-version": "2023-06-01"}
        resp = requests.post(api_url or "https://api.anthropic.com/v1/messages",
                        json=payload, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            response_text = f"[Error: HTTP {resp.status_code}] {resp.text[:300]}"
        else:
            blocks = resp.json().get("content", [])
            response_text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or "[No content]"
    else:
        # OpenAI-compatible or NanoChat: use nanochat messages (works for both)
        final_messages = to_nanochat_messages(final_bundle)
        response_text = _call_dynamic_provider(primary_config, final_messages, temperature, cfg)

    # Fallback to secondaries if primary fails
    if response_text.startswith("[Error"):
        fallback_messages = to_nanochat_messages(final_bundle)
        for entry, pconfig in secondaries:
            try:
                fallback_text = _call_dynamic_provider(pconfig, fallback_messages, temperature, cfg)
                if not fallback_text.startswith("[Error"):
                    return fallback_text, provider_sources
            except Exception:
                continue

    return response_text, provider_sources


# ---------------------------------------------------------------------------
# Merge scan
# ---------------------------------------------------------------------------
def _scan_and_merge_imports(cfg: Config) -> Dict[str, Any]:
    """Auto-merge import candidates beside state_file and emit a merge report."""
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
def create_app(cfg: Config, url_prefix: str = "") -> Flask:
    """Create and configure the WikiOracle Flask application instance."""
    app = Flask(__name__, static_folder=None)
    startup_merge_report = _scan_and_merge_imports(cfg) if not STATELESS_MODE else {}

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
            "script-src 'self' https://d3js.org; "
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
            "stateless": STATELESS_MODE,
            "url_prefix": url_prefix,
        })

    @app.route(url_prefix + "/bootstrap", methods=["GET"])
    def bootstrap():
        """One-shot seed for stateless clients: state + config from disk.

        Intended to be called once per session when the client has no
        sessionStorage copy.  Returns everything the client needs to
        operate independently of the server's disk files.
        """
        result: Dict[str, Any] = {}

        # Seed state from disk (or empty minimal state)
        try:
            seed_state = _load_state(cfg)
        except Exception:
            seed_state = ensure_minimal_state({}, strict=False)
        result["state"] = seed_state

        # Config YAML text + parsed + prefs
        cfg_path = Path(__file__).resolve().parent / "config.yaml"
        config_yaml = ""
        if cfg_path.exists():
            try:
                config_yaml = cfg_path.read_text(encoding="utf-8")
            except Exception:
                pass
        result["config_yaml"] = config_yaml

        parsed: Dict[str, Any] = {}
        try:
            import yaml
            parsed = yaml.safe_load(config_yaml) or {}
        except Exception:
            pass
        result["parsed"] = parsed
        result["prefs"] = _derive_prefs(parsed)

        # Provider metadata (non-secret)
        prov_meta = {}
        for key, pcfg in PROVIDERS.items():
            needs_key = key not in ("wikioracle",)
            prov_meta[key] = {
                "name": pcfg["name"],
                "streaming": pcfg.get("streaming", False),
                "model": pcfg.get("default_model", ""),
                "has_key": bool(pcfg.get("api_key")) or not needs_key,
                "needs_key": needs_key,
            }
        result["providers"] = prov_meta

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
        global _MEMORY_STATE

        if flask_request.method == "GET":
            try:
                if STATELESS_MODE and _MEMORY_STATE is not None:
                    return jsonify({"state": _MEMORY_STATE})
                state = _load_state(cfg)
                if STATELESS_MODE:
                    _MEMORY_STATE = state
                return jsonify({"state": state})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400
        else:
            data = flask_request.get_json(force=True, silent=True)
            if not isinstance(data, dict):
                return jsonify({"ok": False, "error": "invalid_state"}), 400
            if STATELESS_MODE:
                # Update in-memory state without writing to disk
                _MEMORY_STATE = data
                return jsonify({"ok": True})
            try:
                _save_state(cfg, data)
                return jsonify({"ok": True})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route(url_prefix + "/chat", methods=["POST", "OPTIONS"])
    def chat():
        """Process a chat turn, update conversation state, and return reply text."""
        if flask_request.method == "OPTIONS":
            return ("", 204)


        body = flask_request.get_json(force=True, silent=True) or {}
        user_msg = (body.get("message") or "").strip()
        if not user_msg:
            return jsonify({"ok": False, "error": "missing_message"}), 400

        # ── Stateless mode: client must supply state + runtime_config ──
        if STATELESS_MODE:
            if not isinstance(body.get("state"), dict):
                return jsonify({"ok": False, "error": "stateless_missing_state"}), 400
            if not isinstance(body.get("runtime_config"), dict):
                return jsonify({"ok": False, "error": "stateless_missing_runtime_config"}), 400

        prefs = body.get("prefs", {}) if isinstance(body.get("prefs"), dict) else {}

        # Config source: request payload (stateless) or disk (stateful)
        if STATELESS_MODE:
            runtime_cfg = body["runtime_config"]
            yaml_chat = runtime_cfg.get("chat", {})
        else:
            global _CONFIG_YAML
            fresh = _load_config_yaml()
            if fresh:
                _CONFIG_YAML = fresh
            runtime_cfg = _CONFIG_YAML
            yaml_chat = _CONFIG_YAML.get("chat", {})

        provider = prefs.get("provider", "wikioracle")
        client_model = (prefs.get("model") or "").strip()
        print(f"[WikiOracle] Chat request: provider='{provider}' (from client prefs)")

        # Priority: per-request prefs > config.yaml defaults
        temperature = max(0.0, min(2.0, float(
            prefs.get("temp", yaml_chat.get("temperature", 0.7))
        )))
        if "tools" not in prefs:
            prefs["tools"] = {}
        prefs["tools"].setdefault("rag", yaml_chat.get("rag", True))
        prefs["tools"].setdefault("url_fetch", yaml_chat.get("url_fetch", False))
        prefs.setdefault("message_window", yaml_chat.get("message_window", 40))
        prefs.setdefault("retrieval", yaml_chat.get("retrieval", {}))

        # Conversation routing
        conversation_id = body.get("conversation_id")  # append to this conversation
        branch_from = body.get("branch_from")           # create child of this conversation

        try:
            if STATELESS_MODE:
                # Client-supplied state is authoritative — no disk/memory reads.
                import copy
                state = copy.deepcopy(body["state"])
                state = ensure_minimal_state(state, strict=False)
            else:
                state = _load_state(cfg)
            user_timestamp = utc_now_iso()

            # Determine which conversation to use for upstream context
            context_conv_id = conversation_id or branch_from

            # Compute derived truth via Kleene implication engine
            trust = state.get("truth", {}).get("trust", [])
            derived = compute_derived_truth(trust)
            for entry in trust:
                eid = entry.get("id", "")
                if eid in derived and abs(derived[eid] - entry.get("certainty", 0.0)) > 1e-9:
                    entry["_derived_certainty"] = derived[eid]

            # Check for dynamic provider trust entries
            dyn_providers = get_provider_entries(trust)

            if dyn_providers:
                primary_entry, primary_config = dyn_providers[0]
                print(f"[WikiOracle] Chat: using DYNAMIC provider '{primary_config.get('name')}' "
                      f"(from trust entry), secondaries={len(dyn_providers)-1}")
                response_text, _transient = _fan_out_and_aggregate(
                    cfg, state, user_msg, prefs, context_conv_id,
                    temperature=temperature,
                )
                # Store secondary provider responses as persistent trust entries
                if _transient:
                    trust_list = state.get("truth", {}).get("trust", [])
                    for src in _transient:
                        trust_list.append({
                            "type": "trust",
                            "id": src.source_id + "_resp_" + utc_now_iso().replace(":", "").replace("-", "")[:15],
                            "title": f"{src.title} response",
                            "certainty": src.certainty,
                            "content": ensure_xhtml(src.content),
                            "time": utc_now_iso(),
                        })
                    if "truth" not in state:
                        state["truth"] = {"trust": trust_list}
                    else:
                        state["truth"]["trust"] = trust_list
                # Recompute derived truth after HME added secondary responses
                derived = compute_derived_truth(state.get("truth", {}).get("trust", []))
                for entry in state.get("truth", {}).get("trust", []):
                    eid = entry.get("id", "")
                    if eid in derived and abs(derived[eid] - entry.get("certainty", 0.0)) > 1e-9:
                        entry["_derived_certainty"] = derived[eid]

                llm_provider_name = primary_config.get("name", "unknown")
                llm_model = primary_config.get("model", "")
            else:
                context_text = strip_xhtml(state.get("context", ""))
                print(f"[WikiOracle] Chat: provider='{provider}', model='{client_model or PROVIDERS.get(provider, {}).get('default_model', '?')}', "
                      f"context={'yes' if context_text else 'none'} ({len(context_text)} chars), "
                      f"api_key={'server' if PROVIDERS.get(provider, {}).get('api_key') else 'MISSING'}")
                bundle = _build_bundle(state, user_msg, prefs, context_conv_id)
                if DEBUG_MODE:
                    # Show what the bundle contains
                    print(f"[DEBUG] PromptBundle: system={len(bundle.system)} chars, "
                          f"history={len(bundle.history)} msgs, "
                          f"sources={len(bundle.sources)}, query={len(bundle.query)} chars")
                    msgs = _bundle_to_messages(bundle, provider)
                    print(f"[DEBUG] Upstream messages ({len(msgs)} total):")
                    for i, m in enumerate(msgs):
                        role = m.get("role", "?")
                        content = m.get("content", "")
                        print(f"  [{i}] {role}: {content[:200]}{'...' if len(content) > 200 else ''}")
                # In stateless mode, resolve API key from runtime_config
                client_api_key = ""
                if STATELESS_MODE:
                    rc_providers = runtime_cfg.get("providers", {})
                    rc_pcfg = rc_providers.get(provider, {})
                    client_api_key = rc_pcfg.get("api_key", "")
                response_text = _call_provider(cfg, bundle, temperature, provider, client_api_key, client_model)
                if DEBUG_MODE:
                    print(f"[DEBUG] ← Response ({len(response_text)} chars): {response_text[:120]}...")
                llm_provider_name = PROVIDERS.get(provider, {}).get("name", provider)
                llm_model = prefs.get("model", PROVIDERS.get(provider, {}).get("default_model", provider))

            # Build message records
            user_content = ensure_xhtml(user_msg)
            assistant_content = ensure_xhtml(response_text)
            assistant_timestamp = utc_now_iso()
            user_display = runtime_cfg.get("user", {}).get("name", "User")
            llm_display = llm_provider_name  # provider.name from YAML

            query_entry = {
                "role": "user",
                "username": user_display,
                "time": user_timestamp,
                "content": user_content,
            }
            ensure_message_id(query_entry)

            response_entry = {
                "role": "assistant",
                "username": llm_display,
                "time": assistant_timestamp,
                "content": assistant_content,
            }
            ensure_message_id(response_entry)

            conversations = state.get("conversations", [])

            # In stateless mode the client already added the query
            # to state before sending — server only appends the response.
            client_owns_query = STATELESS_MODE

            if conversation_id:
                # Append to existing conversation
                if not client_owns_query:
                    add_message_to_conversation(conversations, conversation_id, query_entry)
                add_message_to_conversation(conversations, conversation_id, response_entry)
                state["selected_conversation"] = conversation_id
            elif branch_from:
                if client_owns_query:
                    # Client already created the optimistic conversation;
                    # find it and append the response.
                    parent = find_conversation(conversations, branch_from)
                    opt = parent["children"][-1] if parent and parent.get("children") else None
                    if opt:
                        opt["messages"].append(response_entry)
                        state["selected_conversation"] = opt["id"]
                    else:
                        # Defensive: client didn't add it — create normally
                        first_words = strip_xhtml(user_content)[:50]
                        new_conv = {
                            "title": first_words,
                            "messages": [query_entry, response_entry],
                            "children": [],
                        }
                        ensure_conversation_id(new_conv)
                        add_child_conversation(conversations, branch_from, new_conv)
                        state["selected_conversation"] = new_conv["id"]
                else:
                    # Stateful: server creates the child conversation
                    first_words = strip_xhtml(user_content)[:50]
                    new_conv = {
                        "title": first_words,
                        "messages": [query_entry, response_entry],
                        "children": [],
                    }
                    ensure_conversation_id(new_conv)
                    add_child_conversation(conversations, branch_from, new_conv)
                    state["selected_conversation"] = new_conv["id"]
            else:
                if client_owns_query:
                    # Client already pushed the optimistic root; find it
                    # and append the response.
                    opt = conversations[-1] if conversations else None
                    if opt and len(opt.get("messages", [])) == 1 and opt["messages"][0].get("_pending"):
                        opt["messages"][0].pop("_pending", None)
                        opt["messages"].append(response_entry)
                        state["selected_conversation"] = opt["id"]
                    else:
                        # Defensive fallback
                        first_words = strip_xhtml(user_content)[:50]
                        new_conv = {
                            "title": first_words,
                            "messages": [query_entry, response_entry],
                            "children": [],
                        }
                        ensure_conversation_id(new_conv)
                        conversations.append(normalize_conversation(new_conv))
                        state["selected_conversation"] = new_conv["id"]
                else:
                    # Stateful: server creates the root conversation
                    first_words = strip_xhtml(user_content)[:50]
                    new_conv = {
                        "title": first_words,
                        "messages": [query_entry, response_entry],
                        "children": [],
                    }
                    ensure_conversation_id(new_conv)
                    conversations.append(normalize_conversation(new_conv))
                    state["selected_conversation"] = new_conv["id"]

            state["conversations"] = conversations

            if not STATELESS_MODE:
                _save_state(cfg, state)
                # Reload after save to get normalized state
                state = _load_state(cfg)
            # In stateless mode, return the updated state directly to the
            # client without any server-side persistence (client owns state).

            return jsonify({"ok": True, "text": response_text, "state": state})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.route(url_prefix + "/merge", methods=["POST", "OPTIONS"])
    def merge_endpoint():
        """Merge imported state payloads/files into the canonical local state."""
        if flask_request.method == "OPTIONS":
            return ("", 204)
        if STATELESS_MODE:
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

    def _derive_prefs(cfg: dict) -> dict:
        """Derive the flat UI prefs dict from a parsed config.yaml dict."""
        ui = cfg.get("ui", {}) if isinstance(cfg, dict) else {}
        chat = cfg.get("chat", {}) if isinstance(cfg, dict) else {}
        user = cfg.get("user", {}) if isinstance(cfg, dict) else {}
        return {
            "provider": ui.get("default_provider", "wikioracle"),
            "layout": ui.get("layout", "flat"),
            "username": user.get("name", "User"),
            "chat": {
                "temperature": chat.get("temperature", 0.7),
                "message_window": chat.get("message_window", 40),
                "rag": chat.get("rag", True),
                "url_fetch": chat.get("url_fetch", False),
                "confirm_actions": chat.get("confirm_actions", False),
            },
            "theme": ui.get("theme", "system"),
        }

    @app.route(url_prefix + "/parse_config", methods=["POST", "OPTIONS"])
    def parse_config_endpoint():
        """Parse raw YAML text and return parsed dict + derived prefs.  No disk writes."""
        if flask_request.method == "OPTIONS":
            return ("", 204)
        try:
            import yaml
        except ImportError:
            return jsonify({"ok": False, "error": "pyyaml not installed"}), 500
        body = flask_request.get_json(force=True, silent=True) or {}
        raw = body.get("yaml", "")
        if not isinstance(raw, str):
            return jsonify({"ok": False, "error": "yaml must be a string"}), 400
        try:
            parsed = yaml.safe_load(raw)
            if parsed is not None and not isinstance(parsed, dict):
                return jsonify({"ok": False, "error": "config.yaml must be a YAML mapping"}), 400
            parsed = parsed or {}
        except yaml.YAMLError as exc:
            return jsonify({"ok": False, "error": f"YAML parse error: {exc}"}), 400
        return jsonify({"ok": True, "parsed": parsed, "prefs": _derive_prefs(parsed)})

    @app.route(url_prefix + "/config", methods=["GET", "POST"])
    def config_endpoint():
        """GET: serve raw config.yaml text + parsed + prefs.  POST: overwrite config.yaml."""
        global _CONFIG_YAML
        try:
            import yaml
        except ImportError:
            return jsonify({"ok": False, "error": "pyyaml not installed"}), 500
        cfg_path = Path(__file__).resolve().parent / "config.yaml"

        if flask_request.method == "GET":
            if not cfg_path.exists():
                return jsonify({"ok": True, "yaml": "", "parsed": {}, "prefs": _derive_prefs({})})
            try:
                raw_text = cfg_path.read_text(encoding="utf-8")
                parsed = yaml.safe_load(raw_text) or {}
                return jsonify({"ok": True, "yaml": raw_text, "parsed": parsed, "prefs": _derive_prefs(parsed)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500
        else:
            if STATELESS_MODE:
                return jsonify({"ok": False, "error": "Server is in stateless mode — writes disabled"}), 403
            # POST: save new YAML content
            body = flask_request.get_json(force=True, silent=True) or {}
            new_yaml = body.get("yaml", "")
            if not isinstance(new_yaml, str):
                return jsonify({"ok": False, "error": "yaml must be a string"}), 400
            # Validate it parses
            try:
                parsed = yaml.safe_load(new_yaml)
                if parsed is not None and not isinstance(parsed, dict):
                    return jsonify({"ok": False, "error": "config.yaml must be a YAML mapping"}), 400
                parsed = parsed or {}
            except yaml.YAMLError as exc:
                return jsonify({"ok": False, "error": f"YAML parse error: {exc}"}), 400
            try:
                cfg_path.write_text(new_yaml, encoding="utf-8")
                # Hot-reload the in-memory config AND rebuild providers
                _CONFIG_YAML = _load_config_yaml()
                PROVIDERS.clear()
                PROVIDERS.update(_build_providers())
                return jsonify({"ok": True, "parsed": parsed, "prefs": _derive_prefs(parsed)})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route(url_prefix + "/spec_defaults", methods=["GET"])
    def spec_defaults_endpoint():
        """Serve spec defaults for reset buttons (context, output, config.yaml)."""
        result: Dict[str, str] = {
            "context": "<div/>",
            "output": DEFAULT_OUTPUT,
            "config_yaml": "",
        }
        spec_cfg = Path(__file__).resolve().parent / "spec" / "config.yaml"
        if spec_cfg.exists():
            try:
                result["config_yaml"] = spec_cfg.read_text(encoding="utf-8")
            except Exception:
                pass
        return jsonify(result)

    @app.route(url_prefix + "/providers", methods=["GET"])
    def providers():
        """Expose non-secret provider metadata for UI model selectors."""

        result = {}
        for key, pcfg in PROVIDERS.items():
            # WikiOracle (NanoChat) never needs a client-side key
            needs_key = key not in ("wikioracle",)
            result[key] = {
                "name": pcfg["name"],
                "streaming": pcfg.get("streaming", False),
                "model": pcfg.get("default_model", ""),
                "has_key": bool(pcfg.get("api_key")) or not needs_key,
                "needs_key": needs_key,
            }
        return jsonify({"providers": result})

    @app.route(url_prefix + "/prefs", methods=["GET", "POST"])
    def prefs_endpoint():
        """Serve UI preferences from config.yaml (all prefs live in YAML now)."""
        global _CONFIG_YAML

        # Re-read config.yaml to pick up hot-reloads
        fresh = _load_config_yaml()
        if fresh:
            _CONFIG_YAML = fresh

        if flask_request.method == "GET":
            return jsonify({"prefs": _derive_prefs(_CONFIG_YAML)})
        else:
            if STATELESS_MODE:
                return jsonify({"ok": False, "error": "Server is in stateless mode — writes disabled"}), 403
            # POST: update config.yaml with new pref values
            body = flask_request.get_json(force=True, silent=True) or {}
            try:
                import yaml
                cfg_path = Path(__file__).resolve().parent / "config.yaml"
                raw = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
                data = yaml.safe_load(raw) or {}

                if "username" in body:
                    data.setdefault("user", {})["name"] = body["username"]
                if "provider" in body:
                    data.setdefault("ui", {})["default_provider"] = body["provider"]
                if "layout" in body:
                    data.setdefault("ui", {})["layout"] = body["layout"]
                if "theme" in body:
                    data.setdefault("ui", {})["theme"] = body["theme"]
                    # Remove legacy css key if present
                    if "css" in data.get("ui", {}):
                        del data["ui"]["css"]
                if "chat" in body and isinstance(body["chat"], dict):
                    chat_sec = data.setdefault("chat", {})
                    for key in ("temperature", "message_window", "rag", "url_fetch", "confirm_actions"):
                        if key in body["chat"]:
                            chat_sec[key] = body["chat"][key]

                cfg_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
                _CONFIG_YAML = _load_config_yaml()
                PROVIDERS.clear()
                PROVIDERS.update(_build_providers())
                return jsonify({"ok": True})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

    # Static file serving — all UI assets live in html/ subdirectory
    try:
        ui_dir = Path(__file__).resolve().parent / "html"
    except NameError:
        ui_dir = Path.cwd() / "html"

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
# CLI merge
# ---------------------------------------------------------------------------
def run_cli_merge(cfg: Config, incoming_files: List[Path]) -> int:
    """CLI path: merge one or more incoming state files and persist result."""
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
DEBUG_MODE = False
STATELESS_MODE = False
_MEMORY_STATE = None  # In-memory state for stateless mode (persists across requests)

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for serve/merge execution modes."""
    parser = argparse.ArgumentParser(description="WikiOracle local shim")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--stateless", action="store_true",
                        help="Run in stateless mode (no writes to disk; editors disabled)")
    parser.add_argument("--url-prefix", default="",
                        help="URL path prefix (e.g. /chat) for reverse-proxy deployments")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Run Flask shim server (default)")
    merge_parser = sub.add_parser("merge", help="Merge llm_*.jsonl files into state")
    merge_parser.add_argument("incoming", nargs="+", help="incoming llm state files")
    return parser.parse_args()


def main() -> int:
    """Entrypoint for server startup and one-shot CLI merge execution."""
    global DEBUG_MODE, STATELESS_MODE
    args = parse_args()
    DEBUG_MODE = args.debug
    STATELESS_MODE = args.stateless or _env_bool("WIKIORACLE_STATELESS", False)
    cfg = load_config()

    if args.cmd == "merge":
        incoming_files = [Path(p).expanduser().resolve() for p in args.incoming]
        return run_cli_merge(cfg, incoming_files)

    # Default: serve
    url_prefix = (args.url_prefix or os.environ.get("WIKIORACLE_URL_PREFIX", "")).strip().rstrip("/")

    if not STATELESS_MODE:
        cfg.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not cfg.state_file.exists():
            initial = ensure_minimal_state({}, strict=False)
            atomic_write_jsonl(cfg.state_file, initial, reject_symlinks=cfg.reject_symlinks)

    print(f"\n{'='*60}")
    print(f"  WikiOracle Local Shim")
    print(f"{'='*60}")
    print(f"  State file : {cfg.state_file}{' (STATELESS — no writes)' if STATELESS_MODE else ''}")
    print(f"  Bind       : {cfg.bind_host}:{cfg.bind_port}")
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
    print(f"  Stateless  : {'ON' if STATELESS_MODE else 'off'}")
    print(f"  Debug      : {'ON' if DEBUG_MODE else 'off'}")
    print(f"  UI         : http://{cfg.bind_host}:{cfg.bind_port}{url_prefix}/")
    print(f"{'='*60}\n")

    app = create_app(cfg, url_prefix=url_prefix)
    app.run(host=cfg.bind_host, port=cfg.bind_port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
