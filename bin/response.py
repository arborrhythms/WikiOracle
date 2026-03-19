"""WikiOracle response pipeline: ProviderBundle, provider adapters, and chat processing.

Response generation and provider coordination:
  - ProviderBundle data model for managing multiple LLM providers
  - Provider adapter implementations for various API backends
  - Prompt assembly and context injection
  - process_chat orchestration for concurrent provider calls
  - Online training pipeline (Stages 2–4): DegreeOfTruth, truth merge,
    Sensation preprocessing, and /train POST to NanoChat (see doc/Training.md)
"""

from __future__ import annotations

import concurrent.futures
import copy
import html as html_mod
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

from config import (
    Config, DEBUG_MODE, PROVIDERS, STATELESS_MODE, _load_config, _PROVIDER_MODELS,
    DEFAULT_TRUTH_CONTEXT, DEFAULT_CONVERSATION_CONTEXT, DEFAULT_OUTPUT,
)
from graph import apply_selection_flags
from sensation import preprocess_training_example
from truth import (
    _fetch_authority,
    _has_operator_tag,
    compute_degree_of_truth,
    compute_derived_truth,
    detect_asymmetric_claim,
    detect_identifiability,
    ensure_xhtml,
    filter_knowledge_only,
    get_authority_entries,
    get_provider_entries,
    load_server_truth,
    merge_client_truth,
    resolve_api_key,
    resolve_authority_entries,
    resolve_entries,
    save_server_truth,
    strip_xhtml,
    user_guid,
    utc_now_iso,
    validate_operator_operands,
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
    atomic_write_xml,
    state_to_xml,
)


# ---------------------------------------------------------------------------
# ProviderBundle data model
# ---------------------------------------------------------------------------
@dataclass
class Source:
    """A single retrieved trust entry with trust score."""
    source_id: str  # Stable entry identifier used for traceability.
    title: str  # Human-readable source label shown to the model/user.
    trust: float  # Confidence score used in ranking/display.
    content: str  # Plaintext/XHTML snippet injected into prompts.
    kind: str = "fact"          # "fact" | "feeling" | "reference" | "provider" | "logic" | "authority" | "transient"
    time: str = ""


@dataclass
class ProviderBundle:
    """Provider-agnostic request object built once per chat request.

    Fields:
        system:   global instructions / context (goes in system message)
        history:  conversation messages from ancestor chain
        sources:  all state.truth entries + dynamic results (when rag=True)
        query:    current user message
        output:   short instruction describing the output format
    """
    system: str = ""  # Global instructions/context.
    history: List[Dict[str, str]] = field(default_factory=list)  # Prior turns on active path.
    sources: List[Source] = field(default_factory=list)  # Truth table evidence.
    transient_sources: List[Source] = field(default_factory=list)  # Legacy ad hoc provider snippets.
    query: str = ""  # Current user message.
    output: str = ""  # Output-format guidance appended to prompts.


