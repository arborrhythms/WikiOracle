"""WikiOracle truth processing: trust entry types, implication engine, authority resolution.

Foundational module for trust-table interpretation:
  - XHTML sanitization and normalization utilities
  - Timestamp, hashing, and UUID helpers
  - Trust entry normalization and ID generation
  - <provider>, <src>, <implication>, <authority> XML block parsing
  - Strong Kleene material implication engine (compute_derived_truth)
  - Authority resolution (remote JSONL fetch with certainty scaling)

Dependency: stdlib only (no imports from config, state, or oracle).
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


# ---------------------------------------------------------------------------
# UUID namespace
# ---------------------------------------------------------------------------
# Stable UUID-5 namespace for deterministic WikiOracle ID generation.
WIKIORACLE_UUID_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------
class StateValidationError(ValueError):
    """Raised when state payload shape is incompatible with expectations."""


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def utc_now_iso() -> str:
    """Return the current UTC timestamp in canonical ISO-8601 Zulu format."""
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_iso8601_utc(timestamp: Any) -> bool:
    """Validate strict YYYY-MM-DDTHH:MM:SSZ timestamp strings."""
    if not isinstance(timestamp, str):
        return False
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def _coerce_timestamp(value: Any) -> str:
    """Return value when valid; otherwise replace with current UTC timestamp."""
    if _is_iso8601_utc(value):
        return str(value)
    return utc_now_iso()


def _timestamp_sort_key(timestamp: str) -> tuple:
    """Convert timestamp into a deterministic sortable key tuple."""
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        return (int(dt.replace(tzinfo=timezone.utc).timestamp()), timestamp)
    except ValueError:
        return (0, "")


# ---------------------------------------------------------------------------
# XHTML helpers
# ---------------------------------------------------------------------------

# Regex for control characters that are invalid in XML 1.0 and problematic in
# JSON/JavaScript: C0 controls (except HT, LF, CR), DEL, and C1 controls.
_RE_CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)

# ChatGPT citation artifacts that survive PUA-stripping, e.g. ". citeturn0search3".
_RE_CITE_MARKER = re.compile(r"\s*\bciteturn\d+\w*\d*\b", re.IGNORECASE)


def sanitize_unicode(text: str) -> str:
    """Replace or remove problematic Unicode characters for safe XHTML/JSON.

    * U+2028 (Line Separator) and U+2029 (Paragraph Separator) → newline
    * C0 controls (except tab/LF/CR), DEL, C1 controls → removed
    * U+FEFF (BOM / zero-width no-break space) → removed
    * Normalize to NFC for consistent representation
    """
    if not isinstance(text, str):
        return text
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    text = text.replace("\ufeff", "")
    text = _RE_CONTROL.sub("", text)
    text = _RE_CITE_MARKER.sub("", text)
    text = unicodedata.normalize("NFC", text)
    return text


def _escape_plain_text(text: str) -> str:
    """Wrap plain text in a <p> element with proper HTML escaping."""
    return f"<p>{html.escape(text)}</p>"


def _canonicalize_xml_fragment(fragment: str) -> str:
    """Parse an XHTML fragment and return C14N-canonicalized inner content.

    Uses ET.canonicalize (C14N 2.0) for proper XML normalization.
    Raises ET.ParseError if fragment is not well-formed XML.
    """
    wrapped = f"<root>{fragment}</root>"
    canonical = ET.canonicalize(wrapped)
    inner = canonical.removeprefix("<root>").removesuffix("</root>").strip()
    return inner


def _is_plain_text(fragment: str) -> bool:
    """Check whether a fragment parsed as XML is just text (no child elements)."""
    root = ET.fromstring(f"<root>{fragment}</root>")
    return not list(root) and bool(root.text)


def ensure_xhtml(fragment: Any) -> str:
    """Normalize user content into safe, minimal XHTML fragments.

    Pipeline: sanitize_unicode → parse as XML → canonicalize, or escape as
    plain text.  Plain text (no markup) is wrapped in ``<p>`` with escaping.
    """
    if not isinstance(fragment, str) or not fragment.strip():
        return "<div/>"
    cleaned = sanitize_unicode(fragment).strip()
    try:
        if _is_plain_text(cleaned):
            return _escape_plain_text(cleaned)
        return _canonicalize_xml_fragment(cleaned) or "<div/>"
    except ET.ParseError:
        return _escape_plain_text(cleaned)


def strip_xhtml(content: str) -> str:
    """Remove tags and decode entities from XHTML content."""
    return html.unescape(re.sub(r"<[^>]+>", "", content)).strip()


# ---------------------------------------------------------------------------
# Hashing / ID helpers
# ---------------------------------------------------------------------------
def _stable_sha256(text: str) -> str:
    """Return SHA-256 hex digest for deterministic ID generation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _trust_fingerprint(entry: dict) -> str:
    """Build a stable hash input for trust-entry identity derivation."""
    title = str(entry.get("title", "")).strip()
    timestamp = str(entry.get("time", "")).strip()
    certainty = str(entry.get("certainty", "")).strip()
    content = ensure_xhtml(entry.get("content", ""))
    return _stable_sha256(f"{title}|{timestamp}|{certainty}|{content}")


