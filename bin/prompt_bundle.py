#!/usr/bin/env python3
"""PromptBundle: provider-agnostic request object and provider adapters.

Decouples retrieval/prompting from provider-specific payload formats.
Each request is built once as a PromptBundle, then adapted for the target provider.

HME (Hierarchical Model Ensemble):
  <provider> trust entries are evaluated by sending each a RAG-free bundle.
  Their responses replace the <provider> XML with a <div> containing
  the provider's output.  The enriched entries become normal sources
  in the bundle that the primary (mastermind) LLM sees.
"""

from __future__ import annotations

import concurrent.futures
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# Re-export for backward compat (canonical definition is in wikioracle_state)
from wikioracle_state import DEFAULT_OUTPUT  # noqa: F401


# ---------------------------------------------------------------------------
# Data model
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
class PromptBundle:
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
        certainty = entry.get("certainty", 0)
        if abs(certainty) < min_certainty:
            continue
        content = entry.get("content", "")
        if exclude_providers and "<provider" in content:
            continue
        if exclude_srcs and "<src" in content:
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
) -> PromptBundle:
    """Build a RAG-free bundle for a secondary provider consultation.

    The provider sees system context, history, the query, and the output
    instructions — but NO sources (no RAG).  This keeps the secondary
    providers independent so the mastermind can weigh their opinions.
    """
    return PromptBundle(
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
    prefs: Dict[str, Any],
    conversation_id: Optional[str] = None,
    transient_snippets: Optional[List[Dict]] = None,
    *,
    strip_xhtml_fn=None,
    get_context_messages_fn=None,
    get_src_entries_fn=None,
    resolve_src_content_fn=None,
    provider_sources: Optional[List[Source]] = None,
) -> PromptBundle:
    """Build a canonical PromptBundle from state + user message.

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
    # Lazy imports to avoid circular deps when used from WikiOracle.py
    if strip_xhtml_fn is None:
        from wikioracle_state import strip_xhtml
        strip_xhtml_fn = strip_xhtml
    if get_context_messages_fn is None:
        from wikioracle_state import get_context_messages
        get_context_messages_fn = get_context_messages
    if get_src_entries_fn is None:
        from wikioracle_state import get_src_entries
        get_src_entries_fn = get_src_entries
    if resolve_src_content_fn is None:
        from wikioracle_state import resolve_src_content
        resolve_src_content_fn = resolve_src_content

    bundle = PromptBundle()

    # 1) System context (with mandatory XHTML output instruction)
    XHTML_INSTRUCTION = "Return strictly valid XHTML: no Markdown, close all tags, escape entities, one root element."
    context_text = strip_xhtml_fn(state.get("context", ""))
    if context_text:
        bundle.system = f"{context_text}\n\n{XHTML_INSTRUCTION}"
    else:
        bundle.system = XHTML_INSTRUCTION

    # 2) Certainty-aware source retrieval (RAG)
    if prefs.get("tools", {}).get("rag", True):
        trust_entries = state.get("truth", {}).get("trust", [])
        retrieval_prefs = prefs.get("retrieval", {})

        # Ranked normal entries (excluding providers and srcs)
        ranked = rank_retrieval_entries(
            trust_entries, retrieval_prefs,
            exclude_providers=True, exclude_srcs=True,
        )
        for entry in ranked:
            bundle.sources.append(Source(
                source_id=entry.get("id", ""),
                title=entry.get("title", "untitled"),
                certainty=entry.get("certainty", 0),
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

    # 2b) Provider HME sources (evaluated <provider> entries)
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

    window_size = prefs.get("message_window", 40)
    recent = context_msgs[-window_size:]
    for msg in recent:
        role = msg.get("role", "user")
        content = strip_xhtml_fn(msg.get("content", ""))
        bundle.history.append({"role": role, "content": content})

    # 5) User query
    bundle.query = user_message

    # 6) Structured output instructions (always in state after ensure_minimal_state)
    #    XHTML format is now enforced via system context; output_format removed from config.
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
def to_openai_messages(bundle: PromptBundle) -> List[Dict[str, str]]:
    """Convert a PromptBundle to OpenAI chat/completions messages array.

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
    bundle: PromptBundle,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    """Convert a PromptBundle to an Anthropic /v1/messages payload.

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


def to_nanochat_messages(bundle: PromptBundle) -> List[Dict[str, str]]:
    """Convert a PromptBundle to NanoChat-compatible messages.

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