# ---------------------------------------------------------------------------
# Trust-aware retrieval ranking
# ---------------------------------------------------------------------------
def static_truth(
    trust_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract the evaluable (static) subset of the truth table.

    Returns every entry whose content is a fact, feeling, or reference —
    i.e. the entries that carry propositional content rather than structural
    wiring.  These are the entries that ``dynamic_truth`` evaluates against.

    Structural entries are excluded from this subset:
      - ``<provider>``  — evaluated separately as dynamic expert consultations
      - ``<logic>``     — evaluated by ``compute_derived_truth`` (Strong Kleene)
      - ``<authority>``  — resolved separately via ``resolve_authority_entries``

    Note: ``static_truth`` controls what the dynamic evaluation steps see
    as input.  All ``state.truth`` entries (including structural ones) are
    still sent to the final provider when ``rag`` is true.
    """
    result = []
    for entry in trust_entries:
        content = entry.get("content", "")
        if "<provider" in content:
            continue
        if _has_operator_tag(content):
            continue
        if "<authority" in content:
            continue
        result.append(entry)
    return result


def direct_truth_sources(
    trust_entries: List[Dict[str, Any]],
    strip_fn: Callable = strip_xhtml,
) -> List[Source]:
    """Build Source list of direct truths only (facts + feelings).

    Unlike ``static_truth()`` which also includes references, this filters
    to only ``<fact>`` and ``<feeling>`` entries — the direct propositional
    content that truth providers receive as context.
    """
    sources: List[Source] = []
    for entry in trust_entries:
        content = entry.get("content", "")
        if "<fact" in content:
            kind = "fact"
        elif "<feeling" in content:
            kind = "feeling"
        else:
            continue
        sources.append(Source(
            source_id=entry.get("id", ""),
            title=entry.get("title", ""),
            trust=entry.get("trust", 0),
            content=strip_fn(content),
            kind=kind,
            time=entry.get("time", ""),
        ))
    return sources


def _extract_direct_truths(
    response_text: str,
    provider_id: str,
    provider_trust: float,
) -> tuple:
    """Parse ``<fact>``, ``<feeling>``, ``<conversation>`` from a truth provider response.

    Returns ``(conversation_text, truth_sources)`` where:
      - *conversation_text* is the text inside ``<conversation>`` tags (or None)
      - *truth_sources* is a list of Source objects for extracted facts/feelings
    """
    conversation_text = None
    truth_sources: List[Source] = []

    # Extract <conversation> content
    conv_match = re.search(r"<conversation[^>]*>(.*?)</conversation>", response_text, re.DOTALL)
    if conv_match:
        conversation_text = conv_match.group(1).strip()

    # Extract <fact> entries — honour trust="..." attribute when present
    for i, m in enumerate(re.finditer(r"<fact([^>]*)>(.*?)</fact>", response_text, re.DOTALL)):
        attrs, body = m.group(1), m.group(2).strip()
        fact_trust = provider_trust
        trust_attr = re.search(r'trust\s*=\s*["\']([^"\']+)["\']', attrs)
        if trust_attr:
            try:
                fact_trust = max(-1.0, min(1.0, float(trust_attr.group(1))))
            except (ValueError, TypeError):
                pass
        truth_sources.append(Source(
            source_id=f"{provider_id}_fact_{i}",
            title=f"{provider_id} fact",
            trust=fact_trust,
            content=body,
            kind="fact",
        ))

    # Extract <feeling> entries
    for i, m in enumerate(re.finditer(r"<feeling[^>]*>(.*?)</feeling>", response_text, re.DOTALL)):
        truth_sources.append(Source(
            source_id=f"{provider_id}_feeling_{i}",
            title=f"{provider_id} feeling",
            trust=provider_trust,
            content=m.group(1).strip(),
            kind="feeling",
        ))

    return conversation_text, truth_sources


# ---------------------------------------------------------------------------
# HME: evaluate <provider> entries
# ---------------------------------------------------------------------------
def _build_provider_query_bundle(
    system: str,
    history: List[Dict[str, str]],
    query: str,
    output: str,
    prelim_response: Optional[str] = None,
) -> ProviderBundle:
    """Build a RAG-free bundle for a truth provider consultation.

    .. deprecated::
        Legacy interface kept for backward compatibility.
        Use :func:`_build_truth_provider_bundle` or
        :func:`_build_conversation_provider_bundle` instead.
    """
    hist = list(history)
    if prelim_response:
        hist.append({"role": "user", "content": query})
        hist.append({"role": "assistant", "content": prelim_response})
    return ProviderBundle(
        system=system,
        history=hist,
        sources=[],
        transient_sources=[],
        query=query,
        output=output,
    )


def _build_truth_provider_bundle(
    system_context: str,
    direct_sources: List[Source],
    query: str,
    output: str,
) -> ProviderBundle:
    """Build a bundle for a truth-only truth provider (conversation=false).

    The truth provider sees the system context with direct truths
    (facts/feelings) but no conversation history.  It is expected to
    return only ``<fact>`` and ``<feeling>`` elements.
    """
    return ProviderBundle(
        system=system_context,
        history=[],
        sources=direct_sources,
        transient_sources=[],
        query=query,
        output=output,
    )


def _build_conversation_provider_bundle(
    system_context: str,
    history: List[Dict[str, str]],
    direct_sources: List[Source],
    query: str,
    output: str,
) -> ProviderBundle:
    """Build a bundle for a conversational truth provider (conversation=true).

    The truth provider sees conversation history, direct truths, and
    the query.  It is expected to return a ``<conversation>`` answer
    plus optional ``<fact>`` and ``<feeling>`` elements.
    """
    return ProviderBundle(
        system=system_context,
        history=list(history),
        sources=direct_sources,
        transient_sources=[],
        query=query,
        output=output,
    )


def resolve_provider_truth(
    provider_config: dict,
    provider_entry: dict,
    *,
    allowed_data_dir: str | None = None,
) -> List[Source]:
    """Resolve a provider's private truth table from its authority_url.

    Uses the same fetch logic as authority resolution.
    Trust is scaled by the provider entry's trust.
    Returns Source objects ready for injection into the provider's bundle.
    """
    authority_url = provider_config.get("authority_url", "")
    if not authority_url:
        return []

    raw_entries = _fetch_authority(
        authority_url, timeout_s=30,
        allowed_data_dir=allowed_data_dir,
    )

    provider_id = provider_entry.get("id", "unknown")
    provider_trust = provider_entry.get("trust", 0.0)
    sources = []
    for entry in raw_entries:
        # Legacy files may use "trust" or "certainty" as the key
        remote_trust = entry.get("trust", entry.get("certainty", 0.0))
        try:
            remote_trust = float(remote_trust)
        except (TypeError, ValueError):
            remote_trust = 0.0
        scaled = min(1.0, max(-1.0, provider_trust * remote_trust))
        remote_id = entry.get("id", "")
        sources.append(Source(
            source_id=f"{provider_id}:{remote_id}" if remote_id else provider_id,
            title=entry.get("title", "untitled"),
            trust=scaled,
            content=entry.get("content", ""),
            kind="fact",
            time=entry.get("time", ""),
        ))
    return sources


def evaluate_providers(
    provider_entries: List[tuple],
    system: str,
    history: List[Dict[str, str]],
    query: str,
    output: str,
    call_fn: Callable[[dict, List[Dict[str, str]]], str],
    *,
    timeout_s: int = 60,
    call_chain: Optional[List[str]] = None,
    direct_sources: Optional[List[Source]] = None,
    truth_context: Optional[str] = None,
    conversation_context: Optional[str] = None,
) -> tuple:
    """Evaluate <provider> trust entries as truth provider consultations.

    Each provider's ``conversation`` flag determines its role:
      - **conversation=false** (default): truth provider contributes only
        direct truths (``<fact>`` and ``<feeling>``).  Invisible to
        conversation tree.
      - **conversation=true**: truth provider participates in the
        conversation and may return a ``<conversation>`` answer plus truths.

    Args:
        provider_entries: list of (trust_entry, provider_config) pairs.
        system:   system context string (from config.providers.context).
        history:  conversation history (ancestor chain).
        query:    the current user message.
        output:   structured output instructions.
        call_fn:  callable(provider_config, messages) -> str.
        timeout_s:  per-provider wall-clock timeout.
        call_chain: provider IDs in the call ancestry (cycle prevention).
        direct_sources: pre-computed direct truth Sources (facts/feelings)
                    to include in provider bundles.

    Returns:
        ``(conversation_sources, truth_contributions)`` tuple:
          - *conversation_sources*: list of Source objects (kind="provider")
            from conversation=true truth providers — visible in the
            conversation tree.
          - *truth_contributions*: list of Source objects (kind="fact"/"feeling")
            extracted from all truth provider responses.
    """
    if not provider_entries:
        return [], []

    chain = set(call_chain) if call_chain else set()
    dsources = direct_sources or []

    conversation_sources: List[Source] = []
    truth_contributions: List[Source] = []

    def _evaluate_one(pair):
        """Evaluate one provider entry.

        Returns (conv_source_or_None, [truth_sources]).
        """
        entry, pconfig = pair

        # Cycle prevention: if this provider is in the call chain, stay silent
        if entry.get("id", "") in chain:
            return None, []

        wants_conversation = pconfig.get("conversation", False)

        # Resolve context from section-level defaults (config.providers)
        if wants_conversation:
            ctx = conversation_context or DEFAULT_CONVERSATION_CONTEXT
        else:
            ctx = truth_context or DEFAULT_TRUTH_CONTEXT

        # Per-provider truth: authority_url provides private facts
        prov_truth = resolve_provider_truth(pconfig, entry)
        all_sources = list(dsources) + prov_truth

        if wants_conversation:
            bundle = _build_conversation_provider_bundle(
                ctx, history, all_sources, query, output,
            )
        else:
            bundle = _build_truth_provider_bundle(
                ctx, all_sources, query, output,
            )

        messages = to_nanochat_messages(bundle)

        try:
            response = call_fn(pconfig, messages)
            if not response or response.startswith("[Error"):
                return None, []

            # Extract structured truths from the truth provider's response
            conv_text, extracted_truths = _extract_direct_truths(
                response,
                entry.get("id", ""),
                entry.get("trust", 0),
            )

            conv_source = None
            if wants_conversation:
                # Build a conversation source for the tree
                pname = html_mod.escape(entry.get("id", ""), quote=True)
                # Use conversation text if extracted, otherwise the full response
                display_text = conv_text if conv_text else response
                safe_response = html_mod.escape(display_text[:4000])
                conv_source = Source(
                    source_id=entry.get("id", ""),
                    title=entry.get("title", ""),
                    trust=entry.get("trust", 0),
                    content=(
                        f'<div class="provider-response" '
                        f'data-provider="{pname}">'
                        f'{safe_response}</div>'
                    ),
                    kind="provider",
                    time=entry.get("time", ""),
                )

            return conv_source, extracted_truths
        except Exception:
            return None, []

    if len(provider_entries) == 1:
        conv_src, truths = _evaluate_one(provider_entries[0])
        if conv_src:
            conversation_sources.append(conv_src)
        truth_contributions.extend(truths)
    else:
        max_workers = min(len(provider_entries), 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_evaluate_one, p): p for p in provider_entries}
            done, _ = concurrent.futures.wait(futures, timeout=timeout_s)
            for fut in done:
                try:
                    conv_src, truths = fut.result(timeout=0)
                    if conv_src:
                        conversation_sources.append(conv_src)
                    truth_contributions.extend(truths)
                except Exception:
                    pass

    return conversation_sources, truth_contributions


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------
def build_query(
    state: Dict[str, Any],
    user_message: str,
    query_config: Dict[str, Any],
    conversation_id: Optional[str] = None,
    transient_snippets: Optional[List[Dict]] = None,
    *,
    strip_xhtml_fn=None,
    get_context_messages_fn=None,
    provider_sources: Optional[List[Source]] = None,
) -> ProviderBundle:
    """Build a canonical ProviderBundle from state + user message.

    This is the single entry point for all providers. The bundle captures:
    - system: cleaned context text (project constraints, formatting rules)
    - history: conversation messages from ancestor chain
    - sources: all state.truth entries plus dynamic results (when rag=True)
    - query: the current user message
    - output: structured output instructions

    When ``rag`` is true, **all** ``state.truth`` entries are sent to the
    provider (facts, references, operators, authorities, providers), plus
    dynamic results (resolved authorities, evaluated provider responses).
    When ``rag`` is false, **no** truth of any kind is sent.

    The pipeline is:

        st = static_truth(state.truth)   — facts & references (evaluable)
        t  = st + dynamic_truth(st)      — operators propagate trust,
                                           authorities resolved, providers
                                           evaluated
        bundle.sources = state.truth (with derived trust)
                       + authority remote entries
                       + provider_sources (HME expert responses)
    """
    if strip_xhtml_fn is None:
        strip_xhtml_fn = strip_xhtml
    if get_context_messages_fn is None:
        get_context_messages_fn = get_context_messages

    bundle = ProviderBundle()

    # 1) System context (with mandatory XHTML output instruction)
    XHTML_INSTRUCTION = "Return strictly valid XHTML: no Markdown, close all tags, escape entities, one root element."
    context_text = strip_xhtml_fn(query_config.get("context", ""))
    if context_text:
        bundle.system = f"{context_text}\n\n{XHTML_INSTRUCTION}"
    else:
        bundle.system = XHTML_INSTRUCTION

    # 2) Truth table → sources  (the HME pipeline)
    #
    #    st = static_truth(state.truth)     — facts & references
    #    t  = st + dynamic_truth(st)        — augmented with operators,
    #                                         authorities, and providers
    #
    # When truth_weight > 0, ALL state.truth is sent.
    # When truth_weight == 0, NO truth of any kind is sent.
    #
    ts_cfg = query_config.get("truthset", {})
    _rag_on = ts_cfg.get("truth_weight", 0.7)
    if (isinstance(_rag_on, bool) and _rag_on) or (isinstance(_rag_on, (int, float)) and _rag_on > 0):
        trust_entries = state.get("truth") or []

        # Resolve references→facts, authorities→facts, providers→feelings
        # before any evaluation step sees the entries.
        trust_entries = resolve_entries(trust_entries)

        # st: the evaluable subset (facts + feelings) — used as input
        # to dynamic evaluation steps
        st = static_truth(trust_entries)

        # dynamic_truth(st): operators (Strong Kleene trust propagation)
        derived = compute_derived_truth(trust_entries)
        for entry in trust_entries:
            eid = entry.get("id", "")
            if eid in derived:
                entry["_derived_trust"] = derived[eid]

        # dynamic_truth(st): authority resolution (remote truth tables)
        authority_entries = get_authority_entries(trust_entries)
        authority_sources: List[Source] = []
        if authority_entries:
            resolved = resolve_authority_entries(authority_entries, timeout_s=30)
            for _auth_entry, remote_trusts in resolved:
                for rt in remote_trusts:
                    authority_sources.append(Source(
                        source_id=rt.get("id", ""),
                        title=rt.get("title", "untitled"),
                        trust=rt.get("trust", 0),
                        content=strip_xhtml_fn(rt.get("content", "")),
                        kind="authority",
                        time=rt.get("time", ""),
                    ))

        # dynamic_truth(st): evaluated <provider> entries (HME experts)
        # provider_sources are computed upstream by evaluate_providers()

        # t = st + dynamic_truth(st)
        # Send every state.truth entry to the provider, with derived
        # trust where operators have propagated it.
        for entry in trust_entries:
            trust_val = entry.get("_derived_trust", entry.get("trust", 0))
            content = entry.get("content", "")
            if "<provider" in content:
                kind = "provider"
            elif "<authority" in content:
                kind = "authority"
            elif "<reference" in content:
                kind = "reference"
            elif "<logic" in content or _has_operator_tag(content):
                kind = "logic"
            elif "<feeling" in content:
                kind = "feeling"
            else:
                kind = "fact"
            bundle.sources.append(Source(
                source_id=entry.get("id", ""),
                title=entry.get("title", "untitled"),
                trust=trust_val,
                content=strip_xhtml_fn(content),
                kind=kind,
                time=entry.get("time", ""),
            ))
        bundle.sources.extend(authority_sources)
        if provider_sources:
            bundle.sources.extend(provider_sources)

    # 3) Transient sources (legacy path; HME replaces this)
    if transient_snippets:
        for s in transient_snippets:
            bundle.transient_sources.append(Source(
                source_id=s.get("source_id", ""),
                title=s.get("source", "unknown"),
                trust=s.get("trust", 0),
                content=s.get("content", "")[:4000],
                kind="transient",
                time=s.get("time", ""),
            ))

    # 4) Conversation history (ancestor chain)
    conversations = state.get("conversations", [])
    if conversation_id:
        context_msgs = get_context_messages_fn(conversations, conversation_id)
    else:
        context_msgs = []

    recent = context_msgs
    for msg in recent:
        role = msg.get("role", "user")
        content = strip_xhtml_fn(msg.get("content", ""))
        bundle.history.append({"role": role, "content": content})

    # 5) User query (use "(continue)" for empty sends so providers
    #    always receive a non-empty user message)
    bundle.query = user_message or "(continue)"

    # 6) Structured output instructions (from config.providers.output)
    # Fall back to DEFAULT_OUTPUT so the main provider always knows to produce
    # structured <conversation>/<fact>/<feeling> output.
    bundle.output = query_config.get("output", "") or DEFAULT_OUTPUT

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
                f"- (id: {s.source_id}, trust: {s.trust:.2f}): "
                f"{content}"
            )
        else:
            trust_str = f"{s.trust:.2f}" if s.trust is not None else "n/a"
            lines.append(
                f"- [{title}] (id: {s.source_id}, trust: {trust_str}): "
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


def to_openrouter_messages(bundle: ProviderBundle) -> List[Dict[str, str]]:
    """Convert a ProviderBundle to OpenRouter chat/completions messages.

    OpenRouter is OpenAI-compatible at the transport layer, but some routed
    models reject ``system`` / developer-style instructions. Build the normal
    OpenAI messages first, then fold the system content into the first user
    turn so the request stays model-compatible without losing context.
    """
    messages = to_openai_messages(bundle)
    if not messages or messages[0]["role"] != "system":
        return messages

    system_content = messages[0]["content"]
    flattened = [dict(msg) for msg in messages[1:]]

    for msg in flattened:
        if msg["role"] == "user":
            msg["content"] = f"{system_content}\n\n{msg['content']}"
            return flattened

    flattened.insert(0, {"role": "user", "content": system_content})
    return flattened


def to_anthropic_payload(
    bundle: ProviderBundle,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    temperature: float = 0.7,
    web_search: bool = True,
) -> Dict[str, Any]:
    """Convert a ProviderBundle to an Anthropic /v1/messages payload.

    - System context goes in the top-level 'system' field.
    - History as alternating user/assistant messages.
    - Sources + query in final user message.
    - Handles Anthropic's strict user/assistant alternation requirement.
    - Includes web_search tool when enabled.
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
    if web_search:
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

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
    """Normalize, size-check, and atomically persist state to disk as XML."""
    normalized = ensure_minimal_state(state, strict=True)
    normalized["time"] = utc_now_iso()
    # Size check (use JSON for estimation — close enough for both formats)
    serialized = json.dumps(normalized, ensure_ascii=False)
    if len(serialized.encode("utf-8")) > cfg.max_state_bytes:
        raise StateValidationError("State exceeds MAX_STATE_BYTES")
    atomic_write_xml(cfg.state_file, normalized, reject_symlinks=cfg.reject_symlinks)


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
    return build_query(
        state, user_message, query_config,
        conversation_id=conversation_id,
        transient_snippets=transient_snippets,
    )


def _bundle_to_messages(bundle: ProviderBundle, provider: str) -> List[Dict[str, str]]:
    """Convert a ProviderBundle to provider-appropriate messages list."""
    prov_type = PROVIDERS.get(provider, {}).get("type", provider)
    if prov_type == "wikioracle":
        return to_nanochat_messages(bundle)
    elif prov_type == "openai":
        return to_openai_messages(bundle)
    elif prov_type == "openrouter":
        return to_openrouter_messages(bundle)
    elif prov_type == "anthropic":
        # For Anthropic we return OpenAI-format messages; the caller
        # uses to_anthropic_payload() directly for the full payload.
        return to_openai_messages(bundle)
    else:
        return to_openai_messages(bundle)


# ---------------------------------------------------------------------------
# Provider call functions
# ---------------------------------------------------------------------------
def _trim_nanochat_messages(
    messages: List[Dict],
    max_tokens: int,
    sequence_len: int = 2048,
    chars_per_token: int = 4,
) -> List[Dict]:
    """Trim conversation history so the prompt fits within *sequence_len* tokens.

    Uses a conservative character-based estimate (server-side doesn't have the
    tokenizer).  Keeps the preamble (context + ack, first two messages) and the
    current query (last message), trimming the oldest history turns first.
    """
    token_budget = sequence_len - min(max_tokens, sequence_len // 2)
    char_budget = token_budget * chars_per_token

    total_chars = sum(len(m.get("content", "")) for m in messages)
    if total_chars <= char_budget:
        return messages

    # Preamble = context injection + ack (first 2 msgs when present)
    # Query   = current user message (last msg)
    if len(messages) <= 3:
        # Nothing useful to trim — preamble + query is all there is
        print(f"[WikiOracle] Warning: prompt ({total_chars} chars) exceeds budget "
              f"({char_budget} chars) but no history to trim")
        return messages

    preamble = messages[:2]
    query = messages[-1:]
    history = messages[2:-1]

    fixed_chars = sum(len(m.get("content", "")) for m in preamble + query)
    history_budget = char_budget - fixed_chars

    if history_budget <= 0:
        print(f"[WikiOracle] Warning: preamble+query alone ({fixed_chars} chars) "
              f"exceeds budget ({char_budget} chars); dropping all history")
        return preamble + query

    # Keep most-recent history turns that fit within budget
    kept: list[Dict] = []
    running = 0
    for msg in reversed(history):
        msg_chars = len(msg.get("content", ""))
        if running + msg_chars > history_budget:
            break
        kept.append(msg)
        running += msg_chars
    kept.reverse()

    dropped = len(history) - len(kept)
    print(f"[WikiOracle] Trimmed {dropped} history message(s) to fit context window "
          f"(sequence_len={sequence_len}, reserved {sequence_len - token_budget} tokens "
          f"for generation)")

    return preamble + kept + query


def _call_nanochat(cfg: Config, messages: List[Dict], temperature: float,
                   max_tokens: int = 128, timeout: int = 120) -> str:
    """Call NanoChat /chat/completions (SSE streaming, buffered)."""
    seq_len = PROVIDERS.get("WikiOracle", {}).get("sequence_len", 2048)
    messages = _trim_nanochat_messages(messages, max_tokens, seq_len)
    url = PROVIDERS.get("WikiOracle", {}).get("url") or (cfg.base_url + cfg.api_path)
    if DEBUG_MODE:
        print(f"[DEBUG] NanoChat → {url}")
        print(f"[DEBUG] NanoChat messages ({len(messages)}):")
        for i, m in enumerate(messages):
            print(f"  [{i}] {m['role']}: {m['content'][:200]}{'...' if len(m['content']) > 200 else ''}")
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    provider_timeout = max(PROVIDERS.get("WikiOracle", {}).get("timeout") or timeout, 15)
    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"},
                         timeout=provider_timeout, stream=True)
    if resp.status_code >= 400:
        return f"[Error from upstream: HTTP {resp.status_code}] {resp.text[:500]}"

    full_text = []
    done = False
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
                if data.get("error"):
                    return f"[Error from NanoChat: {data['error']}]"
                if data.get("done"):
                    done = True
                    break
                if "token" in data:
                    full_text.append(data["token"])
            except json.JSONDecodeError:
                continue
    except (requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout) as exc:
        return f"[Error: connection lost to NanoChat ({url}): {exc}]"
    if full_text:
        return "".join(full_text)
    if not done:
        return f"[Error: NanoChat stream ended abnormally ({url}). Check server logs.]"
    return f"[Error: no response from NanoChat ({url}). Check server logs.]"


def _call_basicmodel(cfg: Config, messages: List[Dict], temperature: float,
                     max_tokens: int = 128, timeout: int = 120) -> str:
    """Call BasicModel /chat/completions endpoint."""
    url = PROVIDERS.get("WikiOracle", {}).get("basicmodel_url", "http://127.0.0.1:8001/chat/completions")
    payload = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    provider_timeout = max(PROVIDERS.get("WikiOracle", {}).get("basicmodel_timeout") or timeout, 15)
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"},
                             timeout=provider_timeout)
        if resp.status_code >= 400:
            return f"[Error from BasicModel: HTTP {resp.status_code}] {resp.text[:500]}"
        return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "[No content]")
    except requests.exceptions.ConnectionError:
        return ("[BasicModel server is not running. "
                "Start it with: python basicmodel/bin/serve.py]")
    except Exception as exc:
        return f"[Error from BasicModel: {exc}]"


