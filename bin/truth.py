"""WikiOracle truth processing: trust entry types, operator engine, authority resolution.

Foundational module for trust-table interpretation:
  - XHTML sanitization and normalization utilities
  - Timestamp, hashing, and UUID helpers
  - Trust entry normalization and ID generation
  - Subtypes (all self-describing XHTML with id/trust/title attrs):
      <fact>       — plain text assertion (penalizable if incorrect)
      <feeling>    — subjective claim (not penalizable if incorrect)
      <reference>  — external link (href attr)
      <and>/<or>/<not>/<non> — operators with <child id="..."/> refs
      <provider>   — LLM provider config (name, api_url, model attrs)
      <authority>  — remote trust table import (did, url attrs)
  - Strong Kleene operator engine (compute_derived_truth)
  - Authority resolution (remote JSONL fetch with trust scaling)

Dependency: stdlib only (no imports from config, state, or oracle).
"""

from __future__ import annotations

import collections
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
    trust_val = str(entry.get("trust", "")).strip()
    content = ensure_xhtml(entry.get("content", ""))
    return _stable_sha256(f"{title}|{timestamp}|{trust_val}|{content}")


def ensure_trust_id(entry: dict) -> str:
    """Ensure a trust entry has an ID, deriving a deterministic UUID if missing."""
    trust_id = str(entry.get("id", "")).strip()
    if trust_id:
        return trust_id
    trust_id = str(uuid.uuid5(WIKIORACLE_UUID_NS, _trust_fingerprint(entry)))
    entry["id"] = trust_id
    return trust_id


def _operator_fingerprint(entry: dict) -> str:
    """Build a stable hash input for operator identity derivation."""
    content = ensure_xhtml(entry.get("content", ""))
    return _stable_sha256(f"operator|{content}")


def ensure_operator_id(entry: dict) -> str:
    """Ensure an operator entry has an ID, deriving a deterministic UUID if missing."""
    oid = str(entry.get("id", "")).strip()
    if oid:
        return oid
    oid = str(uuid.uuid5(WIKIORACLE_UUID_NS, _operator_fingerprint(entry)))
    entry["id"] = oid
    return oid


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
def _has_operator_tag(content: str) -> bool:
    """Check whether content contains an operator tag (<and>, <or>, <not>, <non>)."""
    return ("<and" in content or "<or" in content or "<not" in content
            or "<non" in content)


# Recognized XHTML root tags for trust entries.
_RECOGNIZED_TAGS = frozenset({"fact", "feeling", "reference", "and", "or", "not", "non", "provider", "authority"})


def _parse_root_attrs(content: str) -> dict | None:
    """Parse XHTML content and extract root element tag name and attributes.

    Returns { tag, id, trust, title, root_el } or None if content
    doesn't have a recognized root tag.

    NOTE: id, trust, and title are now optional for XHTML entries.
    These attributes may be present in legacy/migrating entries but are
    canonical on the JSON envelope, not in the XHTML.
    """
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    # Find first recognized child element
    for child in root:
        tag = child.tag
        if tag in _RECOGNIZED_TAGS:
            result = {"tag": tag, "root_el": child}
            result["id"] = child.get("id", "")
            try:
                result["trust"] = float(child.get("trust", ""))
            except (TypeError, ValueError):
                result["trust"] = None
            result["title"] = child.get("title", "")
            # Extract <place> and <time> as child elements (not attributes)
            place_el = child.find("place")
            result["place"] = (place_el.text or "").strip() if place_el is not None else ""
            time_el = child.find("time")
            result["time_val"] = (time_el.text or "").strip() if time_el is not None else ""
            return result
    return None


