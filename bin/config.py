"""WikiOracle configuration.

Sections:
  - TLS certificate helpers     (_ensure_self_signed_cert)
  - Config dataclass + loader   (Config, load_config)
  - config.xml loader           (_load_config_xml, _load_config)
  - Provider registry           (_build_providers, PROVIDERS, _PROVIDER_MODELS)
  - Config schema + serializer  (CONFIG_SCHEMA, config_to_xml)
  - Config normalization         (_normalize_config)
  - Module-level mode flags     (DEBUG_MODE, STATELESS_MODE, URL_PREFIX)
  - CLI argument parsing        (parse_args)

Configuration is read from config.xml.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import uuid as _uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict
from xml.dom import minidom


# ---------------------------------------------------------------------------
# TLS certificate helpers
# ---------------------------------------------------------------------------
_DEFAULT_SSL_DIR = Path.home() / ".ssl"
_DEFAULT_HOSTNAME = __import__("socket").gethostname().split(".")[0]
_DEFAULT_CERT = _DEFAULT_SSL_DIR / f"{_DEFAULT_HOSTNAME}.pem"
_DEFAULT_KEY = _DEFAULT_SSL_DIR / f"{_DEFAULT_HOSTNAME}-key.pem"


def _ensure_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    """Generate a self-signed TLS certificate if it doesn't already exist.

    Creates ~/.ssl/ and generates a cert valid for 10 years, covering
    localhost, 127.0.0.1, ::1, the machine's .local hostname, and its
    current LAN IP.
    """
    if cert_path.exists() and key_path.exists():
        return

    cert_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect SAN entries
    san_dns = ["localhost"]
    san_ip = ["127.0.0.1", "::1"]

    # Machine hostname (e.g. ArborBook.local)
    import socket
    local_name = "localhost"
    try:
        hostname = socket.gethostname()  # e.g. "ArborBook.local"
        if hostname and hostname not in san_dns:
            san_dns.append(hostname)
        short = hostname.split(".")[0]
        local_name = f"{short}.local"
        if local_name not in san_dns:
            san_dns.append(local_name)
    except Exception:
        pass

    # Current LAN IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        lan_ip = s.getsockname()[0]
        s.close()
        if lan_ip and lan_ip not in san_ip:
            san_ip.append(lan_ip)
    except Exception:
        pass

    # Build SAN string for openssl
    san_entries = [f"DNS:{d}" for d in san_dns] + [f"IP:{ip}" for ip in san_ip]
    san_value = ",".join(san_entries)

    print(f"  Generating self-signed TLS certificate …")
    print(f"    Cert : {cert_path}")
    print(f"    Key  : {key_path}")
    print(f"    SANs : {san_value}")

    subprocess.run(
        [
            "openssl", "req",
            "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-keyout", str(key_path),
            "-out", str(cert_path),
            "-days", "3650",
            "-nodes",  # no passphrase
            "-subj", f"/CN={local_name}",
            "-addext", f"subjectAltName={san_value}",
        ],
        check=True,
        capture_output=True,
    )
    key_path.chmod(0o600)
    print(f"    ✓ Certificate created.\n")


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """Runtime configuration for the local shim process."""

    state_file: Path  # Canonical on-disk state location (ignored in stateless mode).
    base_url: str = "http://127.0.0.1:8000"  # Upstream NanoChat-compatible base URL.
    api_path: str = "/chat/completions"  # Upstream endpoint path appended to base_url.
    bind_host: str = "127.0.0.1"  # Loopback only; reverse proxy handles external traffic.
    bind_port: int = 8888  # Local port for browser/UI traffic.
    ssl_cert: Path = field(default_factory=lambda: _DEFAULT_CERT)  # TLS certificate.
    ssl_key: Path = field(default_factory=lambda: _DEFAULT_KEY)  # TLS private key.
    timeout_s: float = 120.0  # Network timeout for provider requests.
    max_state_bytes: int = 5_000_000  # Hard upper bound for serialized state size.
    max_context_chars: int = 40_000  # Context rewrite cap for merge appendix generation.
    reject_symlinks: bool = True  # Refuse symlinked state files for safer local ownership.
    auto_merge_on_start: bool = True  # Auto-import llm_*.xml/.json files at startup.
    auto_context_rewrite: bool = False  # Enable delta-based context append during merges.
    merged_suffix: str = ".merged"  # Suffix applied to files after successful import.
    allowed_origins: set = field(default_factory=lambda: {
        "https://127.0.0.1:8888", "https://localhost:8888"
    })
    api_token: str = ""  # Bearer token for endpoint auth (empty = no auth required).


def _env_bool(name: str, default: bool) -> bool:
    """Read a permissive boolean env var with a default fallback."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    """Build Config from environment variables with safe defaults."""
    state_file = Path(
        os.environ.get("WIKIORACLE_STATE_FILE", str(Path.cwd() / "state.xml"))
    ).expanduser().resolve()

    port = int(os.environ.get("WIKIORACLE_BIND_PORT", "8888"))
    allowed_origins_raw = os.environ.get(
        "WIKIORACLE_ALLOWED_ORIGINS",
        f"https://127.0.0.1:{port},https://localhost:{port}",
    )
    allowed_origins = set()
    for _origin in allowed_origins_raw.split(","):
        _origin = _origin.strip()
        if not _origin:
            continue
        if _origin == "*":
            logging.warning("WIKIORACLE_ALLOWED_ORIGINS: wildcard '*' rejected")
            continue
        if not (_origin.startswith("https://")
                or _origin.startswith("http://127.0.0.1")
                or _origin.startswith("http://localhost")):
            logging.warning("WIKIORACLE_ALLOWED_ORIGINS: non-https origin rejected: %s", _origin)
            continue
        allowed_origins.add(_origin)

    ssl_cert = Path(os.environ.get("WIKIORACLE_SSL_CERT", str(_DEFAULT_CERT))).expanduser()
    ssl_key = Path(os.environ.get("WIKIORACLE_SSL_KEY", str(_DEFAULT_KEY))).expanduser()

    return Config(
        state_file=state_file,
        base_url=os.environ.get("WIKIORACLE_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        api_path=os.environ.get("WIKIORACLE_API_PATH", "/chat/completions"),
        bind_host=os.environ.get("WIKIORACLE_BIND_HOST", "127.0.0.1"),
        bind_port=port,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        timeout_s=float(os.environ.get("WIKIORACLE_TIMEOUT_S", "120")),
        max_state_bytes=int(os.environ.get("WIKIORACLE_MAX_STATE_BYTES", str(20_000_000))),
        max_context_chars=int(os.environ.get("WIKIORACLE_MAX_CONTEXT_CHARS", "40000")),
        reject_symlinks=_env_bool("WIKIORACLE_REJECT_SYMLINKS", True),
        auto_merge_on_start=_env_bool("WIKIORACLE_AUTO_MERGE_ON_START", True),
        auto_context_rewrite=_env_bool("WIKIORACLE_AUTO_CONTEXT_REWRITE", False),
        merged_suffix=os.environ.get("WIKIORACLE_MERGED_SUFFIX", ".merged").strip() or ".merged",
        allowed_origins=allowed_origins,
        api_token=os.environ.get("WIKIORACLE_API_TOKEN", ""),
    )


# ---------------------------------------------------------------------------
# config.xml loader
# ---------------------------------------------------------------------------
_CONFIG_STATUS = ""  # human-readable load status for startup banner


def _xml_text(element: ET.Element | None) -> str:
    """Return the stripped text content of an XML element, or '' if None."""
    if element is None:
        return ""
    return (element.text or "").strip()


def _xml_coerce(text: str):
    """Coerce an XML text value to a Python bool, int, float, or str."""
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    try:
        return int(text)
    except (ValueError, TypeError):
        pass
    try:
        return float(text)
    except (ValueError, TypeError):
        pass
    return text


def _load_config_xml(xml_path: Path) -> Dict[str, Any]:
    """Parse a config.xml file into a dict.

    The XML structure uses a ``<config>`` root element with ``<server>``
    and ``<providers>`` sections. The server section contains subsections
    for ``<truthset>``, ``<evaluation>``, and ``<training>``. Provider
    entries use ``<provider name="key">`` with child elements;
    ``<display_name>`` is mapped to ``name`` in the returned dict (for
    backward compat with the rest of the codebase).

    Boolean text ``true``/``false`` is coerced to Python bools; numeric
    text is coerced to int/float.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    data: Dict[str, Any] = {}

    def _parse_flat_children(parent_el) -> Dict[str, Any]:
        """Parse an element's children as flat key→value pairs."""
        result: Dict[str, Any] = {}
        for child in parent_el:
            result[child.tag] = _xml_coerce(_xml_text(child))
        return result

    def _parse_xhtml_content(el) -> str:
        """Extract mixed content from an element as a string.

        For elements that may contain XHTML markup, serialise all
        children back to a string.  Falls back to plain text.
        """
        if el is None:
            return ""
        # If the element has child elements, serialise them
        children = list(el)
        if children:
            parts = [el.text or ""]
            for child in children:
                parts.append(ET.tostring(child, encoding="unicode", method="xml"))
            return "".join(parts).strip()
        return (el.text or "").strip()

    # --- server ---
    server_el = root.find("server")
    if server_el is not None:
        server: Dict[str, Any] = {}
        for child in server_el:
            if child.tag == "truthset":
                server["truthset"] = _parse_flat_children(child)
            elif child.tag == "evaluation":
                server["evaluation"] = _parse_flat_children(child)
            elif child.tag == "training":
                server["training"] = _parse_flat_children(child)
            elif child.tag == "allowed_urls":
                urls = [_xml_text(u) for u in child.findall("url") if _xml_text(u)]
                server["allowed_urls"] = urls
            else:
                server[child.tag] = _xml_coerce(_xml_text(child))
        data["server"] = server

    # --- providers ---
    providers_el = root.find("providers")
    if providers_el is not None:
        providers: Dict[str, Any] = {}
        # Section-level elements
        default_el = providers_el.find("default")
        if default_el is not None:
            providers["default"] = _xml_text(default_el)
        context_el = providers_el.find("context")
        if context_el is not None:
            providers["context"] = _parse_xhtml_content(context_el)
        output_el = providers_el.find("output")
        if output_el is not None:
            providers["output"] = _xml_text(output_el)
        truth_context_el = providers_el.find("truth_context")
        if truth_context_el is not None:
            providers["truth_context"] = _parse_xhtml_content(truth_context_el)
        conversation_context_el = providers_el.find("conversation_context")
        if conversation_context_el is not None:
            providers["conversation_context"] = _parse_xhtml_content(conversation_context_el)
        # Per-provider entries
        for prov_el in providers_el.findall("provider"):
            prov_key = prov_el.get("name", "")
            prov: Dict[str, Any] = {}
            for child in prov_el:
                tag = child.tag
                # <display_name> maps to "name" for backward compat
                if tag == "display_name":
                    tag = "name"
                prov[tag] = _xml_coerce(_xml_text(child))
            providers[prov_key] = prov
        data["providers"] = providers

    return data