def _call_openai(messages: List[Dict], temperature: float, provider_cfg: Dict) -> str:
    """Call an OpenAI-compatible chat/completions endpoint and return text."""
    url = provider_cfg.get("url", "https://api.openai.com/v1/chat/completions")
    payload = {
        "model": provider_cfg.get("model", "gpt-4o"),
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
            model=provider_cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=2048,
            temperature=temperature,
        )
    else:
        payload = _build_anthropic_payload_from_messages(
            messages or [],
            model=provider_cfg.get("model", "claude-sonnet-4-6"),
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
    data = resp.json()
    blocks = data.get("content", [])
    # Extract text blocks; append citation URLs if web search was used
    text_parts = []
    citations = []
    for b in blocks:
        if b.get("type") == "text":
            text_parts.append(b.get("text", ""))
            for cite in b.get("citations", []):
                if cite.get("type") == "web_search_result_location":
                    url_val = cite.get("url", "")
                    title = cite.get("title", url_val)
                    if url_val and url_val not in [c[1] for c in citations]:
                        citations.append((title, url_val))
    result = "".join(text_parts) or "[No content]"
    # Wrap the main text in <conversation> and each citation as a <fact>
    # so the extraction pipeline can harvest them into the truth table.
    if citations:
        trust = provider_cfg.get("trust", 0.6)
        citation_facts = "\n".join(
            f'<fact trust="{trust}">{html_mod.escape(t)}: {html_mod.escape(u)}</fact>'
            for t, u in citations
        )
        result = f"<conversation>{result}</conversation>\n{citation_facts}"
    return result


# ---------------------------------------------------------------------------
# Gemini adapter (Google Generative Language API)
# ---------------------------------------------------------------------------
def to_gemini_payload(
    bundle: ProviderBundle,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    web_search: bool = True,
) -> Dict[str, Any]:
    """Convert a ProviderBundle to a Gemini generateContent payload.

    Gemini uses a different message format: contents → [parts → text].
    System instructions go in a separate 'system_instruction' field.
    Enables Google Search grounding when web_search is True.
    """
    system_parts = []
    if bundle.system:
        system_parts.append(bundle.system)
    if bundle.output:
        system_parts.append(bundle.output)

    contents = []
    for msg in bundle.history:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Final user message: sources + query
    user_parts_text = []
    source_text = _format_sources(bundle.sources)
    if source_text:
        user_parts_text.append(f"[Reference Documents]\n{source_text}")
    transient_text = _format_sources(bundle.transient_sources)
    if transient_text:
        user_parts_text.append(f"[Provider Consultations]\n{transient_text}")
    user_parts_text.append(bundle.query)
    contents.append({"role": "user", "parts": [{"text": "\n\n".join(user_parts_text)}]})

    payload: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048},
    }
    if system_parts:
        payload["system_instruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
    if web_search:
        payload["tools"] = [{"google_search": {}}]
    return payload


def _call_gemini(bundle: ProviderBundle | None, temperature: float,
                 provider_cfg: Dict, messages: List[Dict] | None = None) -> str:
    """Call Google Gemini API with optional Google Search grounding."""
    model = provider_cfg.get("model", "gemini-2.5-flash")
    base_url = provider_cfg.get("url", "https://generativelanguage.googleapis.com/v1beta/models")
    api_key = provider_cfg.get("api_key", "")
    url = f"{base_url}/{model}:generateContent"

    if bundle is not None:
        payload = to_gemini_payload(bundle, model=model, temperature=temperature)
    else:
        # Fallback: convert legacy messages to Gemini format
        contents = []
        for msg in (messages or []):
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 2048},
            "tools": [{"google_search": {}}],
        }

    if DEBUG_MODE:
        print(f"[DEBUG] Gemini → {base_url}/{model}:generateContent")
        contents = payload.get("contents", [])
        print(f"[DEBUG] Gemini contents ({len(contents)}):")
        for i, c in enumerate(contents):
            text = c.get("parts", [{}])[0].get("text", "")
            print(f"  [{i}] {c.get('role', '?')}: {text[:200]}{'...' if len(text) > 200 else ''}")

    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    if resp.status_code >= 400:
        return f"[Error from Gemini: HTTP {resp.status_code}] {resp.text[:500]}"

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return "[No response from Gemini]"

    # Extract text from candidate parts
    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [p.get("text", "") for p in parts if "text" in p]
    result = "".join(text_parts) or "[No content]"

    # Append grounding citations if present
    grounding = candidates[0].get("groundingMetadata", {})
    chunks = grounding.get("groundingChunks", [])
    if chunks:
        citations = []
        for chunk in chunks:
            web = chunk.get("web", {})
            if web.get("uri"):
                citations.append((web.get("title", web["uri"]), web["uri"]))
        if citations:
            trust = provider_cfg.get("trust", 0.6)
            citation_facts = "\n".join(
                f'<fact trust="{trust}">{html_mod.escape(t)}: {html_mod.escape(u)}</fact>'
                for t, u in citations
            )
            result = f"<conversation>{result}</conversation>\n{citation_facts}"

    return result