def _migrate_legacy_content(item: dict) -> str:
    """Migrate pre-XHTML-spec content into the new self-describing format.

    Handles:
      - Plain <p> text → <fact>text</fact> (id/trust/title on JSON envelope)
      - Bare <a href>  → <reference href="...">text</reference> (attributes on JSON)
      - Old <and>/<or>/<not>/<non> with <ref>text</ref> → same tag with <child id="..."/>
        Also extract child IDs to arg1/arg2 on the JSON entry for new format
      - <provider> → remove name and state_url attrs; convert state_url to nested <authority url="..."/>
      - <authority> → remove did and orcid attrs; keep url and refresh
    Returns updated content string and may mutate item to set arg1/arg2 for operators.
    """
    content = item.get("content", "")
    eid = item.get("id", "")
    trust_val = item.get("trust", 0.0)
    title = item.get("title", "")

    def _esc_attr(v):
        return str(v).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

    def _common_attrs_legacy():
        """Legacy attribute style (only for migration fallback)."""
        parts = []
        if eid:
            parts.append(f'id="{_esc_attr(eid)}"')
        parts.append(f'trust="{trust_val}"')
        if title:
            parts.append(f'title="{_esc_attr(title)}"')
        return " ".join(parts)

    # Already has recognized root tag — no migration needed
    parsed = _parse_root_attrs(content)
    if parsed and parsed["tag"] in _RECOGNIZED_TAGS:
        return content

    # Operator migration: <and><ref>x</ref>...</and> → <and><child id="x"/>...</and>
    # Also extract child IDs to arg1/arg2 on the JSON entry
    if _has_operator_tag(content):
        try:
            root = ET.fromstring(f"<root>{content}</root>")
        except ET.ParseError:
            return content
        for tag in ("and", "or", "not", "non"):
            el = root.find(f".//{tag}")
            if el is not None:
                # Migrate <ref>text</ref> → <child id="text"/>
                for ref_el in el.findall("ref"):
                    ref_id = (ref_el.text or "").strip()
                    child_el = ET.SubElement(el, "child")
                    child_el.set("id", ref_id)
                    child_el.tail = ref_el.tail
                    el.remove(ref_el)

                # Extract child IDs for arg1/arg2 on JSON entry
                child_ids = []
                for child_el in el.findall("child"):
                    ref_id = (child_el.get("id") or "").strip()
                    if ref_id:
                        child_ids.append(ref_id)

                if child_ids:
                    if len(child_ids) >= 1:
                        item["arg1"] = child_ids[0]
                    if len(child_ids) >= 2:
                        item["arg2"] = child_ids[1]

                inner = ET.tostring(root, encoding="unicode", method="xml")
                return inner.removeprefix("<root>").removesuffix("</root>").strip()
        return content

    # Authority migration: remove did/orcid attrs; keep url and refresh
    if "<authority" in content:
        try:
            root = ET.fromstring(f"<root>{content}</root>")
            auth = root.find(".//authority")
            if auth is not None:
                # Remove legacy attributes
                if "did" in auth.attrib:
                    del auth.attrib["did"]
                if "orcid" in auth.attrib:
                    del auth.attrib["orcid"]
                # Also remove id/trust/title from XHTML (now envelope-only)
                if "id" in auth.attrib:
                    del auth.attrib["id"]
                if "trust" in auth.attrib:
                    del auth.attrib["trust"]
                if "title" in auth.attrib:
                    del auth.attrib["title"]
                inner = ET.tostring(root, encoding="unicode", method="xml")
                return inner.removeprefix("<root>").removesuffix("</root>").strip()
        except ET.ParseError:
            pass
        return content

    # Provider migration: remove name and state_url attrs; convert state_url to <authority url="..."/>
    if "<provider" in content:
        try:
            root = ET.fromstring(f"<root>{content}</root>")
            prov = root.find(".//provider")
            if prov is not None:
                # Extract state_url if present and convert to nested <authority>
                state_url = prov.get("state_url", "")
                if state_url:
                    # Create nested <authority> element
                    auth_el = ET.SubElement(prov, "authority")
                    auth_el.set("url", state_url)

                # Remove legacy attributes
                if "name" in prov.attrib:
                    del prov.attrib["name"]
                if "state_url" in prov.attrib:
                    del prov.attrib["state_url"]
                # Also remove id/trust/title from XHTML (now envelope-only)
                if "id" in prov.attrib:
                    del prov.attrib["id"]
                if "trust" in prov.attrib:
                    del prov.attrib["trust"]
                if "title" in prov.attrib:
                    del prov.attrib["title"]

                inner = ET.tostring(root, encoding="unicode", method="xml")
                return inner.removeprefix("<root>").removesuffix("</root>").strip()
        except ET.ParseError:
            pass
        return content

    # Reference migration: <a href="...">text</a> → <reference href="...">text</reference>
    if "<a " in content:
        try:
            root = ET.fromstring(f"<root>{content}</root>")
            a_el = root.find(".//a")
            if a_el is not None:
                href = a_el.get("href", "")
                text = a_el.text or ""
                return f'<reference href="{_esc_attr(href)}">{_esc_attr(text)}</reference>'
        except ET.ParseError:
            pass
        return content

    # Fact migration: <p>text</p> or bare text → <fact>text</fact>
    text = strip_xhtml(content)
    if not text:
        text = content
    return f"<fact>{text}</fact>"