def _load_config(project_root: Path | None = None) -> Dict[str, Any]:
    """Load configuration from config.xml.

    *project_root* defaults to the parent of the bin/ directory (i.e. the
    repo root).
    """
    global _CONFIG_STATUS
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    xml_path = project_root / "config.xml"
    if xml_path.exists():
        try:
            data = _load_config_xml(xml_path)
            if data:
                _CONFIG_STATUS = f"loaded ({len(data)} keys) from {xml_path}"
            else:
                _CONFIG_STATUS = f"empty or unparseable at {xml_path}"
            return data
        except Exception as exc:
            _CONFIG_STATUS = f"parse error: {exc}"
    else:
        _CONFIG_STATUS = f"not found at {xml_path}"
    return {}


_CONFIG: Dict[str, Any] = _load_config()



# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------
def _build_providers() -> Dict[str, Dict[str, Any]]:
    """Construct provider registry from defaults + config.xml overrides."""
    cfg_providers = _CONFIG.get("providers", {})

    providers: Dict[str, Dict[str, Any]] = {
        "wikioracle": {
            "name": "WikiOracle",
            "streaming": True,
            "sequence_len": 2048,
            "trust": 1.0,
        },
        "openai": {
            "name": "OpenAI",
            "url": "https://api.openai.com/v1/chat/completions",
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "default_model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "streaming": False,
            "trust": 0.6,
        },
        "anthropic": {
            "name": "Anthropic",
            "url": "https://api.anthropic.com/v1/messages",
            "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "default_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "streaming": False,
            "trust": 0.6,
        },
        "gemini": {
            "name": "Gemini",
            "url": "https://generativelanguage.googleapis.com/v1beta/models",
            "api_key": os.getenv("GEMINI_API_KEY", ""),
            "default_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            "streaming": False,
            "trust": 0.6,
        },
        "grok": {
            "name": "Grok",
            "url": "https://api.x.ai/v1/chat/completions",
            "api_key": os.getenv("XAI_API_KEY", ""),
            "default_model": os.getenv("XAI_MODEL", "grok-3-mini"),
            "streaming": False,
            "trust": 0.6,
        },
    }

    # Merge config.xml values (config overrides defaults; env vars still win)
    for key, ycfg in cfg_providers.items():
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
        # Config api_key fills in when no env var is set
        if ycfg.get("api_key") and not pcfg.get("api_key"):
            pcfg["api_key"] = ycfg["api_key"]
        if ycfg.get("timeout"):
            pcfg["timeout"] = ycfg["timeout"]
        if ycfg.get("sequence_len"):
            pcfg["sequence_len"] = int(ycfg["sequence_len"])
        if ycfg.get("trust") is not None:
            pcfg["trust"] = float(ycfg["trust"])

    return providers