def ensure_trust_id(entry: dict) -> str:
    """Ensure a trust entry has an ID, deriving a deterministic UUID if missing."""
    trust_id = str(entry.get("id", "")).strip()
    if trust_id:
        return trust_id
    trust_id = str(uuid.uuid5(WIKIORACLE_UUID_NS, _trust_fingerprint(entry)))
    entry["id"] = trust_id
    return trust_id


def _implication_fingerprint(entry: dict) -> str:
    """Build a stable hash input for implication identity derivation."""
    content = ensure_xhtml(entry.get("content", ""))
    return _stable_sha256(f"implication|{content}")


def ensure_implication_id(entry: dict) -> str:
    """Ensure an implication entry has an ID, deriving a deterministic UUID if missing."""
    iid = str(entry.get("id", "")).strip()
    if iid:
        return iid
    iid = str(uuid.uuid5(WIKIORACLE_UUID_NS, _implication_fingerprint(entry)))
    entry["id"] = iid
    return iid


def ensure_authority_id(entry: dict) -> str:
    """Ensure an authority entry has an ID, deriving a deterministic UUID if missing."""
    aid = str(entry.get("id", "")).strip()
    if aid:
        return aid
    aid = str(uuid.uuid5(WIKIORACLE_UUID_NS, _trust_fingerprint(entry)))
    entry["id"] = aid
    return aid


# ---------------------------------------------------------------------------
# Trust entry normalization
# ---------------------------------------------------------------------------
def _normalize_trust_entry(raw: Any) -> dict:
    """Normalize a trust record and clamp certainty into [-1.0, 1.0] (Kleene ternary)."""
    item = dict(raw) if isinstance(raw, dict) else {}
    item["type"] = "trust"
    item["title"] = str(item.get("title", "Trust entry"))
    item["time"] = _coerce_timestamp(item.get("time"))
    certainty = item.get("certainty", 0.0)
    try:
        certainty = float(certainty)
    except (TypeError, ValueError):
        certainty = 0.0
    item["certainty"] = min(1.0, max(-1.0, certainty))
    item["content"] = ensure_xhtml(item.get("content", ""))
    # Use typed ID generation based on content markers
    if "<implication" in item.get("content", ""):
        ensure_implication_id(item)
    elif "<authority" in item.get("content", ""):
        ensure_authority_id(item)
    else:
        ensure_trust_id(item)
    return item


def _provider_sort_key(entry: dict) -> tuple:
    """Sort trust entries by certainty (desc), timestamp (desc), then ID."""
    certainty = entry.get("certainty", 0.0)
    ts = entry.get("time", "")
    eid = entry.get("id", "")
    return (-certainty, _timestamp_sort_key(ts)[0] * -1, eid)


# ---------------------------------------------------------------------------
# Provider / Src parsing
# ---------------------------------------------------------------------------
ALLOWED_DATA_DIR = Path.home() / ".wikioracle" / "keys"