def _normalize_trust_entry(raw: Any) -> dict:
    """Normalize a truth record into canonical form.

    New behavior (XHTML simplification):
    - XHTML content is no longer self-describing (no id/trust/title attrs)
    - Metadata (id, trust, title) lives on the JSON envelope only
    - Operators use arg1/arg2 on the JSON entry instead of XHTML <child> elements
    - Authority and Provider elements no longer have did/orcid or name/state_url
    """
    item = dict(raw) if isinstance(raw, dict) else {}
    item["type"] = "truth"
    item["title"] = str(item.get("title", "Truth entry"))
    item["time"] = _coerce_timestamp(item.get("time"))
    trust_val = item.get("trust", 0.0)
    try:
        trust_val = float(trust_val)
    except (TypeError, ValueError):
        trust_val = 0.0
    item["trust"] = min(1.0, max(-1.0, trust_val))
    item["content"] = ensure_xhtml(item.get("content", ""))

    # Migrate legacy content to new XHTML spec
    # This may populate arg1/arg2 for operator entries
    item["content"] = _migrate_legacy_content(item)

    # Parse root attrs for legacy compatibility (but don't sync into envelope)
    # These attributes are now optional in XHTML and canonical on JSON only
    parsed = _parse_root_attrs(item["content"])
    if parsed:
        # Only sync if explicitly present in XHTML (legacy migration scenario)
        if parsed["id"] and not item.get("id"):
            item["id"] = parsed["id"]
        if parsed["trust"] is not None and item.get("trust") is None:
            item["trust"] = min(1.0, max(-1.0, parsed["trust"]))
        if parsed["title"] and not item.get("title"):
            item["title"] = parsed["title"]
        if parsed.get("place") and not item.get("place"):
            item["place"] = parsed["place"]
        if parsed.get("time_val") and not item.get("time_val"):
            item["time_val"] = parsed["time_val"]

    # Ensure ID exists (fallback to generated UUID)
    content = item["content"]
    if _has_operator_tag(content):
        ensure_operator_id(item)
    elif "<authority" in content:
        ensure_authority_id(item)
    else:
        ensure_trust_id(item)
    return item


# ---------------------------------------------------------------------------
# Spacetime fact classification, PII detection, and anonymization
# ---------------------------------------------------------------------------
# Placeholders and sentinel values that do NOT count as real spatiotemporal
# bindings.  Any place or time value matching one of these (case-insensitive)
# is treated as absent.
_PLACEHOLDER_VALUES = frozenset({
    "",
    "[unverified]",
    "unverified",
    "[unknown]",
    "unknown",
    "[none]",
    "none",
    "[n/a]",
    "n/a",
    "[tbd]",
    "tbd",
})


def _has_real_value(value: str | None) -> bool:
    """Return True if *value* is a non-empty, non-placeholder string."""
    if not value or not isinstance(value, str):
        return False
    return value.strip().lower() not in _PLACEHOLDER_VALUES


def is_news_fact(entry: dict) -> bool:
    """Return True if this entry is spatiotemporally bound (news).

    Checks XHTML content for <place> and <time> child elements with
    real (non-placeholder) values.
    """
    content = entry.get("content", "")
    if not isinstance(content, str) or not content.strip():
        return False
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return False
    for child in root:
        place_el = child.find("place")
        time_el = child.find("time")
        if place_el is not None and _has_real_value(place_el.text):
            return True
        if time_el is not None and _has_real_value(time_el.text):
            return True
    return False


def is_knowledge_fact(entry: dict) -> bool:
    """Return True if this is a knowledge fact (no spatiotemporal binding).

    Knowledge facts are universal/inferential — they have no specific
    place or time binding.
    """
    return not is_news_fact(entry)


def filter_knowledge_only(entries: list) -> list:
    """Return only knowledge facts from a list of truth entries.

    This is used by the server to filter what gets persisted to the truth
    corpus (news facts are session-only).
    """
    return [e for e in entries if is_knowledge_fact(e)]


# --- Basic gazetteer: top 50 world cities (case-insensitive matching) -------
_CITY_NAMES = frozenset({
    "tokyo", "delhi", "shanghai", "são paulo", "sao paulo", "mumbai",
    "beijing", "cairo", "dhaka", "mexico city", "osaka", "karachi",
    "chongqing", "istanbul", "buenos aires", "kolkata", "kinshasa",
    "lagos", "manila", "tianjin", "rio de janeiro", "guangzhou",
    "lahore", "bangalore", "moscow", "shenzhen", "chennai", "bogotá",
    "bogota", "jakarta", "lima", "bangkok", "hyderabad", "seoul",
    "nagoya", "london", "chengdu", "tehran", "ho chi minh city",
    "luanda", "new york", "los angeles", "chicago", "houston",
    "toronto", "sydney", "paris", "berlin", "madrid", "singapore",
})