def _call_provider(cfg: Config, bundle: ProviderBundle | None, temperature: float,
                    provider: str, client_api_key: str = "",
                    client_model: str = "",
                    messages: List[Dict] | None = None,
                    chat_settings: Dict | None = None) -> str:
    """Call a provider using a ProviderBundle (preferred) or legacy messages."""
    import config as config_mod

    pcfg = PROVIDERS.get(provider)
    if not pcfg:
        return f"[Unknown provider: {provider}. Available: {', '.join(PROVIDERS.keys())}]"
    prov_type = pcfg.get("type", "")
    # WikiOracle requires an API key. "StrongDemocracy" is a public
    # passphrase that grants access without a personal key.
    _PUBLIC_PASSPHRASE = "StrongDemocracy"
    effective_key = client_api_key or pcfg.get("api_key", "")
    if prov_type == "wikioracle" and not effective_key:
        return f"[No API key for {provider}. Enter your key in settings.]"
    if prov_type == "wikioracle":
        local_msgs = to_nanochat_messages(bundle) if bundle else (messages or [])
        cs = chat_settings or {}
        # Route to the appropriate model: BasicModel or NanoChat (default)
        if client_model == "BasicModel":
            if DEBUG_MODE:
                print(f"[DEBUG] → _call_basicmodel")
            return _call_basicmodel(cfg, local_msgs, temperature,
                                    max_tokens=int(cs.get("max_tokens", 128)),
                                    timeout=int(cs.get("timeout", 120)))
        else:
            if DEBUG_MODE:
                print(f"[DEBUG] → _call_nanochat (127.0.0.1)")
            return _call_nanochat(cfg, local_msgs, temperature,
                                  max_tokens=int(cs.get("max_tokens", 128)),
                                  timeout=int(cs.get("timeout", 120)))
    # Build effective config: merge client + server keys
    effective_cfg = dict(pcfg)
    if client_model:
        effective_cfg["model"] = client_model
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
            # Hot-reload config.xml in case keys were added after server start
            fresh = _load_config()
            fresh_key = (fresh.get("providers", {}).get(provider) or {}).get("api_key", "")
            if fresh_key:
                effective_cfg["api_key"] = fresh_key
                # Update cached PROVIDERS so subsequent calls don't need to reload
                if provider in PROVIDERS:
                    PROVIDERS[provider]["api_key"] = fresh_key
        if not effective_cfg.get("api_key"):
            return f"[No API key for {provider}. Add it to config.xml.]"
    if prov_type == "openai":
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_openai ({effective_cfg.get('url', '?')}, model={effective_cfg.get('model')})")
        oai_msgs = to_openai_messages(bundle) if bundle else (messages or [])
        return _call_openai(oai_msgs, temperature, effective_cfg)
    if prov_type == "anthropic":
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_anthropic ({effective_cfg.get('url', '?')}, model={effective_cfg.get('model')})")
        return _call_anthropic(bundle, temperature, effective_cfg, messages=messages)
    if prov_type == "gemini":
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_gemini (model={effective_cfg.get('model')})")
        return _call_gemini(bundle, temperature, effective_cfg, messages=messages)
    if prov_type == "grok":
        # Grok (xAI) is OpenAI-compatible — reuse the OpenAI adapter
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_openai/grok ({effective_cfg.get('url', '?')}, model={effective_cfg.get('model')})")
        oai_msgs = to_openai_messages(bundle) if bundle else (messages or [])
        return _call_openai(oai_msgs, temperature, effective_cfg)
    if prov_type == "openrouter":
        # OpenRouter is OpenAI-compatible, but some models reject system-role
        # instructions. Use the OpenRouter formatter to fold system text into
        # the first user turn.
        if DEBUG_MODE:
            print(f"[DEBUG] → _call_openai/openrouter ({effective_cfg.get('url', '?')}, model={effective_cfg.get('model')})")
        oai_msgs = to_openrouter_messages(bundle) if bundle else (messages or [])
        return _call_openai(oai_msgs, temperature, effective_cfg)
    return f"[Provider '{provider}' (type={prov_type}) not implemented]"


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

    # Hot-reload config.xml (mirrors _call_provider hot-reload logic)
    if matched_provider_key and not config_mod.STATELESS_MODE:
        fresh = _load_config()
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
        if "googleapis.com" in api_url:
            return os.getenv("GEMINI_API_KEY", "")
    return ""


