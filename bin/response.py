"""WikiOracle response pipeline: ProviderBundle, provider adapters, and chat processing.

Response generation and provider coordination:
  - ProviderBundle data model for managing multiple LLM providers
  - Provider adapter implementations for various API backends
  - Prompt assembly and context injection
  - process_chat orchestration for concurrent provider calls
"""

from __future__ import annotations

import concurrent.futures
import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

from config import Config, DEBUG_MODE, PROVIDERS, STATELESS_MODE, _load_config_yaml, _PROVIDER_MODELS
from truth import (
    compute_derived_truth,
    ensure_xhtml,
    get_authority_entries,
    get_provider_entries,
    get_src_entries,
    resolve_api_key,
    resolve_authority_entries,
    resolve_src_content,
    strip_xhtml,
    utc_now_iso,
)
from state import (
    add_child_conversation,
    add_message_to_conversation,
    build_context_draft,
    ensure_conversation_id,
    ensure_message_id,
    ensure_minimal_state,
    find_conversation,
    get_context_messages,
    load_state_file,
    merge_llm_states,
    normalize_conversation,
    atomic_write_jsonl,
)


# ---------------------------------------------------------------------------
# ProviderBundle data model
# ---------------------------------------------------------------------------
@dataclass
class Source:
    """A single retrieved trust entry with certainty score."""
    source_id: str  # Stable entry identifier used for traceability.
    title: str  # Human-readable source label shown to the model/user.
    certainty: float  # Confidence score used in ranking/display.
    content: str  # Plaintext/XHTML snippet injected into prompts.
    kind: str = "fact"          # "fact" | "provider" | "src" | "url" | "transient"
    time: str = ""


@dataclass
class ProviderBundle:
    """Provider-agnostic request object built once per chat request.

    Fields:
        system:   global instructions / context (goes in system message)
        history:  conversation messages from ancestor chain, windowed
        sources:  trust entries with certainty scores
        query:    current user message
        output:   short instruction describing the output format
    """
    system: str = ""  # Global instructions/context.
    history: List[Dict[str, str]] = field(default_factory=list)  # Prior turns on active path.
    sources: List[Source] = field(default_factory=list)  # Ranked retrieval evidence.
    transient_sources: List[Source] = field(default_factory=list)  # Legacy ad hoc provider snippets.
    query: str = ""  # Current user message.
    output: str = ""  # Output-format guidance appended to prompts.


# ---------------------------------------------------------------------------
# Certainty-aware retrieval ranking
# ---------------------------------------------------------------------------
def rank_retrieval_entries(
    trust_entries: List[Dict[str, Any]],
    retrieval_prefs: Dict[str, Any],
    *,
    exclude_providers: bool = True,
    exclude_srcs: bool = True,
) -> List[Dict[str, Any]]:
    """Rank and filter trust entries by |certainty| (Kleene ternary logic).

    Certainty range is [-1, 1]:  +1 = true, 0 = ignorance (inert), -1 = false.
    Entries with |certainty| below min_certainty are dropped (ignorance zone).
    Remaining entries are ranked by |certainty| descending, then timestamp, then id.
    Returns at most max_entries.
    """
    max_entries = retrieval_prefs.get("max_entries", 8)
    min_certainty = retrieval_prefs.get("min_certainty", 0.0)

    candidates = []
    for entry in trust_entries:
        # Use derived certainty (from implication engine) when available
        certainty = entry.get("_derived_certainty", entry.get("certainty", 0))
        if abs(certainty) < min_certainty:
            continue
        content = entry.get("content", "")
        if exclude_providers and "<provider" in content:
            continue
        if exclude_srcs and "<src" in content:
            continue
        # Implication and authority entries are structural, not content — exclude from RAG
        if "<implication" in content:
            continue
        if "<authority" in content:
            continue

        # Rank by |certainty| (both strong belief and strong disbelief are relevant)
        score = abs(certainty)
        ts = entry.get("time", "")
        candidates.append((score, ts, entry.get("id", ""), entry))

    # Sort: highest |certainty| first, then by timestamp and id for determinism
    candidates.sort(key=lambda t: (-t[0], t[1] if t[1] else "", t[2]))

    return [c[3] for c in candidates[:max_entries]]