# Regex patterns for PII / identity-collapse detection
_RE_USERNAME = re.compile(
    r"""(?:^|[\s(,;])               # boundary
        (?:user|usr|u/)?\w{1,3}\d{3,}  # user123, usr4567, u/name123
        (?=[\s),;:.]|$)
    """,
    re.VERBOSE | re.IGNORECASE,
)
_RE_HANDLE = re.compile(r"@[A-Za-z_]\w{1,30}")
_RE_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)
_RE_PHONE = re.compile(
    r"""(?:^|[\s(,;])
        (?:\+?\d{1,3}[\s\-.]?)?     # country code
        \(?\d{2,4}\)?[\s\-.]?        # area code
        \d{3,4}[\s\-.]?              # first group
        \d{3,4}                       # second group
        (?=[\s),;:.]|$)
    """,
    re.VERBOSE,
)
_RE_IP_ADDR = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
_RE_SPECIFIC_TIME = re.compile(
    r"""(?:
        \d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?   # 9:14 PM, 14:30:00
        |
        \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}             # ISO timestamps
    )""",
    re.VERBOSE,
)
_RE_GPS_COORDS = re.compile(
    r"""(?:
        [-+]?\d{1,3}\.\d{4,}[\s,]+[-+]?\d{1,3}\.\d{4,}   # 40.7128, -74.0060
        |
        \d{1,3}°\d{1,2}[''′]\d{0,2}[""″]?\s*[NSns]       # 40°42'N
    )""",
    re.VERBOSE,
)
_RE_STREET_ADDR = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Ct|Court|Pl|Place)\b",
    re.IGNORECASE,
)
_RE_NAMED_PERSON_TEMPORAL = re.compile(
    r"""(?:
        (?:[A-Z][a-z]+\s+){1,2}[A-Z][a-z]+         # "John David Smith"
        \s+(?:at|on|in|from|near|around)\s+          # temporal/spatial preposition
        (?:\d|[A-Z])                                  # followed by time or place
    )""",
    re.VERBOSE,
)

_IDENTITY_PATTERNS = [
    _RE_USERNAME,
    _RE_HANDLE,
    _RE_EMAIL,
    _RE_PHONE,
    _RE_IP_ADDR,
    _RE_SPECIFIC_TIME,
    _RE_GPS_COORDS,
    _RE_STREET_ADDR,
    _RE_NAMED_PERSON_TEMPORAL,
]


def detect_identifiability(content: str) -> bool:
    """Check if content contains information that identifies a particular entity.

    This is a particular case of detecting *particularity* — content
    that collapses a general proposition onto a specific identity,
    place, or time.

    Detects:
    - Usernames/handles (user123, @handle)
    - Specific times (9:14 PM, ISO timestamps)
    - Specific places (city names, GPS coords, addresses)
    - Email addresses, phone numbers, IP addresses
    - Named individuals with temporal/spatial markers

    Returns True if the content risks identity exposure.
    """
    if not isinstance(content, str) or not content.strip():
        return False

    # Strip XHTML tags for plain-text analysis
    plain = strip_xhtml(content)

    # Check regex patterns
    for pattern in _IDENTITY_PATTERNS:
        if pattern.search(plain):
            return True

    # Check city gazetteer (word-boundary aware, case-insensitive)
    plain_lower = plain.lower()
    for city in _CITY_NAMES:
        # Use word boundary matching to avoid false positives
        if re.search(r"\b" + re.escape(city) + r"\b", plain_lower):
            return True

    return False


def strip_spacetime_elements(content: str) -> str:
    """Remove <place> and <time> child elements from XHTML fact/feeling tags.

    Used when the server needs to anonymize entries before persistence.
    """
    if not isinstance(content, str) or not content.strip():
        return content
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return content

    changed = False
    for child in root:
        if child.tag in _RECOGNIZED_TAGS:
            for tag_name in ("place", "time"):
                el = child.find(tag_name)
                if el is not None:
                    # Preserve tail text (content after the child element)
                    tail = el.tail or ""
                    # Find preceding sibling or parent to attach tail text
                    siblings = list(child)
                    idx = siblings.index(el)
                    if idx > 0:
                        prev = siblings[idx - 1]
                        prev.tail = (prev.tail or "") + tail
                    else:
                        child.text = (child.text or "") + tail
                    child.remove(el)
                    changed = True

    if not changed:
        return content

    inner = ET.tostring(root, encoding="unicode", method="xml")
    return inner.removeprefix("<root>").removesuffix("</root>").strip()