def _call_dynamic_provider(
    provider_config: dict, messages: List[Dict], temperature: float, cfg: Config,
) -> str:
    """Route a trust-entry provider config to Anthropic, NanoChat, or OpenAI path."""
    from config import is_url_allowed

    api_url = provider_config.get("api_url", "")
    if api_url and not is_url_allowed(api_url):
        return f"[Error: URL not in allowed_urls whitelist: {api_url}]"
    raw_key = provider_config.get("api_key", "")
    model = provider_config.get("model", "")
    timeout = provider_config.get("timeout") or int(cfg.timeout_s)
    max_tokens = provider_config.get("max_tokens") or 2048

    api_key = _resolve_dynamic_api_key(raw_key, api_url)

    trust = provider_config.get("trust", 0.6)
    api_url_lower = api_url.lower()
    if "anthropic.com" in api_url_lower:
        return _call_dynamic_anthropic(api_url, api_key, model, messages, temperature, timeout, max_tokens, trust=trust)
    elif "googleapis.com" in api_url_lower:
        return _call_dynamic_gemini(api_url, api_key, model, messages, temperature, timeout, max_tokens, trust=trust)
    elif "127.0.0.1" in api_url_lower or "localhost" in api_url_lower:
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
    *, trust: float = 0.6,
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
    text_parts = []
    citations = []
    for b in blocks:
        if b.get("type") == "text":
            text_parts.append(b.get("text", ""))
            for cite in b.get("citations", []):
                if cite.get("type") == "web_search_result_location":
                    url_val = cite.get("url", "")
                    title = cite.get("title", url_val)
                    if url_val and url_val not in [c[1] for c in citations]:
                        citations.append((title, url_val))
    result = "".join(text_parts) or "[No content]"
    if citations:
        citation_facts = "\n".join(
            f'<fact trust="{trust}">{html_mod.escape(t)}: {html_mod.escape(u)}</fact>'
            for t, u in citations
        )
        result = f"<conversation>{result}</conversation>\n{citation_facts}"
    return result