def parse_provider_block(content: str) -> dict | None:
    """Parse the first <provider> XML block from trust-entry content.

    Supports both child-element style and attribute style:
      Child:  <provider><name>claude</name><api_url>...</api_url></provider>
      Attr:   <provider name="claude" api_url="..." model="..." />
    Attributes take precedence only when the corresponding child element is
    absent or empty, so either style (or a mix) works.
    """
    if not isinstance(content, str) or "<provider" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    prov = root.find(".//provider")
    if prov is None:
        return None
    def _val(tag, default=""):
        """Read from child element first, fall back to XML attribute."""
        el = prov.find(tag)
        text = (el.text or "").strip() if el is not None else ""
        if text:
            return text
        # Fall back to attribute on the <provider> element itself
        return prov.get(tag, default)
    result = {
        "name": _val("name", "unknown"),
        "api_url": _val("api_url"),
        "api_key": _val("api_key"),
        "model": _val("model"),
        "timeout": 0,
        "max_tokens": 0,
    }
    try:
        result["timeout"] = int(_val("timeout", "0"))
    except ValueError:
        result["timeout"] = 0
    try:
        result["max_tokens"] = int(_val("max_tokens", "0"))
    except ValueError:
        result["max_tokens"] = 0
    return result


def parse_src_block(content: str) -> dict | None:
    """Parse the first <src> XML block from trust-entry content."""
    if not isinstance(content, str) or "<src" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    src = root.find(".//src")
    if src is None:
        return None
    def _text(tag, default=""):
        """Read and strip child text from src XML nodes."""
        el = src.find(tag)
        return (el.text or "").strip() if el is not None else default
    return {
        "name": _text("name", "unknown"),
        "path": _text("path"),
        "format": _text("format", "text"),
    }


def get_provider_entries(trust_entries: list) -> list:
    """Extract and rank trust entries that contain valid <provider> blocks."""
    result = []
    for entry in trust_entries:
        prov = parse_provider_block(entry.get("content", ""))
        if prov is not None:
            result.append((entry, prov))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


def get_src_entries(trust_entries: list) -> list:
    """Extract and rank trust entries that contain valid <src> blocks."""
    result = []
    for entry in trust_entries:
        src = parse_src_block(entry.get("content", ""))
        if src is not None:
            result.append((entry, src))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


def get_primary_provider(trust_entries: list) -> tuple | None:
    """Return the highest-ranked provider entry/config pair, if any."""
    entries = get_provider_entries(trust_entries)
    return entries[0] if entries else None


def resolve_api_key(raw_key: str) -> str:
    """Resolve file:// API keys from allowlisted paths; otherwise return raw value."""
    if not raw_key or not raw_key.startswith("file://"):
        return raw_key
    rel_path = raw_key[len("file://"):]
    key_path = Path(rel_path).expanduser().resolve()
    allowed = ALLOWED_DATA_DIR.resolve()
    try:
        key_path.relative_to(allowed)
    except ValueError:
        raise StateValidationError(f"API key path outside allowlist: {key_path}")
    raw_path = Path(rel_path).expanduser()
    if raw_path.is_symlink() or key_path.is_symlink():
        raise StateValidationError(f"API key path is a symlink: {raw_path}")
    if ".." in Path(rel_path).parts:
        raise StateValidationError(f"Path traversal in API key path: {rel_path}")
    if not key_path.exists():
        raise StateValidationError(f"API key file not found: {key_path}")
    return key_path.read_text(encoding="utf-8").strip()