# Backward-compatible alias
strip_spacetime_attrs = strip_spacetime_elements


# ---------------------------------------------------------------------------
# Provider sort key
# ---------------------------------------------------------------------------
def _provider_sort_key(entry: dict) -> tuple:
    """Sort trust entries by trust (desc), timestamp (desc), then ID."""
    trust_val = entry.get("trust", 0.0)
    ts = entry.get("time", "")
    eid = entry.get("id", "")
    return (-trust_val, _timestamp_sort_key(ts)[0] * -1, eid)


# ---------------------------------------------------------------------------
# Provider parsing
# ---------------------------------------------------------------------------
ALLOWED_DATA_DIR = Path.home() / ".wikioracle" / "keys"


def parse_provider_block(content: str) -> dict | None:
    """Parse the first <provider> XML block from trust-entry content.

    Supports both child-element style and attribute style:
      Child:  <provider><api_url>...</api_url><model>claude</model></provider>
      Attr:   <provider api_url="..." model="..." />
    Attributes take precedence only when the corresponding child element is
    absent or empty, so either style (or a mix) works.

    NOTE: The provider no longer has 'name' or 'state_url' attributes.
    'name' is implicit from the model. 'state_url' is now a nested <authority url="..."/>.
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

    # Extract authority_url from nested <authority url="..."/> child
    authority_url = ""
    auth_el = prov.find("authority")
    if auth_el is not None:
        authority_url = auth_el.get("url", "")

    prelim_raw = _val("prelim", "true").lower()
    result = {
        "api_url": _val("api_url"),
        "api_key": _val("api_key"),
        "model": _val("model"),
        "authority_url": authority_url,
        "prelim": prelim_raw not in ("false", "0", "no"),
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


def get_provider_entries(trust_entries: list) -> list:
    """Extract and rank trust entries that contain valid <provider> blocks."""
    result = []
    for entry in trust_entries:
        prov = parse_provider_block(entry.get("content", ""))
        if prov is not None:
            result.append((entry, prov))
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


# ---------------------------------------------------------------------------
# Operator parsing (<and>, <or>, <not>, <non>)
# ---------------------------------------------------------------------------
_OPERATOR_TAGS = ("and", "or", "not", "non")


def parse_operator_block(content: str, entry: dict | None = None) -> dict | None:
    """Parse the first <and>, <or>, <not>, or <non> operator block from trust-entry content.

    Returns { operator: "and"|"or"|"not"|"non", refs: [id, ...] } or None.
    - <and> and <or> require 2+ <child> elements.
    - <not> and <non> require exactly 1 <child> element.

    Operator references come from (in priority order):
    1. entry.arg1 and entry.arg2 (if entry is provided)
    2. <child id="..."/> elements in XHTML (new format)
    3. Legacy <ref>id</ref> elements in XHTML (legacy format)

    Each reference points to an existing trust entry by ID.
    """
    if not isinstance(content, str) or not _has_operator_tag(content):
        return None
    try:
        root = ET.fromstring(f"<root>{content}</root>")
    except ET.ParseError:
        return None
    for tag in _OPERATOR_TAGS:
        el = root.find(f".//{tag}")
        if el is not None:
            refs = []

            # Priority 1: arg1/arg2 from JSON entry
            if entry is not None:
                arg1 = entry.get("arg1", "")
                if isinstance(arg1, str) and arg1.strip():
                    refs.append(arg1.strip())
                arg2 = entry.get("arg2", "")
                if isinstance(arg2, str) and arg2.strip():
                    refs.append(arg2.strip())

            # Fallback to XHTML format if no args from entry
            if not refs:
                # New format: <child id="..."/>
                for child_el in el.findall("child"):
                    ref_id = (child_el.get("id") or "").strip()
                    if ref_id:
                        refs.append(ref_id)
                # Legacy fallback: <ref>id</ref>
                if not refs:
                    for ref_el in el.findall("ref"):
                        ref_id = (ref_el.text or "").strip()
                        if ref_id:
                            refs.append(ref_id)

            if tag in ("not", "non"):
                if len(refs) != 1:
                    return None
            else:
                if len(refs) < 2:
                    return None
            return {"operator": tag, "refs": refs}
    return None


def get_operator_entries(trust_entries: list) -> list:
    """Extract trust entries that contain valid operator blocks."""
    result = []
    for entry in trust_entries:
        op = parse_operator_block(entry.get("content", ""))
        if op is not None:
            result.append((entry, op))
    return result


# ---------------------------------------------------------------------------
# Authority parsing and resolution
# ---------------------------------------------------------------------------
def parse_authority_block(content: str) -> dict | None:
    """Parse the first <authority> XML block from trust-entry content.

    Supports both child-element style and attribute style:
      Child:  <authority><url>https://...</url></authority>
      Attr:   <authority url="https://..." />

    NOTE: 'did' and 'orcid' are no longer supported attributes.

    Returns { url, refresh } or None if not an authority entry.
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
_AUTHORITY_CACHE_MAX = 64  # Maximum number of cached authority URLs.
_AUTHORITY_CACHE: collections.OrderedDict = collections.OrderedDict()
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
    4. Extract truth entries (type="truth"/"trust"), skip headers/conversations/authorities
    5. Scale each entry's trust by the authority entry's trust
    6. Prefix imported entry IDs: "{authority_id}:{original_id}"

    Returns: list of (authority_entry, list_of_scaled_trust_dicts)
    """
    import time as _time

    results = []
    for entry, auth_config in authority_entries:
        url = auth_config.get("url", "")
        if not url:
            continue

        authority_trust = entry.get("trust", 0.0)
        authority_id = entry.get("id", "unknown")
        refresh = auth_config.get("refresh", 3600)

        # Check cache
        now = _time.time()
        cached = _AUTHORITY_CACHE.get(url)
        if cached and (now - cached[0]) < refresh:
            raw_entries = cached[1]
            _AUTHORITY_CACHE.move_to_end(url)  # refresh LRU position
        else:
            raw_entries = _fetch_authority_jsonl(
                url, timeout_s=timeout_s,
                allowed_data_dir=allowed_data_dir,
            )
            _AUTHORITY_CACHE[url] = (now, raw_entries)
            if len(_AUTHORITY_CACHE) > _AUTHORITY_CACHE_MAX:
                _AUTHORITY_CACHE.popitem(last=False)  # evict oldest

        # Scale trust and namespace IDs
        scaled = []
        for re_entry in raw_entries[:_AUTHORITY_MAX_ENTRIES]:
            # Skip nested authority entries (no recursive fetch)
            if "<authority" in re_entry.get("content", ""):
                continue
            remote_trust = re_entry.get("trust", 0.0)
            try:
                remote_trust = float(remote_trust)
            except (TypeError, ValueError):
                remote_trust = 0.0
            scaled_trust = authority_trust * remote_trust
            scaled_trust = min(1.0, max(-1.0, scaled_trust))

            remote_id = re_entry.get("id", "")
            namespaced_id = f"{authority_id}:{remote_id}" if remote_id else authority_id

            scaled.append({
                "type": "truth",
                "id": namespaced_id,
                "title": re_entry.get("title", "untitled"),
                "trust": scaled_trust,
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

    Returns a list of truth entry dicts (type="truth"/"trust" accepted).
    On any error, logs a warning and returns [].
    """
    import json as _json

    entries = []
    try:
        if url.startswith("file://"):
            # file:// URLs are only allowed when whitelisted in allowed_urls.
            try:
                from config import is_url_allowed
                if not is_url_allowed(url):
                    print(f"[WikiOracle] file:// authority URL not whitelisted: {url}")
                    return []
            except ImportError:
                print(f"[WikiOracle] file:// authority URLs are blocked (no config): {url}")
                return []
            import os as _os
            rel_path = url[len("file://"):]
            # Resolve relative to allowed_data_dir if provided, else cwd.
            base = allowed_data_dir or _os.getcwd()
            abs_path = _os.path.realpath(_os.path.join(base, rel_path))
            if not _os.path.isfile(abs_path):
                print(f"[WikiOracle] file:// path not found: {abs_path}")
                return []
            with open(abs_path, "r", encoding="utf-8") as fh:
                raw = fh.read(_AUTHORITY_MAX_RESPONSE_BYTES)
        elif url.startswith("https://"):
            # Validate URL against the configured whitelist
            try:
                from config import is_url_allowed
                if not is_url_allowed(url):
                    print(f"[WikiOracle] Authority URL not in allowed_urls whitelist: {url}")
                    return []
            except ImportError:
                pass  # standalone usage without config module

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
            if isinstance(rec, dict) and rec.get("type") in ("truth", "trust"):
                entries.append(rec)

    except Exception as exc:
        print(f"[WikiOracle] Authority fetch failed for {url}: {exc}")
        return []

    return entries