def _call_dynamic_gemini(
    api_url: str, api_key: str, model: str,
    messages: List[Dict], temperature: float, timeout: int, max_tokens: int,
    *, trust: float = 0.6,
) -> str:
    """Call a dynamic Gemini endpoint from a <provider> trust entry."""
    # Gemini URL format: {base}/{model}:generateContent
    # If api_url already contains a model, use it directly; otherwise append.
    if ":generateContent" in api_url:
        url = api_url
    else:
        base = api_url.rstrip("/")
        url = f"{base}/{model or 'gemini-2.5-flash'}:generateContent"

    # Convert messages to Gemini contents format
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        return f"[Error from Gemini: HTTP {resp.status_code}] {resp.text[:300]}"

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return "[No response from Gemini]"
    parts = candidates[0].get("content", {}).get("parts", [])
    result = "".join(p.get("text", "") for p in parts if "text" in p) or "[No content]"
    # Map grounding citations to <fact> tags
    grounding = candidates[0].get("groundingMetadata", {})
    chunks = grounding.get("groundingChunks", [])
    if chunks:
        citations = []
        for chunk in chunks:
            web = chunk.get("web", {})
            if web.get("uri"):
                citations.append((web.get("title", web["uri"]), web["uri"]))
        if citations:
            citation_facts = "\n".join(
                f'<fact trust="{trust}">{html_mod.escape(t)}: {html_mod.escape(u)}</fact>'
                for t, u in citations
            )
            result = f"<conversation>{result}</conversation>\n{citation_facts}"
    return result


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
    call_chain: Optional[List[str]] = None,
) -> tuple:
    """HME diamond vote: truth provider fan-out → main provider final.

    1. Fan out to truth providers with Q + direct truths
    2. Call the main provider with truth table + truth provider contributions → R_final
    """
    trust_entries = state.get("truth") or []
    provider_entries = get_provider_entries(trust_entries)

    if not provider_entries:
        raise ValueError("No provider trust entries found")

    primary_entry, primary_config = provider_entries[0]
    primary_id = primary_entry.get("id", "")
    secondaries = provider_entries[1:]

    base_bundle = _build_bundle(state, user_message, query_config, conversation_id)

    # ── Step 1: fan out to betas ──
    d_sources = direct_truth_sources(trust_entries)
    conversation_sources: List[Source] = []
    truth_contributions: List[Source] = []
    if secondaries:
        beta_chain = list(call_chain or [])
        if primary_id:
            beta_chain.append(primary_id)

        def _call_for_eval(pconfig, messages):
            return _call_dynamic_provider(pconfig, messages, temperature, cfg)

        conversation_sources, truth_contributions = evaluate_providers(
            secondaries,
            system=base_bundle.system,
            history=base_bundle.history,
            query=base_bundle.query,
            output=base_bundle.output,
            call_fn=_call_for_eval,
            timeout_s=max(int(cfg.timeout_s), 60),
            call_chain=beta_chain,
            direct_sources=d_sources,
        )

    # ── Step 2: main provider final response ──
    all_provider_sources = conversation_sources + truth_contributions
    final_bundle = build_query(
        state, user_message, query_config,
        conversation_id=conversation_id,
        provider_sources=all_provider_sources,
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

    return response_text, all_provider_sources


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
    candidates = sorted(
        list(root.glob("llm_*.xml")) + list(root.glob("llm_*.json"))
    )
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
) -> tuple[str, Dict[str, Any], list[dict]]:
    """Process a chat turn: derive truth, call providers, update conversations.

    Returns (response_text, updated_state, symmetry_rejected).
    """
    import config as config_mod

    user_msg = (body.get("message") or "").strip()
    query_config = body.get("config", {}) if isinstance(body.get("config"), dict) else {}

    server_eval = runtime_cfg.get("server", {}).get("evaluation", {})
    server_ts = runtime_cfg.get("server", {}).get("truthset", {})
    provider = (
        (query_config.get("provider") or runtime_cfg.get("providers", {}).get("default"))
        .strip()
    )
    client_model = (query_config.get("model") or "").strip()
    print(f"[WikiOracle] Chat request: provider='{provider}' (from client config), "
          f"truth_weight={query_config.get('truthset', {}).get('truth_weight', '?')}")

    temperature = max(0.0, min(2.0, float(
        query_config.get("temp", server_eval.get("temperature", 0.7))
    )))
    # TruthSet settings: truth_weight, store_concrete
    if "truthset" not in query_config or not isinstance(query_config.get("truthset"), dict):
        query_config["truthset"] = {}
    query_config["truthset"].setdefault("truth_weight", float(server_ts.get("truth_weight", 0.7)))
    query_config["truthset"].setdefault("store_concrete", server_ts.get("store_concrete", False))
    # Evaluation settings: url_fetch, max_tokens, timeout
    if "evaluation" not in query_config or not isinstance(query_config.get("evaluation"), dict):
        query_config["evaluation"] = {}
    query_config["evaluation"].setdefault("url_fetch", server_eval.get("url_fetch", False))
    query_config["evaluation"].setdefault("max_tokens", server_eval.get("max_tokens", 128))
    query_config["evaluation"].setdefault("timeout", server_eval.get("timeout", 120))
    # Training settings: truth_max_entries
    server_tr = runtime_cfg.get("server", {}).get("training", {})
    if "training" not in query_config or not isinstance(query_config.get("training"), dict):
        query_config["training"] = {}
    query_config["training"].setdefault("truth_max_entries", int(server_tr.get("truth_max_entries", 1000)))

    conversation_id = body.get("conversation_id")
    branch_from = body.get("branch_from")
    context_conv_id = conversation_id or branch_from

    user_timestamp = utc_now_iso()

    truth_list = state.get("truth") or []
    derived = compute_derived_truth(truth_list)
    for entry in truth_list:
        eid = entry.get("id", "")
        if eid in derived and abs(derived[eid] - entry.get("trust", 0.0)) > 1e-9:
            entry["_derived_trust"] = derived[eid]

    # ── Voting: truth provider fan-out → main provider final ──
    #
    # When dynamic <provider> entries exist, the UI-selected provider
    # acts as the main provider and the dynamic providers act as truth
    # providers.
    #
    # Truth providers with conversation=true participate in the
    # conversation tree (creating a diamond).  Truth providers with
    # conversation=false only contribute direct truths (facts/feelings)
    # invisibly.
    #
    # When there are no dynamic providers, this collapses to a single call.

    dyn_providers = get_provider_entries(truth_list)
    conversation_sources: list = []
    truth_contributions: list = []

    providers_cfg = runtime_cfg.get("providers", {})
    context_text = strip_xhtml(providers_cfg.get("context", ""))
    print(f"[WikiOracle] Chat: provider='{provider}', model='{client_model or PROVIDERS.get(provider, {}).get('model', '?')}', "
          f"context={'yes' if context_text else 'none'} ({len(context_text)} chars), "
          f"api_key={'local' if provider == 'wikioracle' else 'server' if PROVIDERS.get(provider, {}).get('api_key') else 'MISSING'}")
    truth_count = len(state.get("truth") or [])
    truth_weight_flag = query_config.get("truthset", {}).get("truth_weight", "MISSING")

    # Inject context/output from config.providers into query_config
    # so that build_query can read them
    query_config.setdefault("context", providers_cfg.get("context", ""))
    query_config.setdefault("output", providers_cfg.get("output", ""))

    client_api_key = ""
    if config_mod.STATELESS_MODE:
        rc_providers = runtime_cfg.get("providers", {})
        rc_pcfg = rc_providers.get(provider, {})
        client_api_key = rc_pcfg.get("api_key", "")

    # ── Step 1: truth provider fan-out ──
    if dyn_providers:
        print(f"[WikiOracle] Voting: fan out to {len(dyn_providers)} truth provider(s)")
        base_bundle = _build_bundle(state, user_msg, query_config, context_conv_id)
        d_sources = direct_truth_sources(truth_list)
        call_chain: list = []
        def _call_for_eval(pconfig, messages):
            return _call_dynamic_provider(pconfig, messages, temperature, cfg)
        conversation_sources, truth_contributions = evaluate_providers(
            dyn_providers,
            system=base_bundle.system,
            history=base_bundle.history,
            query=base_bundle.query,
            output=base_bundle.output,
            call_fn=_call_for_eval,
            timeout_s=max(int(cfg.timeout_s), 60),
            call_chain=call_chain,
            direct_sources=d_sources,
            truth_context=providers_cfg.get("truth_context"),
            conversation_context=providers_cfg.get("conversation_context"),
        )

    # ── Step 2: main provider final response ──
    all_provider_sources = conversation_sources + truth_contributions
    bundle = build_query(state, user_msg, query_config,
                         conversation_id=context_conv_id,
                         provider_sources=all_provider_sources or None)
    print(f"[WikiOracle] RAG: truth_weight={truth_weight_flag}, truth_entries={truth_count}, "
          f"bundle.sources={len(bundle.sources)}")
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
    response_text = _call_provider(cfg, bundle, temperature, provider, client_api_key, client_model,
                                    chat_settings=query_config.get("evaluation"))
    if config_mod.DEBUG_MODE:
        print(f"[DEBUG] ← Response ({len(response_text)} chars): {response_text[:120]}...")
    llm_provider_name = provider
    llm_model = query_config.get("model", PROVIDERS.get(provider, {}).get("model", provider))

    # ── Extract facts/feelings from the main provider response ──
    # The main provider's response may contain <fact>, <feeling>, and
    # <conversation> tags.  Extract structured truths and use the
    # <conversation> portion (if present) as the display text shown
    # to the user.
    main_conv_text, main_truths = _extract_direct_truths(
        response_text, provider, PROVIDERS.get(provider, {}).get("trust", 1.0),
    )
    if main_truths:
        truth_contributions.extend(main_truths)
        print(f"[WikiOracle] Main provider response: extracted {len(main_truths)} truth(s) "
              f"({sum(1 for t in main_truths if t.kind == 'fact')} facts, "
              f"{sum(1 for t in main_truths if t.kind == 'feeling')} feelings)")

    # Use <conversation> text for display if the main provider produced structured
    # output; otherwise fall back to the full response text.
    display_text = main_conv_text if main_conv_text else response_text

    # Output safety filtering on the display text (all providers)
    if detect_identifiability(display_text):
        display_text = "[Response filtered: identifiable content]"
    asym_reason = detect_asymmetric_claim(display_text)
    if asym_reason:
        display_text = "[Response filtered: asymmetric claim]"

    user_content = ensure_xhtml(user_msg) if user_msg else ""
    assistant_content = ensure_xhtml(display_text)
    assistant_timestamp = utc_now_iso()
    user_display = state.get("client_name", "User")
    llm_display = llm_provider_name

    if user_msg:
        query_entry = {
            "role": "user",
            "username": user_display,
            "time": user_timestamp,
            "content": user_content,
        }
        ensure_message_id(query_entry)
    else:
        query_entry = None

    response_entry = {
        "role": "assistant",
        "username": llm_display,
        "time": assistant_timestamp,
        "content": assistant_content,
    }
    ensure_message_id(response_entry)

    conversations = state.get("conversations", [])
    client_owns_query = config_mod.STATELESS_MODE

    # ── Build conversation tree ──
    # When conversation=true truth providers participated, build a diamond:
    #
    #        root (query only)
    #       /    \
    #     tp1    tp2          ← truth provider children of root
    #       \    /
    #        final            ← child of every truth provider
    #
    # The final node lives as a child of each truth provider (true DAG
    # merge).  The same final object appears in every truth provider's
    # children list so that navigating down from *any* truth provider
    # reaches it.  The XML serializer deduplicates by ID.
    #
    # Without conversation=true truth providers, it's a simple linear
    # conversation: conv: [user_query, main_response]

    has_vote = bool(conversation_sources)

    if has_vote:
        first_words = strip_xhtml(user_content)[:50] if user_content else "(continue)"

        # Final: main provider's synthesized response
        # Parents: all truth providers (true diamond)
        final_conv = {
            "title": f"{llm_display} (final)",
            "messages": [response_entry],
            "children": [],
        }
        ensure_conversation_id(final_conv)
        final_normalized = normalize_conversation(final_conv)

        # Truth provider children: one conversation per conversation=true
        # truth provider response.  Each gets final_conv as a child
        # (shared object = diamond).
        beta_convs = []
        for src in conversation_sources:
            beta_msg = {
                "role": "assistant",
                "username": src.title or src.source_id,
                "time": user_timestamp,
                "content": src.content,
            }
            ensure_message_id(beta_msg)
            beta_conv = {
                "title": src.title or src.source_id,
                "messages": [beta_msg],
                "children": [final_normalized],
            }
            ensure_conversation_id(beta_conv)
            beta_convs.append(beta_conv)

        # Set final's parentId to all truth provider IDs
        beta_ids = [b["id"] for b in beta_convs]
        final_normalized["parentId"] = beta_ids

        # Assemble the root with betas as children
        # Root has only the user query (no prelim)
        root_messages = [query_entry] if query_entry else []
        vote_root = {
            "title": first_words,
            "messages": root_messages,
            "children": [normalize_conversation(b) for b in beta_convs],
            "parentId": None,
        }
        ensure_conversation_id(vote_root)
        conversations.append(normalize_conversation(vote_root))

        state["selected_conversation"] = final_conv["id"]
    else:
        # No voting — simple linear conversation
        all_messages = ([query_entry, response_entry] if query_entry
                        else [response_entry])

        if conversation_id:
            if query_entry and not client_owns_query:
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
                    first_words = strip_xhtml(user_content)[:50] if user_content else "(continue)"
                    new_conv = {
                        "title": first_words,
                        "messages": all_messages,
                        "children": [],
                        "parentId": branch_from,
                    }
                    ensure_conversation_id(new_conv)
                    add_child_conversation(conversations, branch_from, new_conv)
                    state["selected_conversation"] = new_conv["id"]
            else:
                first_words = strip_xhtml(user_content)[:50] if user_content else "(continue)"
                new_conv = {
                    "title": first_words,
                    "messages": all_messages,
                    "children": [],
                    "parentId": branch_from,
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
                    first_words = strip_xhtml(user_content)[:50] if user_content else "(continue)"
                    new_conv = {
                        "title": first_words,
                        "messages": all_messages,
                        "children": [],
                        "parentId": None,
                    }
                    ensure_conversation_id(new_conv)
                    conversations.append(normalize_conversation(new_conv))
                    state["selected_conversation"] = new_conv["id"]
            else:
                first_words = strip_xhtml(user_content)[:50] if user_content else "(continue)"
                new_conv = {
                    "title": first_words,
                    "messages": all_messages,
                    "children": [],
                    "parentId": None,
                }
                ensure_conversation_id(new_conv)
                conversations.append(normalize_conversation(new_conv))
                state["selected_conversation"] = new_conv["id"]

    state["conversations"] = conversations
    # Reset stale selection metadata from the previously active branch before
    # strict state normalization runs on save.
    state["selected_message"] = None
    apply_selection_flags(
        state["conversations"],
        state.get("selected_conversation"),
        state.get("selected_message"),
    )

    # ── Merge main provider-extracted truths into client truth table ──
    # Facts and feelings extracted from the main provider response are
    # added to the state's truth table so they accumulate across turns
    # and participate in DoT computation and training.
    if main_truths:
        if "truth" not in state or not isinstance(state.get("truth"), list):
            state["truth"] = []
        for src in main_truths:
            state["truth"].append({
                "id": src.source_id,
                "title": src.title,
                "trust": src.trust,
                "content": f"<{src.kind}>{src.content}</{src.kind}>",
                "time": assistant_timestamp,
            })

    # ── Post-response pipeline: DoT + truth merge + online training ──
    # These stages run after the user has received the response.
    symmetry_rejected: list[dict] = []
    server_cfg = runtime_cfg.get("server", {})
    tr_cfg = server_cfg.get("training", {})
    ts_cfg = server_cfg.get("truthset", {})
    if tr_cfg.get("enabled", False) and not config_mod.STATELESS_MODE:
        try:
            client_truth = state.get("truth") or []
            author_guid = user_guid(
                state.get("client_name", "User"),
                uid=state.get("client_id") or None,
            )

            # Ensure client ID is stored in state
            state["client_id"] = author_guid

            # Resolve references→facts, authorities→facts, providers→feelings
            # before DoT computation and merge.
            client_truth = resolve_entries(client_truth)

            server_truth_path = Path(tr_cfg.get("truth_corpus_path", "data/truth.xml"))
            server_truth = load_server_truth(server_truth_path)

            # Stage 2: compute DegreeOfTruth (before merge so it measures
            #          the gap between client and pre-merge server truth).
            #
            # DoT range is -1..+1:
            #   +1 = full agreement   (learn a true statement)
            #    0 = no shared context (skip — nothing to learn)
            #   -1 = full disagreement (learn a false statement)
            #
            # Both true (+1) and false (-1) are valuable training signal.
            # A DoT near 0 means the truth tables share no entries; in a
            # future pluralistic model this might instead prompt for user
            # feedback to disambiguate which context applies before
            # committing to a training step.
            dot = compute_degree_of_truth(server_truth, client_truth)

            # Stage 3: merge client truth into server truth
            # Filter per Entanglement Policy (doc/Entanglement.md):
            # - When store_concrete is false (default), only universal
            #   facts persist to the TruthSet.
            # - Identifiable content is always filtered regardless.
            # Client-side override: query_config.truthset.store_concrete
            _store_part = query_config.get("truthset", {}).get(
                "store_concrete", ts_cfg.get("store_concrete", False))
            if not _store_part:
                client_truth = filter_knowledge_only(client_truth)
            client_truth = [
                e for e in client_truth
                if not detect_identifiability(e.get("content", ""))
            ]
            # Symmetry check (doc/Ethics.md §5-8)
            if ts_cfg.get("truth_symmetry", True):
                surviving = []
                for e in client_truth:
                    reason = detect_asymmetric_claim(e.get("content", ""))
                    if reason:
                        symmetry_rejected.append({
                            "id": e.get("id", ""),
                            "content": e.get("content", ""),
                            "reason": reason,
                        })
                    else:
                        surviving.append(e)
                client_truth = surviving
            # Validate operators: reject any whose leaf operands are feelings
            client_truth = validate_operator_operands(client_truth)
            merge_rate = float(tr_cfg.get("merge_rate", 0.1))
            server_truth = merge_client_truth(
                server_truth, client_truth,
                merge_rate=merge_rate, author=author_guid,
            )

            # ── Truth table size cap (truth_max_entries) ──
            # Trim entries with |trust| closest to 0 when table exceeds max.
            _truth_max = int(query_config.get("training", {}).get(
                "truth_max_entries", tr_cfg.get("truth_max_entries", 1000)))
            if len(server_truth) > _truth_max:
                before_count = len(server_truth)
                # Sort by |trust| descending — keep strongest signals
                server_truth.sort(key=lambda e: abs(float(e.get("trust", 0))),
                                  reverse=True)
                server_truth = server_truth[:_truth_max]
                trimmed = before_count - len(server_truth)
                print(f"[WikiOracle] Truth table trimmed: {trimmed} entries removed "
                      f"(was {before_count}, now {len(server_truth)}, "
                      f"max={_truth_max})")

            save_server_truth(server_truth_path, server_truth)
            print(f"[WikiOracle] Online training: DoT={dot:.3f} "
                  f"(server={len(server_truth)} entries, client={len(client_truth)} entries)")

            # Stage 4: train NanoChat (online SFT, if provider is wikioracle)
            # Runs in a background thread so the chat response returns immediately —
            # CPU training on a non-GPU machine can take many seconds.
            #
            # Guard: for external providers, only train when the response
            # produced structured facts (via native tags or citation mapping).
            # This prevents training on unstructured text from providers that
            # didn't produce truth claims we can verify against the truth table.
            _has_main_facts = any(t.kind == "fact" for t in main_truths)
            _is_local = PROVIDERS.get(provider, {}).get("type") == "wikioracle"
            if not _is_local and not _has_main_facts:
                print(f"[WikiOracle] Online training: skipped — external provider "
                      f"'{provider}' produced no structured facts")
            elif _is_local or _has_main_facts:
                nanochat_url = cfg.base_url.rstrip("/")
                # Build the full prompt messages for training
                train_messages = _bundle_to_messages(bundle, provider)
                # Append the response as the final assistant turn
                train_messages.append({"role": "assistant", "content": response_text})
                train_device = tr_cfg.get("device", "cpu")
                # truth_weight from client config (0.0–1.0)
                _truth_weight = float(query_config.get("truthset", {}).get("truth_weight", 0.7))
                _warmup_steps = int(tr_cfg.get("warmup_steps", 50))
                _grad_clip = float(tr_cfg.get("grad_clip", 1.0))
                _anchor_decay = float(tr_cfg.get("anchor_decay", 0.001))
                # Snapshot everything the thread needs — no shared mutable state.
                _train_payload = {
                    "messages": [{"role": m["role"], "content": m.get("content", "")}
                                 for m in train_messages],
                    "dot": dot,
                    "device": train_device,
                    "url": nanochat_url,
                    "truth_weight": _truth_weight,
                    "warmup_steps": _warmup_steps,
                    "grad_clip": _grad_clip,
                    "anchor_decay": _anchor_decay,
                }

                def _do_train(payload: dict) -> None:
                    try:
                        tagged = preprocess_training_example(
                            payload["messages"],
                            degree_of_truth=payload["dot"],
                        )
                        resp = requests.post(
                            f"{payload['url']}/train",
                            json={
                                "messages": tagged,
                                "degree_of_truth": payload["dot"],
                                "device": payload["device"],
                                "truth_weight": payload["truth_weight"],
                                "warmup_steps": payload["warmup_steps"],
                                "grad_clip": payload["grad_clip"],
                                "anchor_decay": payload["anchor_decay"],
                            },
                            timeout=300,
                        )
                        if resp.ok:
                            result = resp.json()
                            loss = result.get("loss")
                            gain = result.get("gain")
                            if gain is not None:
                                print(f"[WikiOracle] Online training: gain={gain:.4f}")
                            elif loss is not None:
                                print(f"[WikiOracle] Online training: loss={loss:.4f}")
                            else:
                                print(f"[WikiOracle] Online training: {result.get('message', 'no-op')}")
                        else:
                            print(f"[WikiOracle] Online training: HTTP {resp.status_code}")
                    except Exception as exc:
                        print(f"[WikiOracle] Online training (bg): {exc}")

                t = threading.Thread(target=_do_train, args=(_train_payload,),
                                     name="wikioracle-train", daemon=True)
                t.start()
                print("[WikiOracle] Online training: dispatched to background thread")
        except Exception as exc:
            print(f"[WikiOracle] Online training pipeline error: {exc}")

    return response_text, state, symmetry_rejected
