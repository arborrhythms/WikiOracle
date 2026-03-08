"""Sensation — preprocessing pipeline for XML-tagged training data.

Transforms plain-text conversations into XML-tagged JSONL so that
NanoChat learns to understand WikiOracle's structured protocol.

Works for both:
  1. Batch retagging of the NanoChat SFT corpus (identity_conversations.jsonl)
  2. Dynamic training examples from the WikiOracle online training pipeline

The name "Sensation" comes from the epistemological pipeline:
  Sensation → Perception → Cognition
Raw input data (sensation) is structured and tagged before it reaches
the model (cognition).

───────────────────────────────────────────────────────────────────
Korzybski IS Detection
───────────────────────────────────────────────────────────────────

Alfred Korzybski (Science and Sanity, 1933) observed that the English
copula "is" conflates several distinct relations:

  • IS of identity:      "Socrates is a man"
  • IS of predication:   "The sky is blue"
  • IS of existence:     "There are eight planets"

Each of these asserts something verifiable about the world — a *fact*
that is bound to a specific spacetime context.  "The cup is on the
table" is only true at a particular place and time; at a different
spacetime it may not be.

The detector below classifies sentences heuristically:
  → Sentences with an IS-pattern become <fact trust="0.5">
  → Everything else becomes <feeling> (subjective, not penalizable)

Feelings are orthogonal to truth: in the tetralemma (true / false /
both / neither), feelings occupy the *neither* position.  They carry
no trust attribute, are not used in model training, and are not
persisted in the server truth table.  Poetry is a canonical example.

Facts are classified by kind:
  → "knowledge" — inferential / universal (no spatiotemporal binding)
  → "news"      — direct perception bound to a specific place and time

The server persists only knowledge facts.  News facts are session-only
to avoid worldline capture (identity collapse through spatiotemporal
observation).  See doc/BuddhistLogic.md for the philosophical basis.

This is deliberately conservative: hedged claims ("might be"),
questions, and subjective markers ("I think") override IS detection
and produce <feeling> instead.
───────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from html import escape as html_escape
from pathlib import Path
from typing import Any

# ── sibling imports (when called from the WikiOracle tree) ──────
try:
    from truth import (
        WIKIORACLE_UUID_NS,
        ensure_trust_id,
        utc_now_iso,
        sanitize_unicode,
    )
except ImportError:
    # Fallback for standalone / test usage
    WIKIORACLE_UUID_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

    def utc_now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def ensure_trust_id(entry: dict) -> str:
        import hashlib
        raw = entry.get("content", "") + entry.get("title", "")
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return str(uuid.uuid5(WIKIORACLE_UUID_NS, h))

    def sanitize_unicode(text: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


# =====================================================================
#  Korzybski IS detection — heuristic sentence classifier
# =====================================================================

# ── Subjective / hedging markers (override IS detection) ────────

_SUBJECTIVE_RE = re.compile(
    r"""(?ix)                  # case-insensitive, verbose
    (?:^|\b)(?:
        i\s+(?:think|feel|believe|guess|hope|wish|imagine|suspect|suppose)
      | it\s+(?:seems?|appears?|looks?\s+like)
      | (?:maybe|perhaps|probably|arguably|supposedly|apparently)
      | (?:might|could|would|should)\s+be
      | in\s+my\s+(?:opinion|view|experience)
      | (?:not\s+quite|not\s+(?:exactly|necessarily))
      | personally
    )\b
    """,
)

_QUESTION_RE = re.compile(r"\?\s*$")

_META_DISCOURSE_RE = re.compile(
    r"""(?ix)
    (?:^|\b)(?:
        (?:that(?:'s|\s+is)\s+(?:a\s+)?(?:great|good|interesting|fair|excellent|cool|nice|awesome)
            (?:\s+(?:question|point|observation|topic))?)
      | (?:(?:it|that)\s+is\s+(?:great|good|interesting|fair|excellent|cool|nice|awesome)\s*[!.])
      | (?:let\s+me\s+(?:explain|clarify|break|walk))
      | (?:to\s+(?:be\s+clear|summarize|sum\s+up|put\s+it))
      | (?:I\s+(?:can\s+help|am\s+happy\s+to|would\s+be))
      | (?:(?:great|good)\s+(?:question|point))
      | (?:absolutely|exactly|definitely|certainly)\s*[!.]
    )\b
    """,
)


def is_subjective(text: str) -> bool:
    """Return True if *text* contains hedging / subjective markers."""
    return bool(_SUBJECTIVE_RE.search(text))


def _is_question(text: str) -> bool:
    return bool(_QUESTION_RE.search(text))


def _is_meta_discourse(text: str) -> bool:
    return bool(_META_DISCOURSE_RE.search(text))


# ── IS-pattern regexes ──────────────────────────────────────────

# IS of identity / predication:  "X is/are [a/an/the] Y"
_IS_IDENTITY_RE = re.compile(
    r"""(?ix)
    \b(?:is|are|was|were)\s+
    (?:a|an|the|one\s+of(?:\s+the)?|)\s*
    [A-Za-z]
    """,
)

# IS of existence:  "there is/are X"
_IS_EXISTENCE_RE = re.compile(
    r"""(?ix)
    \bthere\s+(?:is|are|was|were|exist[s]?)\b
    """,
)

# Mereological:  "X contains / includes / is part of / consists of Y"
_IS_MEREOLOGICAL_RE = re.compile(
    r"""(?ix)
    \b(?:
        contains?
      | includes?
      | is\s+(?:part|a\s+part|composed|comprised|made\s+up)\s+of
      | consists?\s+of
      | is\s+(?:inside|within|between|among)
    )\b
    """,
)

# Quantity:  "X has/have N Y"
_IS_QUANTITY_RE = re.compile(
    r"""(?ix)
    \b(?:has|have|had)\s+
    (?:about|approximately|roughly|exactly|at\s+least|over|under|nearly)?\s*
    \d+
    """,
)

# Definition:  "X is called / known as / defined as Y"
_IS_DEFINITION_RE = re.compile(
    r"""(?ix)
    \b(?:is|are)\s+
    (?:called|known\s+as|defined\s+as|referred\s+to\s+as|named)
    \b
    """,
)


def detect_is_type(text: str) -> str | None:
    """Classify *text* by Korzybski IS subtype.

    Returns
    -------
    "identity" | "existence" | "mereological" | "quantity" | "definition" | None
    """
    # Order matters — more specific patterns first
    if _IS_DEFINITION_RE.search(text):
        return "definition"
    if _IS_EXISTENCE_RE.search(text):
        return "existence"
    if _IS_MEREOLOGICAL_RE.search(text):
        return "mereological"
    if _IS_QUANTITY_RE.search(text):
        return "quantity"
    if _IS_IDENTITY_RE.search(text):
        return "identity"
    return None


def classify_statement(text: str) -> tuple[str, str | None]:
    """Top-level classifier for a single sentence.

    Returns
    -------
    ("fact", is_subtype)    — verifiable assertion (IS-pattern detected)
    ("feeling", None)       — subjective / hedged / question / meta
    """
    if not text or not text.strip():
        return ("feeling", None)

    stripped = text.strip()

    # Questions are never facts
    if _is_question(stripped):
        return ("feeling", None)

    # Subjective / hedged → feeling
    if is_subjective(stripped):
        return ("feeling", None)

    # Meta-discourse → feeling
    if _is_meta_discourse(stripped):
        return ("feeling", None)

    # Try IS detection
    is_type = detect_is_type(stripped)
    if is_type is not None:
        return ("fact", is_type)

    return ("feeling", None)


# =====================================================================
#  Sentence splitting
# =====================================================================

# Split on sentence-ending punctuation, keeping the delimiter attached.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'\(])")


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences.  Keeps short fragments intact."""
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# =====================================================================
#  XML tag wrapping
# =====================================================================

_DEFAULT_TRUST = 0.5


def _escape_xml(text: str) -> str:
    """Escape text for safe embedding inside XML content."""
    return html_escape(text, quote=True)


def _wrap_fact(text: str, trust: float = _DEFAULT_TRUST,
               place: str = "", time: str = "") -> str:
    """Wrap *text* in a ``<fact>`` tag with trust attribute.

    Optional ``<place>`` and ``<time>`` child elements are emitted when
    non-empty.

    Parameters
    ----------
    trust : float
        Trust score for the assertion.
    place : str
        Optional spatiotemporal place binding (emitted as child element).
    time : str
        Optional spatiotemporal time binding (emitted as child element).
    """
    safe = _escape_xml(text)
    place_el = f"<place>{_escape_xml(place)}</place>" if place else ""
    time_el = f"<time>{_escape_xml(time)}</time>" if time else ""
    return f'<fact trust="{trust}">{place_el}{time_el}{safe}</fact>'


def _wrap_feeling(text: str, place: str = "", time: str = "") -> str:
    """Wrap *text* in a ``<feeling>`` tag (no trust attribute).

    Feelings are orthogonal to the truth lattice.  In the tetralemma
    (true / false / both / neither), feelings occupy the *neither*
    position — they are not penalizable if incorrect, and they are
    excluded from model training.  Poetry is a canonical example.

    Optional ``<place>`` and ``<time>`` child elements are emitted when
    non-empty.
    """
    place_el = f"<place>{_escape_xml(place)}</place>" if place else ""
    time_el = f"<time>{_escape_xml(time)}</time>" if time else ""
    return f"<feeling>{place_el}{time_el}{_escape_xml(text)}</feeling>"


def tag_message(
    content: str,
    role: str,
    trust: float | None = None,
) -> str:
    """Wrap message content in ``<Q>``/``<R>`` and ``<fact>``/``<feeling>`` tags.

    Sentences are classified individually — a message may contain both
    ``<fact>`` and ``<feeling>`` segments.  Adjacent sentences of the
    same type are merged under one tag.

    Parameters
    ----------
    content : str
        Raw plain-text message content.
    role : str
        ``"user"`` → ``<Q>``; ``"assistant"`` → ``<R>``.
    trust : float | None
        If provided, ALL sentences are wrapped as ``<fact>`` with this
        trust value (overrides heuristic detection).

    Returns
    -------
    str
        XML-tagged message content.
    """
    wrapper = "Q" if role == "user" else "R"
    if not content or not content.strip():
        return f"<{wrapper}><feeling></feeling></{wrapper}>"

    clean = sanitize_unicode(content.strip())
    sentences = _split_sentences(clean)

    # Build runs of same-type segments
    segments: list[str] = []
    for sent in sentences:
        if trust is not None:
            # Explicit trust overrides heuristic
            segments.append(_wrap_fact(sent, trust=trust))
        else:
            tag_type, _ = classify_statement(sent)
            if tag_type == "fact":
                segments.append(_wrap_fact(sent))
            else:
                segments.append(_wrap_feeling(sent))

    inner = " ".join(segments)
    return f"<{wrapper}>{inner}</{wrapper}>"


# =====================================================================
#  Fact extraction (for Truth records)
# =====================================================================

def _extract_facts(content: str, trust: float | None = None) -> list[dict]:
    """Extract fact-classified sentences from *content* as truth entries.

    Only facts are extracted — feelings are explicitly excluded from truth
    records because they are orthogonal to the truth lattice (the *neither*
    position of the tetralemma).

    Returns a list of dicts suitable for JSONL truth records.
    """
    facts = []
    sentences = _split_sentences(sanitize_unicode(content.strip()))
    for sent in sentences:
        if trust is not None:
            # Explicit trust — everything is a fact
            tag_type = "fact"
        else:
            tag_type, _ = classify_statement(sent)

        if tag_type == "fact":
            t = trust if trust is not None else _DEFAULT_TRUST
            entry = {
                "type": "truth",
                "title": sent[:80],
                "trust": t,
                "content": (
                    f'<fact trust="{t}">'
                    f"{_escape_xml(sent)}</fact>"
                ),
                "time": utc_now_iso(),
            }
            entry["id"] = ensure_trust_id(entry)
            facts.append(entry)
    return facts


# =====================================================================
#  Conversation-level processing
# =====================================================================

def preprocess_conversation(
    messages: list[dict],
    extract_truth: bool = True,
) -> dict:
    """Process a full conversation (list of role/content dicts).

    Parameters
    ----------
    messages : list[dict]
        ``[{"role": "user", "content": "..."}, ...]``
    extract_truth : bool
        If True, extract detected facts into a separate truth_entries list.

    Returns
    -------
    dict
        ``{"messages": [tagged], "truth_entries": [facts]}``
    """
    tagged: list[dict] = []
    truth_entries: list[dict] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        tagged_content = tag_message(content, role)
        tagged.append({"role": role, "content": tagged_content})

        if extract_truth:
            facts = _extract_facts(content)
            truth_entries.extend(facts)

    return {"messages": tagged, "truth_entries": truth_entries}


# =====================================================================
#  Dynamic training example (called from response.py pipeline)
# =====================================================================

_RE_FEELING_BLOCK = re.compile(
    r"<feeling(?:\s[^>]*)?>.*?</feeling>",
    re.DOTALL,
)
_RE_FEELING_SELFCLOSE = re.compile(
    r"<feeling(?:\s[^>]*)?/>",
)


def strip_feelings_from_training(messages: list[dict]) -> list[dict]:
    """Remove ``<feeling>`` blocks from training messages.

    Feelings must not be used to train model parameters (Entanglement
    policy, doc/Entanglement.md).  This function strips all
    ``<feeling>...</feeling>`` and ``<feeling .../>`` blocks from
    message content.  Messages that become empty after stripping are
    removed entirely.

    Parameters
    ----------
    messages : list[dict]
        Tagged messages (``[{"role": ..., "content": ...}, ...]``).

    Returns
    -------
    list[dict]
        Messages with feeling content removed.
    """
    result = []
    for msg in messages:
        content = msg.get("content", "")
        content = _RE_FEELING_BLOCK.sub("", content)
        content = _RE_FEELING_SELFCLOSE.sub("", content)
        content = content.strip()
        if content:
            result.append({"role": msg["role"], "content": content})
    return result


def preprocess_training_example(
    messages: list[dict],
    degree_of_truth: float,
) -> list[dict]:
    """Tag a single training example for the ``/train`` endpoint.

    Returns the same messages list shape with XML tags in content,
    with ``<feeling>`` blocks stripped — feelings must not train
    model parameters (doc/Entanglement.md).

    The degree_of_truth is NOT used for trust assignment here — it
    controls learning rate scaling in nanochat_ext.py.  Trust values
    inside the XML are per-sentence heuristic estimates.

    Parameters
    ----------
    messages : list[dict]
        ``[{"role": "user", "content": "..."}, ...]``
    degree_of_truth : float
        The DoT for this example (informational; not used for tagging).

    Returns
    -------
    list[dict]
        Tagged messages with feelings stripped, same shape as input.
    """
    result = preprocess_conversation(messages, extract_truth=False)
    return strip_feelings_from_training(result["messages"])


# =====================================================================
#  Corpus-level batch processing
# =====================================================================

def preprocess_corpus(
    input_path: Path,
    output_path: Path,
    user_meta: dict | None = None,
    server_meta: dict | None = None,
) -> dict:
    """Batch-convert a JSONL corpus file.

    Input format: each line is a JSON array of role/content message dicts.
    Output format: JSONL with User/Server/Conversation/Truth record types.

    Parameters
    ----------
    input_path : Path
        Source JSONL (e.g. ``identity_conversations.jsonl``).
    output_path : Path
        Destination JSONL with XML-tagged records.
    user_meta : dict | None
        Optional metadata for the ``<User>`` record.
    server_meta : dict | None
        Optional metadata for the ``<Server>`` record.

    Returns
    -------
    dict
        ``{"processed": int, "facts_found": int, "feelings_found": int,
           "errors": int}``
    """
    inp = Path(input_path)
    out = Path(output_path)

    stats = {"processed": 0, "facts_found": 0, "feelings_found": 0, "errors": 0}

    now = utc_now_iso()
    um = user_meta or {}
    sm = server_meta or {}

    with inp.open("r", encoding="utf-8") as fin, \
         out.open("w", encoding="utf-8") as fout:

        # ── Write header records ────────────────────────────────
        user_record = {
            "type": "user",
            "username": um.get("username", "Human"),
            "uid": um.get("uid", str(uuid.uuid5(WIKIORACLE_UUID_NS, "corpus-user"))),
            "time": now,
        }
        fout.write(json.dumps(user_record, ensure_ascii=False) + "\n")

        server_record = {
            "type": "server",
            "name": sm.get("name", "WikiOracle"),
            "version": sm.get("version", "1.0"),
            "time": now,
        }
        fout.write(json.dumps(server_record, ensure_ascii=False) + "\n")

        # ── Process conversations ───────────────────────────────
        for line_no, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                messages = json.loads(line)
                if not isinstance(messages, list):
                    stats["errors"] += 1
                    continue

                result = preprocess_conversation(messages, extract_truth=True)

                # Conversation record
                conv_id = str(uuid.uuid5(
                    WIKIORACLE_UUID_NS, f"corpus-conv-{line_no}"
                ))
                conv_record = {
                    "type": "conversation",
                    "id": conv_id,
                    "messages": result["messages"],
                }
                fout.write(json.dumps(conv_record, ensure_ascii=False) + "\n")

                # Truth records
                for entry in result["truth_entries"]:
                    fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    stats["facts_found"] += 1

                # Count feelings (messages minus facts)
                for msg in result["messages"]:
                    stats["feelings_found"] += msg["content"].count("<feeling>")

                stats["processed"] += 1

            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                print(f"  ⚠ line {line_no}: {exc}", file=sys.stderr)
                stats["errors"] += 1

    return stats


# =====================================================================
#  SFT corpus preparation (for NanoChat retraining)
# =====================================================================

def prepare_sft_corpus(
    input_path: Path,
    output_path: Path,
) -> dict:
    """Convert a NanoChat SFT corpus (identity_conversations.jsonl) to
    XML-tagged JSONL suitable for retraining with WikiOracle's protocol.

    Each input line is a JSON array of ``{"role": ..., "content": ...}``
    message dicts.  Output lines are the same shape but with content
    XML-tagged using ``<Q>``/``<R>`` and ``<fact>``/``<feeling>`` tags.
    Feelings are stripped from the output since the training corpus
    should contain only fact-bearing content (matching the online
    training pipeline's ``strip_feelings_from_training()``).

    This is the batch equivalent of ``preprocess_training_example()``
    but designed for the full SFT corpus rather than a single interaction.

    Parameters
    ----------
    input_path : Path
        Source JSONL — each line is a JSON array of role/content dicts.
    output_path : Path
        Destination JSONL — same shape, XML-tagged and feelings-stripped.

    Returns
    -------
    dict
        ``{"processed": int, "skipped_empty": int, "errors": int}``
    """
    inp = Path(input_path)
    out = Path(output_path)

    stats = {"processed": 0, "skipped_empty": 0, "errors": 0}

    with inp.open("r", encoding="utf-8") as fin, \
         out.open("w", encoding="utf-8") as fout:

        for line_no, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                messages = json.loads(line)
                if not isinstance(messages, list):
                    stats["errors"] += 1
                    continue

                # Tag and strip feelings (same as online training pipeline)
                tagged = preprocess_training_example(messages, degree_of_truth=1.0)

                if not tagged:
                    stats["skipped_empty"] += 1
                    continue

                fout.write(json.dumps(tagged, ensure_ascii=False) + "\n")
                stats["processed"] += 1

            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                print(f"  ⚠ line {line_no}: {exc}", file=sys.stderr)
                stats["errors"] += 1

    return stats


# =====================================================================
#  CLI
# =====================================================================

def main() -> None:
    """Command-line interface.

    Usage::

        python bin/sensation.py corpus INPUT.jsonl OUTPUT.jsonl
        python bin/sensation.py sft INPUT.jsonl OUTPUT.jsonl
        python bin/sensation.py tag "Some plain text sentence."
    """
    if len(sys.argv) < 2:
        print("Usage:")
        print("  sensation.py corpus INPUT.jsonl OUTPUT.jsonl   — full corpus with truth records")
        print("  sensation.py sft INPUT.jsonl OUTPUT.jsonl      — SFT-ready tagged corpus")
        print("  sensation.py tag \"Some text to classify\"")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "corpus":
        if len(sys.argv) < 4:
            print("Usage: sensation.py corpus INPUT.jsonl OUTPUT.jsonl")
            sys.exit(1)
        inp = Path(sys.argv[2])
        out = Path(sys.argv[3])
        if not inp.exists():
            print(f"Input file not found: {inp}", file=sys.stderr)
            sys.exit(1)
        print(f"Preprocessing {inp} → {out} ...")
        stats = preprocess_corpus(inp, out)
        print(f"Done. {stats['processed']} conversations processed.")
        print(f"  Facts found:    {stats['facts_found']}")
        print(f"  Feeling tags:   {stats['feelings_found']}")
        print(f"  Errors:         {stats['errors']}")

    elif cmd == "sft":
        if len(sys.argv) < 4:
            print("Usage: sensation.py sft INPUT.jsonl OUTPUT.jsonl")
            sys.exit(1)
        inp = Path(sys.argv[2])
        out = Path(sys.argv[3])
        if not inp.exists():
            print(f"Input file not found: {inp}", file=sys.stderr)
            sys.exit(1)
        print(f"Preparing SFT corpus {inp} → {out} ...")
        stats = prepare_sft_corpus(inp, out)
        print(f"Done. {stats['processed']} conversations processed.")
        print(f"  Skipped (empty): {stats['skipped_empty']}")
        print(f"  Errors:          {stats['errors']}")

    elif cmd == "tag":
        text = " ".join(sys.argv[2:])
        tag_type, is_subtype = classify_statement(text)
        tagged = tag_message(text, "user")
        print(f"Classification: {tag_type}" +
              (f" ({is_subtype})" if is_subtype else ""))
        print(f"Tagged: {tagged}")

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