# ---------------------------------------------------------------------------
# Derived truth: Strong Kleene operator engine
# ---------------------------------------------------------------------------
def _eval_operator(op: dict, trust_map: dict) -> float | None:
    """Evaluate a single operator given the current trust table.

    Strong Kleene semantics on [-1, +1]:
      and(a, b, ...) = min(a, b, ...)
      or(a, b, ...)  = max(a, b, ...)
      not(a)         = -a
      non(a)         = 1 - 2|a|   (non-affirming negation)
    Returns None if any referenced ID is missing from the trust table.
    """
    refs = op["refs"]
    values = []
    for ref_id in refs:
        if ref_id not in trust_map:
            return None
        values.append(trust_map[ref_id])
    operator = op["operator"]
    if operator == "and":
        return min(values)
    elif operator == "or":
        return max(values)
    elif operator == "not":
        return -values[0]
    elif operator == "non":
        return 1.0 - 2.0 * abs(values[0])
    return None


def compute_derived_truth(trust_entries: list) -> dict:
    """Evaluate all operator entries and return a derived truth table.

    Returns: { entry_id: derived_trust } for ALL entries (including those
    unchanged), suitable for overlaying onto the trust table during RAG ranking.

    Uses Strong Kleene logic on the [-1,+1] trust scale:
      and(A, B, ...) = min(A, B, ...)
      or(A, B, ...)  = max(A, B, ...)
      not(A)         = -A

    Iterates to fixed point (operators can chain). Max 100 iterations.
    """
    # Build trust lookup from static values
    trust_map = {}
    for entry in trust_entries:
        eid = entry.get("id", "")
        if eid:
            trust_map[eid] = entry.get("trust", 0.0)

    # Extract operators and map each to its parent entry ID
    operators = []
    for entry in trust_entries:
        op = parse_operator_block(entry.get("content", ""), entry=entry)
        if op is not None:
            operators.append((entry.get("id", ""), op))

    if not operators:
        return trust_map

    # Fixed-point iteration: operator entries derive their own trust
    # from their referenced operands.
    for _ in range(100):
        changed = False
        for entry_id, op in operators:
            if not entry_id or entry_id not in trust_map:
                continue
            result = _eval_operator(op, trust_map)
            if result is None:
                continue
            result = min(1.0, max(-1.0, result))
            old = trust_map[entry_id]
            if abs(result - old) > 1e-9:
                trust_map[entry_id] = result
                changed = True

        if not changed:
            break

    return trust_map