# Default context strings for provider consultations
DEFAULT_TRUTH_CONTEXT = (
    "You are a participant in a distributed truth system. "
    "Respond with truth statements as XHTML. "
    "Use <fact> for verifiable claims and <feeling> for subjective opinions."
)
DEFAULT_CONVERSATION_CONTEXT = (
    "You are a participant in a distributed truth system. "
    "Respond with truth statements as XHTML. "
    "Use <conversation> to answer the query, <fact> for verifiable claims "
    "or citations, and <feeling> for subjective opinions."
)

# Default output format instruction for the main provider.
# Tells the LLM to structure its response with <conversation>, <fact>,
# and <feeling> tags rather than returning plain text.
DEFAULT_OUTPUT = (
    "Structure your response as XHTML with the following tags:\n"
    "- <conversation>Your main answer visible to the user.</conversation>\n"
    "- <fact trust=\"0.8\">A verifiable claim (trust -1..+1).</fact>\n"
    "- <feeling>A subjective opinion or emotional response.</feeling>\n"
    "Place each verifiable claim in its own <fact> tag with a trust attribute "
    "reflecting your confidence (-1 to +1). Use <feeling> for opinions, "
    "hedged statements, or meta-commentary. The <conversation> block is "
    "the narrative answer shown to the user."
)