def resolve_src_content(src_config: dict) -> str:
    """Load file-backed <src> content from allowlisted paths."""
    path = src_config.get("path", "")
    if not path:
        return ""
    if path.startswith("file://"):
        rel_path = path[len("file://"):]
        src_path = Path(rel_path).expanduser().resolve()
        allowed = ALLOWED_DATA_DIR.resolve()
        try:
            src_path.relative_to(allowed)
        except ValueError:
            raise StateValidationError(f"Src path outside allowlist: {src_path}")
        raw_path = Path(rel_path).expanduser()
        if raw_path.is_symlink() or src_path.is_symlink():
            raise StateValidationError(f"Src path is a symlink: {raw_path}")
        if ".." in Path(rel_path).parts:
            raise StateValidationError(f"Path traversal in src path: {rel_path}")
        if not src_path.exists():
            raise StateValidationError(f"Src file not found: {src_path}")
        return src_path.read_text(encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
# Implication parsing
# ---------------------------------------------------------------------------
def parse_implication_block(content: str) -> dict | None:
    """Parse the first <implication> XML block from trust-entry content.

    Returns { antecedent, consequent, type } where antecedent and consequent
    are trust entry IDs and type is one of: material, strict, relevant.
    """
    if not isinstance(content, str) or "<implication" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    impl = root.find(".//implication")
    if impl is None:
        return None
    def _text(tag, default=""):
        el = impl.find(tag)
        return (el.text or "").strip() if el is not None else default
    antecedent = _text("antecedent")
    consequent = _text("consequent")
    if not antecedent or not consequent:
        return None
    impl_type = _text("type", "material")
    if impl_type not in ("material", "strict", "relevant"):
        impl_type = "material"
    return {
        "antecedent": antecedent,
        "consequent": consequent,
        "type": impl_type,
    }


def get_implication_entries(trust_entries: list) -> list:
    """Extract trust entries that contain valid <implication> blocks."""
    result = []
    for entry in trust_entries:
        impl = parse_implication_block(entry.get("content", ""))
        if impl is not None:
            result.append((entry, impl))
    return result


# ---------------------------------------------------------------------------
# Authority parsing and resolution
# ---------------------------------------------------------------------------
def parse_authority_block(content: str) -> dict | None:
    """Parse the first <authority> XML block from trust-entry content.

    Supports both child-element style and attribute style:
      Child:  <authority><did>did:web:example</did><url>https://...</url></authority>
      Attr:   <authority did="did:web:example" url="https://..." />

    Returns { did, orcid, url, refresh } or None if not an authority entry.
    """
    if not isinstance(content, str) or "<authority" not in content:
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    auth = root.find(".//authority")
    if auth is None:
        return None

    def _val(tag, default=""):
        """Read from child element first, fall back to XML attribute."""
        el = auth.find(tag)
        text = (el.text or "").strip() if el is not None else ""
        return text if text else auth.get(tag, default)

    url = _val("url")
    if not url:
        return None  # URL is required

    refresh = 3600
    try:
        refresh = int(_val("refresh", "3600"))
    except (ValueError, TypeError):
        refresh = 3600

    return {
        "did": _val("did"),
        "orcid": _val("orcid"),
        "url": url,
        "refresh": refresh,
    }


def get_authority_entries(trust_entries: list) -> list:
    """Extract and rank trust entries that contain valid <authority> blocks."""
    result = []
    for entry in trust_entries:
        auth = parse_authority_block(entry.get("content", ""))
        if auth is not None:
            result.append((entry, auth))
    result.sort(key=lambda pair: _provider_sort_key(pair[0]))
    return result


# In-memory cache for fetched authority JSONL: { url: (timestamp, entries) }
_AUTHORITY_CACHE: dict = {}
_AUTHORITY_MAX_RESPONSE_BYTES = 1_048_576  # 1 MB
_AUTHORITY_MAX_ENTRIES = 1000


def resolve_authority_entries(
    authority_entries: list,
    timeout_s: int = 30,
    *,
    allowed_data_dir: str | None = None,
) -> list:
    """Fetch and parse remote authority JSONL files.

    For each (entry, auth_config) pair:
    1. Check cache; if fresh, use cached entries
    2. Otherwise HTTP GET (or file:// read) the auth_config["url"]
    3. Parse each line as JSON
    4. Extract trust entries (type="trust"), skip headers/conversations/authorities
    5. Scale each entry's certainty by the authority entry's certainty
    6. Prefix imported entry IDs: "{authority_id}:{original_id}"

    Returns: list of (authority_entry, list_of_scaled_trust_dicts)
    """
    import time as _time

    results = []
    for entry, auth_config in authority_entries:
        url = auth_config.get("url", "")
        if not url:
            continue

        authority_certainty = entry.get("certainty", 0.0)
        authority_id = entry.get("id", "unknown")
        refresh = auth_config.get("refresh", 3600)

        # Check cache
        now = _time.time()
        cached = _AUTHORITY_CACHE.get(url)
        if cached and (now - cached[0]) < refresh:
            raw_entries = cached[1]
        else:
            raw_entries = _fetch_authority_jsonl(
                url, timeout_s=timeout_s,
                allowed_data_dir=allowed_data_dir,
            )
            _AUTHORITY_CACHE[url] = (now, raw_entries)

        # Scale certainty and namespace IDs
        scaled = []
        for re_entry in raw_entries[:_AUTHORITY_MAX_ENTRIES]:
            # Skip nested authority entries (no recursive fetch)
            if "<authority" in re_entry.get("content", ""):
                continue
            remote_certainty = re_entry.get("certainty", 0.0)
            try:
                remote_certainty = float(remote_certainty)
            except (TypeError, ValueError):
                remote_certainty = 0.0
            scaled_certainty = authority_certainty * remote_certainty
            scaled_certainty = min(1.0, max(-1.0, scaled_certainty))

            remote_id = re_entry.get("id", "")
            namespaced_id = f"{authority_id}:{remote_id}" if remote_id else authority_id

            scaled.append({
                "type": "trust",
                "id": namespaced_id,
                "title": re_entry.get("title", "untitled"),
                "certainty": scaled_certainty,
                "content": re_entry.get("content", ""),
                "time": re_entry.get("time", ""),
                "_authority_id": authority_id,
            })

        results.append((entry, scaled))
    return results


def _fetch_authority_jsonl(
    url: str,
    timeout_s: int = 30,
    allowed_data_dir: str | None = None,
) -> list:
    """Fetch and parse a JSONL file from a URL or file:// path.

    Returns a list of trust entry dicts (type="trust" only).
    On any error, logs a warning and returns [].
    """
    import json as _json

    entries = []
    try:
        if url.startswith("file://"):
            # Local file read (within allowed data dir)
            rel_path = url[len("file://"):]
            file_path = Path(rel_path).expanduser().resolve()
            if allowed_data_dir:
                allowed = Path(allowed_data_dir).resolve()
                try:
                    file_path.relative_to(allowed)
                except ValueError:
                    print(f"[WikiOracle] Authority file outside allowlist: {file_path}")
                    return []
            if not file_path.exists():
                print(f"[WikiOracle] Authority file not found: {file_path}")
                return []
            raw = file_path.read_text(encoding="utf-8")
        elif url.startswith("https://"):
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "WikiOracle/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read(_AUTHORITY_MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
        else:
            print(f"[WikiOracle] Authority URL scheme not allowed: {url}")
            return []

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("type") == "trust":
                entries.append(rec)

    except Exception as exc:
        print(f"[WikiOracle] Authority fetch failed for {url}: {exc}")
        return []

    return entries


# ---------------------------------------------------------------------------
# Derived truth: Kleene implication engine
# ---------------------------------------------------------------------------
def compute_derived_truth(trust_entries: list) -> dict:
    """Evaluate all implication entries and return a derived truth table.

    Returns: { entry_id: derived_certainty } for ALL entries (including those
    unchanged), suitable for overlaying onto the trust table during RAG ranking.

    Uses Strong Kleene material implication on the [-1,+1] certainty scale:
      negation:    not(A) = -A
      disjunction: A or B = max(A, B)
      implication: A -> B = max(-A, B)   (i.e. not-A or B)

    Iterates to fixed point (implications can chain). Max 100 iterations.
    """
    # Build certainty lookup from static values
    certainty = {}
    for entry in trust_entries:
        eid = entry.get("id", "")
        if eid:
            certainty[eid] = entry.get("certainty", 0.0)

    # Extract implications
    implications = []
    for entry in trust_entries:
        impl = parse_implication_block(entry.get("content", ""))
        if impl is not None:
            implications.append(impl)

    if not implications:
        return certainty

    # Only entries that start at 0.0 (ignorance) are derivable.
    # Entries with explicit positive or negative certainty are ground truth
    # and should not be overridden by implication chains.
    derivable = {eid for eid, c in certainty.items() if c == 0.0}

    # Fixed-point iteration
    for _ in range(100):
        changed = False
        for impl in implications:
            ant_id = impl["antecedent"]
            con_id = impl["consequent"]
            if con_id not in derivable:
                continue  # Don't override explicit certainty
            ant_c = certainty.get(ant_id, 0.0)
            con_c = certainty.get(con_id, 0.0)

            # Modus ponens: if antecedent is believed (positive), the
            # consequent's derived certainty is raised to match.
            # Only applies to derivable entries (initial certainty 0.0).
            if ant_c > 0 and con_id in certainty:
                new_con = max(con_c, ant_c)
                if abs(new_con - con_c) > 1e-9:
                    certainty[con_id] = new_con
                    changed = True

        if not changed:
            break

    return certainty