# ---------------------------------------------------------------------------
# User GUID — deterministic pseudonymous identity from user.name
# ---------------------------------------------------------------------------
def user_guid(user_name: str, uid: str | None = None) -> str:
    """Return a user GUID, preferring an explicit *uid* from config.

    When *uid* is provided (non-empty string), it is returned as-is —
    this is the preferred path (``user.uid`` in config.xml).

    When *uid* is ``None`` or empty, falls back to a deterministic
    UUID-5 derived from *user_name* in the WikiOracle namespace.
    """
    if uid:
        return uid
    return str(uuid.uuid5(WIKIORACLE_UUID_NS, user_name))


# ---------------------------------------------------------------------------
# Server truth table — persistence and merging
# ---------------------------------------------------------------------------
# Tags that are stored in the server truth table.
# Feelings and providers are excluded — only factual content is retained.
_SERVER_TRUTH_TAGS = frozenset({"fact", "reference", "authority", "and", "or", "not", "non"})


def _is_server_storable(entry: dict) -> bool:
    """Return True if the entry should be stored in the server truth table."""
    content = entry.get("content", "")
    if "<feeling" in content:
        return False
    if "<provider" in content:
        return False
    return True


def load_server_truth(path: str | Path) -> list:
    """Load the server truth table from a JSONL file.

    Each line is a JSON truth entry.  Returns a list of normalized entries.
    If the file does not exist, returns an empty list.
    """
    path = Path(path) if not isinstance(path, Path) else path
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                entries.append(_normalize_trust_entry(raw))
            except (json.JSONDecodeError, KeyError):
                continue
    return entries


def save_server_truth(path: str | Path, entries: list) -> None:
    """Atomically write the server truth table to a JSONL file."""
    path = Path(path) if not isinstance(path, Path) else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp.replace(path)


def merge_client_truth(
    server_truth: list,
    client_truth: list,
    merge_rate: float = 0.1,
    author: str = "unknown",
) -> list:
    """Merge a client's truth entries into the server truth table.

    - Match found (by ID): nudge server trust toward client trust using
      a slow-moving average: server += merge_rate × (client − server)
    - No match: insert the entry with the client's trust and author GUID.
    - Feelings and providers are skipped.

    Returns the updated server truth list.
    """
    by_id = {e["id"]: e for e in server_truth}

    for entry in client_truth:
        if not _is_server_storable(entry):
            continue
        eid = entry.get("id", "")
        if not eid:
            continue

        if eid in by_id:
            # Existing entry: slow-moving average
            existing = by_id[eid]
            old_trust = existing.get("trust", 0.0)
            new_trust = entry.get("trust", 0.0)
            existing["trust"] = old_trust + merge_rate * (new_trust - old_trust)
            existing["trust"] = min(1.0, max(-1.0, existing["trust"]))
        else:
            # New entry: insert with author
            new_entry = _normalize_trust_entry(entry)
            new_entry["author"] = author
            server_truth.append(new_entry)
            by_id[eid] = new_entry

    return server_truth