# ---------------------------------------------------------------------------
# HME: evaluate <provider> entries
# ---------------------------------------------------------------------------
def _build_provider_query_bundle(
    system: str,
    history: List[Dict[str, str]],
    query: str,
    output: str,
) -> ProviderBundle:
    """Build a RAG-free bundle for a secondary provider consultation.

    The provider sees system context, history, the query, and the output
    instructions — but NO sources (no RAG).  This keeps the secondary
    providers independent so the mastermind can weigh their opinions.
    """
    return ProviderBundle(
        system=system,
        history=list(history),
        sources=[],
        transient_sources=[],
        query=query,
        output=output,
    )


def evaluate_providers(
    provider_entries: List[tuple],
    system: str,
    history: List[Dict[str, str]],
    query: str,
    output: str,
    call_fn: Callable[[dict, List[Dict[str, str]]], str],
    *,
    timeout_s: int = 60,
) -> List[Source]:
    """Evaluate <provider> trust entries by sending each a RAG-free bundle.

    Args:
        provider_entries: list of (trust_entry, provider_config) pairs
                          as returned by get_provider_entries().
        system:   system context string (from state.context).
        history:  windowed conversation history.
        query:    the current user message.
        output:   structured output instructions.
        call_fn:  callable(provider_config, messages) -> str
                  Caller-supplied function that calls the provider API.
        timeout_s:  per-provider wall-clock timeout.

    Returns:
        List of Source objects with kind="provider", whose content is
        a <div> wrapping the provider's response text.
    """
    if not provider_entries:
        return []

    query_bundle = _build_provider_query_bundle(
        system, history, query, output,
    )
    messages = to_nanochat_messages(query_bundle)

    results: List[Source] = []

    def _evaluate_one(pair):
        """Evaluate one provider entry and convert output to a Source object."""
        entry, pconfig = pair
        try:
            response = call_fn(pconfig, messages)
            if response and not response.startswith("[Error"):
                pname = pconfig.get("name", "")
                return Source(
                    source_id=entry.get("id", ""),
                    title=pname,
                    certainty=entry.get("certainty", 0),
                    content=(
                        f'<div class="provider-response" '
                        f'data-provider="{pname}">'
                        f'{response[:4000]}</div>'
                    ),
                    kind="provider",
                    time=entry.get("time", ""),
                )
        except Exception:
            pass
        return None

    if len(provider_entries) == 1:
        r = _evaluate_one(provider_entries[0])
        if r:
            results.append(r)
    else:
        max_workers = min(len(provider_entries), 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_evaluate_one, p): p for p in provider_entries}
            done, _ = concurrent.futures.wait(futures, timeout=timeout_s)
            for fut in done:
                try:
                    r = fut.result(timeout=0)
                    if r:
                        results.append(r)
                except Exception:
                    pass

    return results


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------
def build_prompt_bundle(
    state: Dict[str, Any],
    user_message: str,
    query_config: Dict[str, Any],
    conversation_id: Optional[str] = None,
    transient_snippets: Optional[List[Dict]] = None,
    *,
    strip_xhtml_fn=None,
    get_context_messages_fn=None,
    get_src_entries_fn=None,
    resolve_src_content_fn=None,
    provider_sources: Optional[List[Source]] = None,
) -> ProviderBundle:
    """Build a canonical ProviderBundle from state + user message.

    This is the single entry point for all providers. The bundle captures:
    - system: cleaned context text (project constraints, formatting rules)
    - history: windowed conversation messages from ancestor chain
    - sources: ranked trust entries with certainty scores
    - transient_sources: secondary provider consultation results
    - query: the current user message
    - output: structured output instructions

    If provider_sources is supplied (from evaluate_providers()), those
    are included as sources with kind="provider".  This is the HME path:
    secondary provider responses become evidence for the mastermind.
    """
    if strip_xhtml_fn is None:
        strip_xhtml_fn = strip_xhtml
    if get_context_messages_fn is None:
        get_context_messages_fn = get_context_messages
    if get_src_entries_fn is None:
        get_src_entries_fn = get_src_entries
    if resolve_src_content_fn is None:
        resolve_src_content_fn = resolve_src_content

    bundle = ProviderBundle()

    # 1) System context (with mandatory XHTML output instruction)
    XHTML_INSTRUCTION = "Return strictly valid XHTML: no Markdown, close all tags, escape entities, one root element."
    context_text = strip_xhtml_fn(state.get("context", ""))
    if context_text:
        bundle.system = f"{context_text}\n\n{XHTML_INSTRUCTION}"
    else:
        bundle.system = XHTML_INSTRUCTION

    # 2) Certainty-aware source retrieval (RAG)
    if query_config.get("tools", {}).get("rag", True):
        trust_entries = state.get("truth", {}).get("trust", [])
        retrieval_prefs = query_config.get("retrieval", {})

        # Compute derived certainty from implication chains
        derived = compute_derived_truth(trust_entries)
        for entry in trust_entries:
            eid = entry.get("id", "")
            if eid in derived:
                entry["_derived_certainty"] = derived[eid]

        # Ranked normal entries (excluding providers and srcs)
        ranked = rank_retrieval_entries(
            trust_entries, retrieval_prefs,
            exclude_providers=True, exclude_srcs=True,
        )
        for entry in ranked:
            certainty = entry.get("_derived_certainty", entry.get("certainty", 0))
            bundle.sources.append(Source(
                source_id=entry.get("id", ""),
                title=entry.get("title", "untitled"),
                certainty=certainty,
                content=strip_xhtml_fn(entry.get("content", "")),
                kind="fact",
                time=entry.get("time", ""),
            ))

        # Resolve <src> file entries
        src_entries = get_src_entries_fn(trust_entries)
        min_certainty = retrieval_prefs.get("min_certainty", 0.0)
        for entry, src_config in src_entries:
            if entry.get("certainty", 0) < min_certainty:
                continue
            try:
                content = resolve_src_content_fn(src_config)
                if content:
                    bundle.sources.append(Source(
                        source_id=entry.get("id", ""),
                        title=entry.get("title", src_config.get("name", "Source")),
                        certainty=entry.get("certainty", 0),
                        content=content[:4000],
                        kind="src",
                        time=entry.get("time", ""),
                    ))
            except Exception:
                pass

    # 2b) Resolve <authority> entries: fetch remote trust tables, scale certainty
    if query_config.get("tools", {}).get("rag", True):
        authority_entries = get_authority_entries(trust_entries)
        if authority_entries:
            resolved = resolve_authority_entries(authority_entries, timeout_s=30)
            for _auth_entry, remote_trusts in resolved:
                for rt in remote_trusts:
                    bundle.sources.append(Source(
                        source_id=rt.get("id", ""),
                        title=rt.get("title", "untitled"),
                        certainty=rt.get("certainty", 0),
                        content=strip_xhtml_fn(rt.get("content", "")),
                        kind="authority",
                        time=rt.get("time", ""),
                    ))

    # 2c) Provider HME sources (evaluated <provider> entries)
    if provider_sources:
        bundle.sources.extend(provider_sources)

    # 3) Transient sources (legacy path; HME replaces this)
    if transient_snippets:
        for s in transient_snippets:
            bundle.transient_sources.append(Source(
                source_id=s.get("source_id", ""),
                title=s.get("source", "unknown"),
                certainty=s.get("certainty", 0),
                content=s.get("content", "")[:4000],
                kind="transient",
                time=s.get("time", ""),
            ))

    # 4) Conversation history (windowed ancestor chain)
    conversations = state.get("conversations", [])
    if conversation_id:
        context_msgs = get_context_messages_fn(conversations, conversation_id)
    else:
        context_msgs = []

    window_size = query_config.get("message_window", 40)
    recent = context_msgs[-window_size:]
    for msg in recent:
        role = msg.get("role", "user")
        content = strip_xhtml_fn(msg.get("content", ""))
        bundle.history.append({"role": role, "content": content})

    # 5) User query
    bundle.query = user_message

    # 6) Structured output instructions (always in state after ensure_minimal_state)
    bundle.output = state.get("output", "")

    return bundle


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------
def _format_sources(sources: List[Source]) -> str:
    """Format sources into a human-readable block for injection into messages."""
    if not sources:
        return ""
    lines = []
    for s in sources:
        # Skip title when it's redundant (content starts with or equals the title)
        title = s.title.strip()
        content = s.content.strip()
        if title and content.lower().startswith(title.lower()):
            lines.append(
                f"- (id: {s.source_id}, certainty: {s.certainty:.2f}): "
                f"{content}"
            )
        else:
            lines.append(
                f"- [{title}] (id: {s.source_id}, certainty: {s.certainty:.2f}): "
                f"{content}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------
def to_openai_messages(bundle: ProviderBundle) -> List[Dict[str, str]]:
    """Convert a ProviderBundle to OpenAI chat/completions messages array.

    - System context goes in a proper 'system' message (not fake user/assistant turns).
    - History as normal turns.
    - Sources + transient sources as structured content in the final user message.
    - Query as the user's actual question.
    - Output format instruction appended.
    """
    messages: List[Dict[str, str]] = []

    # System message: context + output format
    system_parts = []
    if bundle.system:
        system_parts.append(bundle.system)
    if bundle.output:
        system_parts.append(f"\n{bundle.output}")
    if system_parts:
        messages.append({"role": "system", "content": "\n".join(system_parts)})

    # History
    for msg in bundle.history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Final user message: sources + transient + query
    user_parts = []

    source_text = _format_sources(bundle.sources)
    if source_text:
        user_parts.append(f"[Reference Documents]\n{source_text}")

    transient_text = _format_sources(bundle.transient_sources)
    if transient_text:
        user_parts.append(f"[Provider Consultations]\n{transient_text}")

    user_parts.append(bundle.query)

    messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    return messages


def to_anthropic_payload(
    bundle: ProviderBundle,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    """Convert a ProviderBundle to an Anthropic /v1/messages payload.

    - System context goes in the top-level 'system' field.
    - History as alternating user/assistant messages.
    - Sources + query in final user message.
    - Handles Anthropic's strict user/assistant alternation requirement.
    """
    # System field
    system_parts = []
    if bundle.system:
        system_parts.append(bundle.system)
    if bundle.output:
        system_parts.append(f"\n{bundle.output}")
    system_text = "\n".join(system_parts) if system_parts else ""

    # Build messages: history + final user message
    raw_messages: List[Dict[str, str]] = []

    for msg in bundle.history:
        raw_messages.append({"role": msg["role"], "content": msg["content"]})

    # Final user message: sources + transient + query
    user_parts = []
    source_text = _format_sources(bundle.sources)
    if source_text:
        user_parts.append(f"[Reference Documents]\n{source_text}")

    transient_text = _format_sources(bundle.transient_sources)
    if transient_text:
        user_parts.append(f"[Provider Consultations]\n{transient_text}")

    user_parts.append(bundle.query)

    raw_messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    # Anthropic requires strict user/assistant alternation.
    # Merge consecutive same-role messages.
    cleaned: List[Dict[str, str]] = []
    last_role = None
    for msg in raw_messages:
        if msg["role"] == last_role:
            cleaned[-1]["content"] += "\n" + msg["content"]
        else:
            cleaned.append(dict(msg))
            last_role = msg["role"]

    # Anthropic requires first message to be 'user'
    if cleaned and cleaned[0]["role"] != "user":
        cleaned.insert(0, {"role": "user", "content": "(continuing conversation)"})

    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": cleaned,
    }
    if system_text:
        payload["system"] = system_text
    if temperature > 0:
        payload["temperature"] = temperature

    return payload


def to_nanochat_messages(bundle: ProviderBundle) -> List[Dict[str, str]]:
    """Convert a ProviderBundle to NanoChat-compatible messages.

    NanoChat uses OpenAI-compatible format but doesn't support system messages.
    Context goes as a user message prefix instead.
    """
    messages: List[Dict[str, str]] = []

    # NanoChat: context as first user message (it doesn't support system role)
    preamble_parts = []
    if bundle.system:
        preamble_parts.append(f"[Context] {bundle.system}")
    if bundle.output:
        preamble_parts.append(bundle.output)

    source_text = _format_sources(bundle.sources)
    if source_text:
        preamble_parts.append(f"[Reference Documents]\n{source_text}")

    transient_text = _format_sources(bundle.transient_sources)
    if transient_text:
        preamble_parts.append(f"[Provider Consultations]\n{transient_text}")

    if preamble_parts:
        messages.append({"role": "user", "content": "\n\n".join(preamble_parts)})
        messages.append({"role": "assistant", "content": "Understood. I have the project context and reference documents."})

    # History
    for msg in bundle.history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Current query
    messages.append({"role": "user", "content": bundle.query})

    return messages


# ---------------------------------------------------------------------------
# In-memory state for stateless mode
# ---------------------------------------------------------------------------
_MEMORY_STATE = None  # persists across requests in stateless mode


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
# Bundle building convenience wrappers
# ---------------------------------------------------------------------------
def _build_bundle(
    state: Dict[str, Any],
    user_message: str,
    query_config: Dict[str, Any],
    conversation_id: str | None = None,
    transient_snippets: List[Dict] | None = None,
) -> ProviderBundle:
    """Build a ProviderBundle from state + user message (convenience wrapper)."""
    return build_prompt_bundle(
        state, user_message, prefs,
        conversation_id=conversation_id,
        transient_snippets=transient_snippets,
    )


def _bundle_to_messages(bundle: ProviderBundle, provider: str) -> List[Dict[str, str]]:
    """Convert a ProviderBundle to provider-appropriate messages list."""
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


# ---------------------------------------------------------------------------
# Provider call functions
# ---------------------------------------------------------------------------
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


def _call_anthropic(bundle: ProviderBundle | None, temperature: float, provider_cfg: Dict,
                     messages: List[Dict] | None = None) -> str:
    """Call Anthropic API. Prefers bundle-based payload; falls back to legacy messages."""
    url = provider_cfg.get("url", "https://api.anthropic.com/v1/messages")

    if bundle is not None:
        payload = to_anthropic_payload(
            bundle,
            model=provider_cfg.get("default_model", "claude-sonnet-4-6"),
            max_tokens=2048,
            temperature=temperature,
        )
    else:
        payload = _build_anthropic_payload_from_messages(
            messages or [],
            model=provider_cfg.get("default_model", "claude-sonnet-4-6"),
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


def _call_provider(cfg: Config, bundle: ProviderBundle | None, temperature: float,
                    provider: str, client_api_key: str = "",
                    client_model: str = "",
                    messages: List[Dict] | None = None) -> str:
    """Call a provider using a ProviderBundle (preferred) or legacy messages."""
    import config as config_mod

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
    if config_mod.STATELESS_MODE:
        if client_api_key:
            effective_cfg["api_key"] = client_api_key
        # Fall through to server key if client didn't provide one
    else:
        if not effective_cfg.get("api_key") and client_api_key:
            effective_cfg["api_key"] = client_api_key
    if not effective_cfg.get("api_key"):
        if not config_mod.STATELESS_MODE:
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
    """Resolve a dynamic provider's API key with fallback to PROVIDERS/env vars."""
    import config as config_mod

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
    if matched_provider_key and not config_mod.STATELESS_MODE:
        fresh = _load_config_yaml()
        fresh_key = (fresh.get("providers", {}).get(matched_provider_key) or {}).get("api_key", "")
        if fresh_key:
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
        model=model or "claude-sonnet-4-6",
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
    query_config: Dict[str, Any],
    conversation_id: str | None = None,
    temperature: float = 0.7,
) -> tuple:
    """HME fan-out: evaluate secondary providers, feed results to primary."""
    trust_entries = state.get("truth", {}).get("trust", [])
    provider_entries = get_provider_entries(trust_entries)

    if not provider_entries:
        raise ValueError("No provider trust entries found")

    primary_entry, primary_config = provider_entries[0]
    secondaries = provider_entries[1:]

    base_bundle = _build_bundle(state, user_message, query_config, conversation_id)

    provider_sources: List[Source] = []
    if secondaries:
        def _call_for_eval(pconfig, messages):
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

    final_bundle = build_prompt_bundle(
        state, user_message, query_config,
        conversation_id=conversation_id,
        provider_sources=provider_sources,
    )

    api_url = primary_config.get("api_url", "")
    if "anthropic.com" in api_url:
        model = primary_config.get("model", "claude-sonnet-4-6")
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
        final_messages = to_nanochat_messages(final_bundle)
        response_text = _call_dynamic_provider(primary_config, final_messages, temperature, cfg)

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
# Chat processing (extracted from chat route handler)
# ---------------------------------------------------------------------------
def process_chat(
    cfg: Config,
    state: Dict[str, Any],
    body: Dict[str, Any],
    runtime_cfg: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    """Process a chat turn: derive truth, call providers, update conversations.

    Returns (response_text, updated_state).
    """
    import config as config_mod

    user_msg = (body.get("message") or "").strip()
    query_config = body.get("config", {}) if isinstance(body.get("config"), dict) else {}

    yaml_chat = runtime_cfg.get("chat", {})
    provider = query_config.get("provider", "wikioracle")
    client_model = (query_config.get("model") or "").strip()
    print(f"[WikiOracle] Chat request: provider='{provider}' (from client config)")

    temperature = max(0.0, min(2.0, float(
        query_config.get("temp", yaml_chat.get("temperature", 0.7))
    )))
    if "tools" not in query_config:
        query_config["tools"] = {}
    query_config["tools"].setdefault("rag", yaml_chat.get("rag", True))
    query_config["tools"].setdefault("url_fetch", yaml_chat.get("url_fetch", False))
    query_config.setdefault("message_window", yaml_chat.get("message_window", 40))
    query_config.setdefault("retrieval", yaml_chat.get("retrieval", {}))

    conversation_id = body.get("conversation_id")
    branch_from = body.get("branch_from")
    context_conv_id = conversation_id or branch_from

    user_timestamp = utc_now_iso()

    trust = state.get("truth", {}).get("trust", [])
    derived = compute_derived_truth(trust)
    for entry in trust:
        eid = entry.get("id", "")
        if eid in derived and abs(derived[eid] - entry.get("certainty", 0.0)) > 1e-9:
            entry["_derived_certainty"] = derived[eid]

    dyn_providers = get_provider_entries(trust)

    if dyn_providers:
        primary_entry, primary_config = dyn_providers[0]
        print(f"[WikiOracle] Chat: using DYNAMIC provider '{primary_config.get('name')}' "
              f"(from trust entry), secondaries={len(dyn_providers)-1}")
        response_text, _transient = _fan_out_and_aggregate(
            cfg, state, user_msg, query_config, context_conv_id,
            temperature=temperature,
        )
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
        bundle = _build_bundle(state, user_msg, query_config, context_conv_id)
        if config_mod.DEBUG_MODE:
            print(f"[DEBUG] ProviderBundle: system={len(bundle.system)} chars, "
                  f"history={len(bundle.history)} msgs, "
                  f"sources={len(bundle.sources)}, query={len(bundle.query)} chars")
            msgs = _bundle_to_messages(bundle, provider)
            print(f"[DEBUG] Upstream messages ({len(msgs)} total):")
            for i, m in enumerate(msgs):
                role = m.get("role", "?")
                content = m.get("content", "")
                print(f"  [{i}] {role}: {content[:200]}{'...' if len(content) > 200 else ''}")
        client_api_key = ""
        if config_mod.STATELESS_MODE:
            rc_providers = runtime_cfg.get("providers", {})
            rc_pcfg = rc_providers.get(provider, {})
            client_api_key = rc_pcfg.get("api_key", "")
        response_text = _call_provider(cfg, bundle, temperature, provider, client_api_key, client_model)
        if config_mod.DEBUG_MODE:
            print(f"[DEBUG] ← Response ({len(response_text)} chars): {response_text[:120]}...")
        llm_provider_name = PROVIDERS.get(provider, {}).get("name", provider)
        llm_model = query_config.get("model", PROVIDERS.get(provider, {}).get("default_model", provider))

    user_content = ensure_xhtml(user_msg)
    assistant_content = ensure_xhtml(response_text)
    assistant_timestamp = utc_now_iso()
    user_display = runtime_cfg.get("user", {}).get("name", "User")
    llm_display = llm_provider_name

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
    client_owns_query = config_mod.STATELESS_MODE

    if conversation_id:
        if not client_owns_query:
            add_message_to_conversation(conversations, conversation_id, query_entry)
        add_message_to_conversation(conversations, conversation_id, response_entry)
        state["selected_conversation"] = conversation_id
    elif branch_from:
        if client_owns_query:
            parent = find_conversation(conversations, branch_from)
            opt = parent["children"][-1] if parent and parent.get("children") else None
            if opt:
                opt["messages"].append(response_entry)
                state["selected_conversation"] = opt["id"]
            else:
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
            opt = conversations[-1] if conversations else None
            if opt and len(opt.get("messages", [])) == 1 and opt["messages"][0].get("_pending"):
                opt["messages"][0].pop("_pending", None)
                opt["messages"].append(response_entry)
                state["selected_conversation"] = opt["id"]
            else:
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
    return response_text, state