PROVIDERS: Dict[str, Dict[str, Any]] = _build_providers()

# Known models per provider (for UI model selector dropdown)
# Updated March 2026
_PROVIDER_MODELS: Dict[str, list] = {
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-5-mini",
        "gpt-5.4",
        "o3",
        "o3-mini",
        "o4-mini",
    ],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5",
        "claude-opus-4-5",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
    ],
    "grok": [
        "grok-3-mini",
        "grok-3",
        "grok-4-1-fast-non-reasoning",
        "grok-4-1-fast-reasoning",
        "grok-code-fast-1",
        "grok-4.20-beta-0309-non-reasoning",
    ],
    "wikioracle": [
        "NanoChat",
        "BasicModel",
    ],
}


# ---------------------------------------------------------------------------
# Config schema + XML writer
# ---------------------------------------------------------------------------
# Ordered mapping of dotted config paths → human-readable descriptions.
# Drives field ordering and inline comments when writing config.xml.
CONFIG_SCHEMA = [
    ("server",                      "Runtime parameters (usually set via CLI flags)"),
    ("server.server_name",          "Human-readable server display name"),
    ("server.server_id",            "Persistent server identity (auto-generated UUID4)"),
    ("server.stateless",            "Stateless mode — no disk writes (set via --stateless)"),
    ("server.url_prefix",           "URL path prefix, e.g. /chat (set via --url-prefix)"),
    ("server.truthset",             "TruthSet policy settings"),
    ("server.truthset.truth_symmetry", "Enforce Truth Symmetry (see doc/Ethics.md)"),
    ("server.truthset.store_concrete", "Store concrete facts in TruthSet (see doc/Ethics.md §Entanglement Policy)"),
    ("server.truthset.truth_weight", "Truth weight factor (0.0–1.0) for provider prompts"),
    ("server.evaluation",           "Default evaluation parameters for LLM inference"),
    ("server.evaluation.temperature", "Sampling temperature (0.0–2.0)"),
    ("server.evaluation.max_tokens", "Maximum tokens in a single LLM response"),
    ("server.evaluation.timeout",   "Request timeout in seconds for LLM evaluation"),
    ("server.evaluation.url_fetch", "Allow URL fetching in responses"),
    ("server.training",             "Online learning from interactions (see doc/Training.md)"),
    ("server.training.enabled",     "Enable continuous truth corpus updates"),
    ("server.training.truth_corpus_path", "Append-only truth log"),
    ("server.training.truth_max_entries", "Max server TruthSet entries before trimming"),
    ("server.training.alpha_base",  "Base learning rate"),
    ("server.training.alpha_min",   "Minimum learning rate floor"),
    ("server.training.alpha_max",   "Maximum learning rate ceiling"),
    ("server.training.merge_rate",  "Slow-moving average rate for truth merge"),
    ("server.training.dissonance_enabled", "Detect and penalize contradictions"),
    ("server.training.device",      "Training device: auto | cpu | cuda (default: cpu)"),
    ("server.training.operators_dynamic_enabled", "Load custom operators"),
    ("server.training.warmup_steps", "Sigmoid warmup midpoint for training annealing"),
    ("server.training.grad_clip",   "Max gradient norm for clipping"),
    ("server.training.anchor_decay", "EMA blend-back rate toward checkpoint weights"),
    ("server.allowed_urls",         "URL prefixes allowed for authority/provider fetches"),
    ("providers",                   "LLM provider configuration"),
    ("providers.default",           "Provider selected on startup"),
    ("providers.context",           "Shared XHTML context for all provider system prompts"),
    ("providers.output",            "Output format instructions for all providers"),
    ("providers.truth_context",     "System prompt context for truth-only providers"),
    ("providers.conversation_context", "System prompt context for conversational providers"),
    ("providers.wikioracle.name",   "Display name for WikiOracle provider"),
    ("providers.wikioracle.username", "API login / email"),
    ("providers.openai.name",       "Display name for OpenAI provider"),
    ("providers.openai.username",   "API login / email"),
    ("providers.openai.url",        "API endpoint URL"),
    ("providers.openai.api_key",    "API key (or set OPENAI_API_KEY env var)"),
    ("providers.openai.default_model", "Default model"),
    ("providers.anthropic.name",    "Display name for Anthropic provider"),
    ("providers.anthropic.username", "API login / email"),
    ("providers.anthropic.url",     "API endpoint URL"),
    ("providers.anthropic.api_key", "API key (or set ANTHROPIC_API_KEY env var)"),
    ("providers.anthropic.default_model", "Default model"),
    ("providers.gemini.name",       "Display name for Gemini provider"),
    ("providers.gemini.username",   "API login / email"),
    ("providers.gemini.url",        "API endpoint URL"),
    ("providers.gemini.api_key",    "API key (or set GEMINI_API_KEY env var)"),
    ("providers.gemini.default_model", "Default model"),
    ("providers.grok.name",         "Display name for Grok provider"),
    ("providers.grok.username",     "API login / email"),
    ("providers.grok.url",          "API endpoint URL"),
    ("providers.grok.api_key",      "API key (or set XAI_API_KEY env var)"),
    ("providers.grok.default_model", "Default model"),
]