# ---------------------------------------------------------------------------
# DegreeOfTruth — how well does the client truth match the server truth?
# ---------------------------------------------------------------------------
def compute_degree_of_truth(server_truth: list, client_truth: list) -> float:
    """Compute the DegreeOfTruth (DoT) for a client's truth table.

    Range: **-1 .. +1**

        +1  = full agreement   (client and server trust values match)
        0   = no shared context (nothing to learn — skip training)
        -1  = full disagreement (client contradicts server)

    For each entry ID shared between server and client::

        agreement_i = 1 − |server_trust_i − client_trust_i| / 2   # 0..1

    The raw mean agreement lives in [0, 1].  We rescale to [-1, +1] via
    ``dot = 2 * mean_agreement − 1`` so that *direction* is preserved.

    When no entries are shared, returns 0.0 (no information — the model
    has nothing to learn from this exchange and /train is skipped).

    Note on pluralistic truth
    -------------------------
    A DoT of 0 represents epistemic neutrality: neither confirmed nor
    refuted.  In a *consensus* truth model this is a dead zone.  In a
    future *pluralistic* model, the same fact can be true under context
    c1 and false under c2.  Moving from consensus to pluralistic truth
    will require user feedback to disambiguate context — e.g. "true for
    whom?" — so that the truth table can index entries by perspective.
    Until that is implemented, a DoT near 0 may signal that more context
    (and therefore user feedback) is needed before training should occur.
    """
    # TODO: Operator Propagation
    # Currently we compare raw trust values.  Before building server_by_id,
    # we should run compute_derived_truth(server_truth) so that logical
    # operators (and/or/not/non) propagate derived certainty into the
    # entries they govern.  The same should be done for client_truth.
    # This would let DoT reflect the *derived* agreement, not just the
    # raw stored values.  Deferred until the operator engine is stable
    # enough to run on every /chat request without measurable latency.
    server_by_id = {e["id"]: e.get("trust", 0.0) for e in server_truth}

    agreements = []
    for entry in client_truth:
        eid = entry.get("id", "")
        if eid in server_by_id:
            s_trust = server_by_id[eid]
            c_trust = entry.get("trust", 0.0)
            agreement = 1.0 - abs(s_trust - c_trust) / 2.0
            agreements.append(agreement)

    if not agreements:
        return 0.0  # no shared entries — nothing to learn

    mean_agreement = sum(agreements) / len(agreements)
    # Rescale from [0, 1] agreement to [-1, +1] DoT
    return 2.0 * mean_agreement - 1.0


# ---------------------------------------------------------------------------
# Dissonance detection (TODO) — consensus → pluralistic truth
# ---------------------------------------------------------------------------
# The truth table currently stores a single trust value per entry: a
# *consensus* model where each fact is either true (+1), false (-1), or
# somewhere in between.  This is sufficient for many use cases, but breaks
# down when the same claim is true in one context and false in another
# (e.g. "the world was created in seven days" vs. "over millions of years"
# — both can be true when indexed by the perspective they originate from).
#
# Moving from consensus to *pluralistic* truth requires:
#   1. User feedback to disambiguate context when DoT ≈ 0.  A DoT near
#      zero signals that the truth table has no opinion — the system
#      should ask "true for whom?" before committing a training step.
#   2. Context tags on entries (explicit perspective / worldview labels)
#      so that the same entry ID can carry different trust values under
#      different contexts.
#   3. A truth-space representation that is indexed by (entry_id, context)
#      rather than entry_id alone.
#
# Possible approaches:
#   - Perspective tags on entries (explicit frame membership)
#   - Truth-space embeddings with frame clustering
#   - Conditional trust values indexed by worldview vector
#
# Until this is implemented, contradictions are not detected and
# conflicting entries coexist at their stated trust values.  The DoT
# range (-1..+1) already encodes direction (agree/disagree), laying the
# groundwork for context-aware truth once user feedback is integrated.
def detect_dissonance(entries: list) -> list:
    """Placeholder: detect contradictions in the truth table.

    Returns an empty list.  See TODO above for future plans.
    """
    return []