def _get_nested(data: dict, dotted: str):
    """Walk a dotted path into a nested dict, returning (value, found)."""
    keys = dotted.split(".")
    obj = data
    for k in keys:
        if not isinstance(obj, dict) or k not in obj:
            return None, False
        obj = obj[k]
    return obj, True


def _set_nested(data: dict, dotted: str, value) -> None:
    """Set a value at a dotted path, creating intermediate dicts as needed."""
    keys = dotted.split(".")
    obj = data
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value


def config_to_xml(data: dict) -> str:
    """Serialize a parsed config dict to pretty-printed XML with comments.

    Produces the same ``<config>`` structure that ``_load_config_xml()``
    expects.  Uses ``xml.etree.ElementTree`` for construction and
    ``xml.dom.minidom`` for pretty-printing.

    The dict key ``name`` inside each provider is written as
    ``<display_name>`` in the XML (inverse of the load-time mapping).
    """
    if not isinstance(data, dict):
        return '<?xml version="1.0" encoding="UTF-8"?>\n<config/>\n'

    # Strip runtime-only field injected by _normalize_config
    data = dict(data)
    srv = data.get("server")
    if isinstance(srv, dict):
        srv = dict(srv)
        srv.pop("providers", None)
        data["server"] = srv

    # Build a description lookup from CONFIG_SCHEMA
    desc_map: Dict[str, str] = {dotted: desc for dotted, desc in CONFIG_SCHEMA}

    root = ET.Element("config")

    def _val_str(value) -> str:
        """Convert a Python value to its XML text representation."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)

    def _add_comment(parent: ET.Element, text: str) -> None:
        """Append an XML comment to *parent*.

        Double-dashes (``--``) are illegal inside XML comments, so they
        are replaced with en-dashes to keep the output well-formed.
        """
        safe = text.replace("--", "\u2013")  # en-dash
        parent.append(ET.Comment(f" {safe} "))

    def _write_subsection(parent_el, section_name, section_data, schema_prefix):
        """Write a subsection element with its children."""
        desc = desc_map.get(schema_prefix)
        if desc:
            _add_comment(parent_el, desc)
        section_el = ET.SubElement(parent_el, section_name)
        for key, val in section_data.items():
            desc = desc_map.get(f"{schema_prefix}.{key}")
            if desc:
                _add_comment(section_el, desc)
            child = ET.SubElement(section_el, key)
            child.text = _val_str(val)

    # --- server ---
    server_data = data.get("server")
    if isinstance(server_data, dict):
        _add_comment(root, "Runtime parameters (usually set via CLI flags)")
        server_el = ET.SubElement(root, "server")
        # Flat server fields
        for key in ("server_name", "server_id", "stateless", "url_prefix"):
            val = server_data.get(key)
            if val is not None:
                desc = desc_map.get(f"server.{key}")
                if desc:
                    _add_comment(server_el, desc)
                child = ET.SubElement(server_el, key)
                child.text = _val_str(val)
        # Subsections
        truthset_data = server_data.get("truthset")
        if isinstance(truthset_data, dict):
            _write_subsection(server_el, "truthset", truthset_data, "server.truthset")
        evaluation_data = server_data.get("evaluation")
        if isinstance(evaluation_data, dict):
            _write_subsection(server_el, "evaluation", evaluation_data, "server.evaluation")
        training_data = server_data.get("training")
        if isinstance(training_data, dict):
            _write_subsection(server_el, "training", training_data, "server.training")
        # allowed_urls
        urls = server_data.get("allowed_urls")
        if isinstance(urls, list):
            _add_comment(server_el, "URL prefixes allowed for authority/provider fetches")
            urls_el = ET.SubElement(server_el, "allowed_urls")
            for url_str in urls:
                url_child = ET.SubElement(urls_el, "url")
                url_child.text = str(url_str)

    # --- providers ---
    providers_data = data.get("providers")
    if isinstance(providers_data, dict):
        _add_comment(root, "LLM provider configuration")
        providers_el = ET.SubElement(root, "providers")
        # Section-level elements
        for section_key in ("default", "context", "output", "truth_context", "conversation_context"):
            val = providers_data.get(section_key)
            if val is not None:
                desc = desc_map.get(f"providers.{section_key}")
                if desc:
                    _add_comment(providers_el, desc)
                child = ET.SubElement(providers_el, section_key)
                child.text = _val_str(val)
        # Per-provider entries
        for prov_key, prov_cfg in providers_data.items():
            if prov_key in ("default", "context", "output", "truth_context", "conversation_context"):
                continue
            if not isinstance(prov_cfg, dict):
                continue
            desc = desc_map.get(f"providers.{prov_key}.name")
            if desc:
                _add_comment(providers_el, desc)
            prov_el = ET.SubElement(providers_el, "provider")
            prov_el.set("name", prov_key)
            for field_key, field_val in prov_cfg.items():
                # "name" in dict -> <display_name> in XML
                xml_tag = "display_name" if field_key == "name" else field_key
                desc = desc_map.get(f"providers.{prov_key}.{field_key}")
                if desc:
                    _add_comment(prov_el, desc)
                child = ET.SubElement(prov_el, xml_tag)
                child.text = _val_str(field_val)

    # Pretty-print with minidom
    rough_xml = ET.tostring(root, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(rough_xml)
    pretty = dom.toprettyxml(indent="  ", encoding=None)
    # minidom adds its own <?xml …?> declaration — keep it.
    # Strip trailing whitespace from each line.
    lines = [line.rstrip() for line in pretty.splitlines()]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Allowed URL prefixes for authority/provider fetches
# ---------------------------------------------------------------------------
def _default_allowed_urls() -> list:
    """Default URL prefixes that authority and dynamic provider fetches may target.

    Only https:// URLs whose prefix matches one of these entries are allowed.
    file:// URLs are blocked unless explicitly whitelisted here.
    """
    return [
        "https://api.openai.com/",
        "https://api.anthropic.com/",
        "https://generativelanguage.googleapis.com/",
        "https://api.x.ai/",
        "https://en.wikipedia.org/",
        "http://127.0.0.1:",
        "https://127.0.0.1:",
        "http://localhost:",
        "https://localhost:",
        "file://data/",
        "file://output/",
    ]


def get_allowed_urls() -> list:
    """Return the allowed URL prefixes for authority/provider fetches.

    Checks the in-memory ``_CONFIG`` first, then falls back to
    re-reading config.xml from disk (so admin edits take effect without
    a server restart).  If neither source has ``allowed_urls``, returns
    the built-in defaults.
    """
    urls = _CONFIG.get("server", {}).get("allowed_urls")
    if not urls:
        # Re-read disk in case config.xml was edited after server start.
        fresh = _load_config()
        urls = fresh.get("server", {}).get("allowed_urls")
    if not urls:
        return _default_allowed_urls()
    # Guard against the list being parsed as a string.
    if isinstance(urls, str):
        import ast
        try:
            urls = ast.literal_eval(urls)
        except (ValueError, SyntaxError):
            return _default_allowed_urls()
    if not isinstance(urls, list):
        return _default_allowed_urls()
    return urls


def is_url_allowed(url: str) -> bool:
    """Check whether a URL is permitted by the allowed_urls whitelist.

    file:// URLs are accepted only when an explicit file:// prefix is
    present in allowed_urls.  https:// and http://127.0.0.1 (loopback)
    URLs matching a configured prefix are accepted.
    Comparisons are case-insensitive (domains are case-insensitive per RFC).
    """
    if not isinstance(url, str):
        return False
    # file:// URLs are allowed only when explicitly whitelisted.
    if url.startswith("file://"):
        allowed = get_allowed_urls()
        url_lower = url.lower()
        return any(
            prefix.lower().startswith("file://") and url_lower.startswith(prefix.lower())
            for prefix in allowed
        )
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        return False
    allowed = get_allowed_urls()
    url_lower = url.lower()
    return any(url_lower.startswith(prefix.lower()) for prefix in allowed)


# ---------------------------------------------------------------------------
# Config normalization (fill defaults)
# ---------------------------------------------------------------------------
def _normalize_config(cfg_data: dict) -> dict:
    """Ensure all expected fields exist with defaults in a config dict.

    Missing sections/keys are filled with sensible defaults.
    """
    cfg = dict(cfg_data) if isinstance(cfg_data, dict) else {}
    # --- server ---
    server = cfg.setdefault("server", {})
    if not server.get("server_id"):
        server["server_id"] = str(_uuid.uuid4())
    server.setdefault("stateless", False)
    server.setdefault("url_prefix", "")
    # server.truthset
    ts = server.setdefault("truthset", {})
    ts.setdefault("truth_symmetry", True)
    ts.setdefault("store_concrete", False)
    ts.setdefault("truth_weight", 0.7)
    # server.evaluation
    ev = server.setdefault("evaluation", {})
    ev.setdefault("temperature", 0.7)
    ev.setdefault("max_tokens", 128)
    ev.setdefault("timeout", 120)
    ev.setdefault("url_fetch", False)
    # server.training
    tr = server.setdefault("training", {})
    tr.setdefault("enabled", False)
    tr.setdefault("truth_corpus_path", "data/truth.xml")
    tr.setdefault("truth_max_entries", 1000)
    tr.setdefault("alpha_base", 0.01)
    tr.setdefault("alpha_min", 0.001)
    tr.setdefault("alpha_max", 0.1)
    tr.setdefault("merge_rate", 0.1)
    tr.setdefault("device", "cpu")
    tr.setdefault("dissonance_enabled", True)
    tr.setdefault("operators_dynamic_enabled", True)
    tr.setdefault("warmup_steps", 50)
    tr.setdefault("grad_clip", 1.0)
    tr.setdefault("anchor_decay", 0.001)
    server.setdefault("allowed_urls", _default_allowed_urls())
    # --- providers ---
    prov = cfg.setdefault("providers", {})
    prov.setdefault("default", "wikioracle")
    # Non-secret provider metadata for UI dropdowns / key-status badges
    prov_meta = {}
    for key, pcfg in PROVIDERS.items():
        prov_meta[key] = {
            "name": pcfg["name"],
            "streaming": pcfg.get("streaming", False),
            "model": pcfg.get("default_model", ""),
            "models": _PROVIDER_MODELS.get(key, []),
        }
    server["providers"] = prov_meta
    return cfg


# ---------------------------------------------------------------------------
# Module-level mode flags (set by main() at startup)
# ---------------------------------------------------------------------------
DEBUG_MODE: bool = False
STATELESS_MODE: bool = False
URL_PREFIX: str = ""


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
def reload_config(path: str | Path | None = None) -> Dict[str, Any]:
    """Reload configuration from *path* (or the default config.xml).

    Replaces the module-level ``_CONFIG`` and re-populates
    ``PROVIDERS`` so the server picks up the new file immediately.
    Returns the new config dict.
    """
    global _CONFIG
    if path is not None:
        p = Path(path)
        if p.suffix == ".xml" and p.is_file():
            _CONFIG = _load_config_xml(p)
        else:
            _CONFIG = _load_config(p.resolve().parent if p.is_file() else p.resolve())
    else:
        _CONFIG = _load_config()
    _populate_providers()
    return _CONFIG


def _populate_providers() -> None:
    """Refresh the module-level PROVIDERS dict from _CONFIG."""
    cfg_providers = _CONFIG.get("providers", {})
    PROVIDERS.clear()
    for key, prov in cfg_providers.items():
        PROVIDERS[key] = {
            "name": prov.get("name", key),
            "url": prov.get("url", ""),
            "api_key": prov.get("api_key", ""),
            "default_model": prov.get("default_model", ""),
        }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for serve/merge execution modes."""
    parser = argparse.ArgumentParser(description="WikiOracle local shim")
    parser.add_argument("--config", default=None,
                        help="Path to config.xml file (default: config.xml in project root)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--stateless", action="store_true",
                        help="Run in stateless mode (no writes to disk; editors disabled)")
    parser.add_argument("--no-ssl", action="store_true",
                        help="Serve over plain HTTP (skip TLS)")
    parser.add_argument("--url-prefix", default="",
                        help="URL path prefix (e.g. /chat) for reverse-proxy deployments")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Run Flask shim server (default)")
    merge_parser = sub.add_parser("merge", help="Merge llm_*.xml files into state")
    merge_parser.add_argument("incoming", nargs="+", help="incoming llm state files")
    return parser.parse_args()
