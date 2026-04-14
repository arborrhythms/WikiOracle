"""WikiOracle configuration.

Sections:
  - TLS certificate helpers     (_ensure_self_signed_cert)
  - Config dataclass + loader   (Config, load_config)
  - config.xml loader           (_load_config_xml, _load_config)
  - Provider registry           (_build_providers, PROVIDERS, _PROVIDER_MODELS)
  - Config schema + serializer  (CONFIG_SCHEMA, config_to_xml)
  - Client-facing projection    (_client_safe_config)
  - Module-level mode flags     (DEBUG_MODE, STATELESS_MODE, URL_PREFIX)
  - CLI argument parsing        (parse_args)

Configuration is read from config.xml. There are NO defaults in code:
data/config.xml is the canonical baseline (shipped with the project) and
the optional root-level config.xml is overlaid on top via deep-merge.
"""

from __future__ import annotations

import argparse
import copy
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
# XMLConfig — dot-path wrapper for parsed XML dicts
# ---------------------------------------------------------------------------

_MISSING = object()   # sentinel for required config lookups


class XMLConfig:
    """Centralized XML configuration store with dot-path access.

    Same API as basicmodel.util.XMLConfig but without the torch
    dependency — suitable for the wikioracle server process.

    Wraps a nested dict (typically produced by ``_load_config_xml``)
    and provides ``get``/``set``/``section`` helpers.

    ``get()`` raises ``KeyError`` when the path is absent and no
    *default* is supplied — so missing configuration is surfaced
    immediately rather than propagating ``None`` through the system.
    """

    def __init__(self, data=None):
        self._data = data if data is not None else {}
        self._sources: list = []

    # --- Access ---

    def get(self, dotted_path: str, default=_MISSING):
        """Dot-path lookup: ``cfg.get('server.training.enabled')``.

        Raises ``KeyError`` when the path is absent and no *default*
        is supplied.  Pass an explicit *default* (including ``None``)
        for genuinely optional / nullable config keys.
        """
        keys = dotted_path.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                if default is _MISSING:
                    raise KeyError(
                        f"Config key not found: {dotted_path!r} "
                        f"(missing at {k!r})"
                    )
                return default
        return node

    def set(self, dotted_path: str, value) -> None:
        """Dot-path setter: ``cfg.set('server.stateless', True)``."""
        keys = dotted_path.split(".")
        node = self._data
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value

    def section(self, name: str) -> dict:
        """Return a top-level section dict.

        Raises ``KeyError`` when the section is absent.
        """
        if name not in self._data:
            raise KeyError(f"Config section not found: {name!r}")
        return self._data[name]

    @property
    def data(self) -> dict:
        """Raw dict access (backward compat with code expecting a plain dict)."""
        return self._data

    def replace(self, data: dict) -> None:
        """Replace internal data in-place (preserves dict identity for aliases)."""
        self._data.clear()
        self._data.update(data if data is not None else {})

    def __repr__(self):
        n = len(self._data)
        return f"XMLConfig({n} key{'s' if n != 1 else ''})"


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
    session_secret: str = ""  # Flask session secret (auto-generated if empty).


def _env_bool(name: str, default: bool) -> bool:
    """Read a permissive boolean env var with a default fallback."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_xml(project_root: Path, filename: str) -> Path | None:
    """Return the first existing path for *filename* in the search order.

    Search order:
      1. ``project_root / filename``       (user override)
      2. ``project_root / "data" / filename``  (shipped default)
    """
    for candidate in (project_root / filename,
                      project_root / "data" / filename):
        if candidate.exists():
            return candidate
    return None


def load_config() -> Config:
    """Build Config from environment variables with safe defaults."""
    env_state = os.environ.get("WIKIORACLE_STATE_FILE")
    if env_state:
        state_file = Path(env_state).expanduser().resolve()
    else:
        found = _find_xml(_PROJECT_ROOT, "state.xml")
        state_file = found if found else _PROJECT_ROOT / "state.xml"

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
        session_secret=os.environ.get("WIKIORACLE_SESSION_SECRET", ""),
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
    """Parse a config.xml file into the canonical config dict shape.

    The canonical shape mirrors the XML structure exactly::

        {
          "server": {
            "server_id": ...,
            "stateless": ..., "url_prefix": ...,
            "truthset":   {...},
            "evaluation": {...},
            "training":   {...},
            "allowed_urls": [...],
            "dropbox":    {...},        # only when present
            "providers":  {             # provider *definitions* (no api_keys)
              "context": "...", "output": "...",
              "truth_context": "...", "conversation_context": "...",
              "<Name>": {"type": ..., "url": ..., "model": ..., ...},
            },
          },
          "client": {
            "ui":          {...},
            "storage":     {...},
            "temperature": 0.7, "url_fetch": false, "thought_free": false,
            "providers":   {            # client-owned: default + api_keys
              "default_provider": "Gemini",
              "default_model":    "gemini-2.5-flash",
              "<Name>": {"api_key": "..."},
            },
          },
        }

    Boolean text ``true``/``false`` is coerced to Python bools; numeric
    text is coerced to int/float.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return _parse_config_root(root)


def _parse_config_root(root: ET.Element) -> Dict[str, Any]:
    """Parse a parsed ``<config>`` root element into the canonical shape."""
    data: Dict[str, Any] = {"server": {}, "client": {}}

    def _parse_flat_children(parent_el) -> Dict[str, Any]:
        return {child.tag: _xml_coerce(_xml_text(child)) for child in parent_el}

    def _parse_xhtml_content(el) -> str:
        if el is None:
            return ""
        children = list(el)
        if children:
            parts = [el.text or ""]
            for child in children:
                parts.append(ET.tostring(child, encoding="unicode", method="xml"))
            return "".join(parts).strip()
        return (el.text or "").strip()

    def _parse_server_providers(providers_el) -> Dict[str, Any]:
        """Parse <server><providers>: shared sections + per-provider definitions."""
        result: Dict[str, Any] = {}
        for tag in ("context", "output", "truth_context", "conversation_context"):
            el = providers_el.find(tag)
            if el is not None:
                if tag in ("context", "truth_context", "conversation_context"):
                    result[tag] = _parse_xhtml_content(el)
                else:
                    result[tag] = _xml_text(el)
        for prov_el in providers_el.findall("provider"):
            prov: Dict[str, Any] = {}
            prov_name = None
            for child in prov_el:
                tag = child.tag
                if tag == "name":
                    prov_name = _xml_text(child)
                    continue
                if tag == "api_key":
                    continue  # api_keys live under <client><providers>
                prov[tag] = _xml_coerce(_xml_text(child))
            if prov_name:
                result[prov_name] = prov
        return result

    def _parse_client_providers(providers_el) -> Dict[str, Any]:
        """Parse <client><providers>: default selection + api_keys."""
        result: Dict[str, Any] = {}
        for tag in ("default_provider", "default_model"):
            el = providers_el.find(tag)
            if el is not None and (el.text or "").strip():
                result[tag] = _xml_text(el)
        for prov_el in providers_el.findall("provider"):
            name_el = prov_el.find("name")
            key_el = prov_el.find("api_key")
            if name_el is None:
                continue
            name = _xml_text(name_el)
            if not name:
                continue
            entry: Dict[str, Any] = {}
            if key_el is not None and (key_el.text or "").strip():
                entry["api_key"] = _xml_text(key_el)
            if entry:
                result[name] = entry
        return result

    # --- server section ---
    server_el = root.find("server")
    server: Dict[str, Any] = {}
    if server_el is not None:
        for child in server_el:
            tag = child.tag
            if tag == "truthset":
                server["truthset"] = _parse_flat_children(child)
            elif tag == "evaluation":
                server["evaluation"] = _parse_flat_children(child)
            elif tag == "training":
                server["training"] = _parse_flat_children(child)
            elif tag == "allowed_urls":
                urls = [_xml_text(u) for u in child.findall("url") if _xml_text(u)]
                server["allowed_urls"] = urls
            elif tag == "dropbox":
                dbx: Dict[str, Any] = {}
                for attr in ("app_key", "app_secret"):
                    val = child.get(attr, "")
                    if val:
                        dbx[attr] = val
                if dbx:
                    server["dropbox"] = dbx
            elif tag == "providers":
                server["providers"] = _parse_server_providers(child)
            else:
                server[tag] = _xml_coerce(_xml_text(child))
    data["server"] = server

    # --- client section ---
    client_el = root.find("client")
    client: Dict[str, Any] = {}
    if client_el is not None:
        _pbool = lambda t: t.lower() in ("true", "1", "yes")
        for tag, conv in (("temperature", float),
                          ("url_fetch", _pbool),
                          ("thought_free", _pbool)):
            el = client_el.find(tag)
            if el is not None and (el.text or "").strip():
                client[tag] = conv(el.text.strip())
        ui_el = client_el.find("ui")
        if ui_el is not None:
            client["ui"] = _parse_flat_children(ui_el)
        storage_el = client_el.find("storage")
        if storage_el is not None:
            storage: Dict[str, Any] = {}
            for attr in ("state_key",):
                val = storage_el.get(attr, "")
                if val:
                    storage[attr] = val
            client["storage"] = storage
        prov_el = client_el.find("providers")
        if prov_el is not None:
            client["providers"] = _parse_client_providers(prov_el)
    data["client"] = client

    return data


def _load_config_xml_string(xml_text: str) -> Dict[str, Any]:
    """Parse a config XML string (same logic as ``_load_config_xml``)."""
    import tempfile
    tmp = Path(tempfile.mktemp(suffix=".xml"))
    try:
        tmp.write_text(xml_text, encoding="utf-8")
        return _load_config_xml(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into *base*.

    Dicts merge recursively; everything else (scalars, lists) is replaced
    wholesale by the override.  Returns a new deep-copied dict — neither
    input is mutated.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_config(project_root: Path | None = None) -> Dict[str, Any]:
    """Load configuration by overlaying a user override on the shipped baseline.

    The shipped ``data/config.xml`` is the source of all default values.
    A user-supplied ``config.xml`` at the project root is deep-merged on
    top (override wins on scalars and lists; dicts merge recursively).
    There are NO in-code defaults — every parameter must originate in
    one of the two XML files.
    """
    global _CONFIG_STATUS
    if project_root is None:
        project_root = _PROJECT_ROOT

    base_path = project_root / "data" / "config.xml"
    user_path = project_root / "config.xml"

    base: Dict[str, Any] = {}
    if base_path.exists():
        try:
            base = _load_config_xml(base_path)
        except Exception as exc:
            _CONFIG_STATUS = f"baseline parse error: {exc}"
            return {}

    if user_path.exists():
        try:
            override = _load_config_xml(user_path)
            merged = _deep_merge(base, override)
            _CONFIG_STATUS = f"loaded baseline + override from {user_path}"
            return merged
        except Exception as exc:
            _CONFIG_STATUS = f"override parse error: {exc} (using baseline only)"
            return base

    _CONFIG_STATUS = f"loaded baseline from {base_path}"
    return base


TheConfig: XMLConfig = XMLConfig(_load_config())
_CONFIG: Dict[str, Any] = TheConfig.data       # backward-compat alias (same dict object)

# Client settings from state.xml — populated at startup by init_settings().
TheSettings: XMLConfig = XMLConfig()


def init_settings(state_data: dict) -> None:
    """Populate ``TheSettings`` from a parsed state dict.

    Extracts the ``client`` metadata fields (version, title, ui prefs,
    client_name, etc.) from the full state dict.
    """
    settings: Dict[str, Any] = {}
    for key in ("client_name", "client_id", "user_guid",
                "version", "schema", "title"):
        if key in state_data:
            settings[key] = state_data[key]
    if "ui" in state_data:
        settings["ui"] = state_data["ui"]
    TheSettings.replace(settings)


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------
# Section keys that live alongside <provider> entries inside
# ``<server><providers>`` — they describe shared prompt context, not a
# specific provider, so they must be skipped when iterating providers.
_PROVIDER_SECTION_KEYS = ("context", "output", "truth_context", "conversation_context")


def _build_providers() -> Dict[str, Dict[str, Any]]:
    """Construct the runtime provider registry from the canonical config.

    Providers are keyed by **name** (the user-facing label).  Definitions
    come from ``server.providers`` in the loaded XML; per-provider API
    keys come from ``client.providers``.  No values are invented here:
    everything must originate in data/config.xml or the user override.
    """
    server_provs = TheConfig.get("server.providers", {}) or {}
    client_provs = TheConfig.get("client.providers", {}) or {}

    providers: Dict[str, Dict[str, Any]] = {}
    for name, definition in server_provs.items():
        if name in _PROVIDER_SECTION_KEYS or not isinstance(definition, dict):
            continue
        providers[name] = dict(definition)

    # Overlay client-owned API keys onto the matching provider definition.
    for name, entry in client_provs.items():
        if name in ("default_provider", "default_model"):
            continue
        if not isinstance(entry, dict):
            continue
        api_key = entry.get("api_key")
        if api_key and name in providers:
            providers[name]["api_key"] = api_key

    return providers


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
    "openrouter": [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "minimax/minimax-m2.5:free",
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
# Drives inline comments when writing config.xml.
CONFIG_SCHEMA = [
    ("server",                      "Runtime parameters (usually set via CLI flags)"),
    ("server.server_name",          "Human-readable server display name"),
    ("server.server_id",            "Persistent server identity (UUID4)"),
    ("server.stateless",            "Stateless mode — no disk writes (set via --stateless)"),
    ("server.url_prefix",           "URL path prefix, e.g. /chat (set via --url-prefix)"),
    ("server.truthset",             "TruthSet policy settings"),
    ("server.truthset.truth_symmetry", "Enforce Truth Symmetry (see doc/Ethics.md)"),
    ("server.truthset.store_concrete", "Store concrete facts in TruthSet"),
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
    ("server.training.device",      "Training device: auto | cpu | cuda"),
    ("server.training.operators_dynamic_enabled", "Load custom operators"),
    ("server.training.warmup_steps", "Sigmoid warmup midpoint for training annealing"),
    ("server.training.grad_clip",   "Max gradient norm for clipping"),
    ("server.training.anchor_decay", "EMA blend-back rate toward checkpoint weights"),
    ("server.allowed_urls",         "URL prefixes allowed for authority/provider fetches"),
    ("server.providers",            "LLM provider definitions"),
    ("server.providers.context",    "Shared XHTML context for all provider system prompts"),
    ("server.providers.output",     "Output format instructions for all providers"),
    ("server.providers.truth_context", "System prompt context for truth-only providers"),
    ("server.providers.conversation_context", "System prompt context for conversational providers"),
    ("client",                      "Client-facing configuration"),
    ("client.providers",            "Client provider settings (default selection + API keys)"),
    ("client.providers.default_provider", "Provider selected on startup"),
    ("client.providers.default_model", "Model selected on startup for the default provider"),
    ("client.ui",                   "UI preferences"),
]


def config_to_xml(data: dict) -> str:
    """Serialize the canonical config dict to pretty-printed XML with comments.

    Consumes the canonical ``{server: ..., client: ...}`` shape produced
    by :func:`_load_config_xml` and emits the matching XML.  Provider
    definitions are written under ``<server><providers>`` with explicit
    ``<name>`` child elements; ``default_provider`` / ``default_model``
    plus per-provider API keys are written under ``<client><providers>``.
    """
    if not isinstance(data, dict):
        return '<?xml version="1.0" encoding="UTF-8"?>\n<config/>\n'

    desc_map: Dict[str, str] = {dotted: desc for dotted, desc in CONFIG_SCHEMA}

    root = ET.Element("config")

    def _val_str(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)

    def _add_comment(parent: ET.Element, text: str) -> None:
        safe = text.replace("--", "\u2013")  # en-dash; -- is illegal in XML comments
        parent.append(ET.Comment(f" {safe} "))

    def _write_subsection(parent_el, section_name, section_data, schema_prefix):
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
    server_data = data.get("server") or {}
    _add_comment(root, "Runtime parameters (usually set via CLI flags)")
    server_el = ET.SubElement(root, "server")
    for key in ("server_name", "server_id", "stateless", "url_prefix"):
        if key in server_data:
            desc = desc_map.get(f"server.{key}")
            if desc:
                _add_comment(server_el, desc)
            child = ET.SubElement(server_el, key)
            child.text = _val_str(server_data[key])
    for sub_name, schema_prefix in (("truthset",   "server.truthset"),
                                     ("evaluation", "server.evaluation"),
                                     ("training",   "server.training")):
        sub = server_data.get(sub_name)
        if isinstance(sub, dict):
            _write_subsection(server_el, sub_name, sub, schema_prefix)
    urls = server_data.get("allowed_urls")
    if isinstance(urls, list):
        _add_comment(server_el, desc_map["server.allowed_urls"])
        urls_el = ET.SubElement(server_el, "allowed_urls")
        for url_str in urls:
            url_child = ET.SubElement(urls_el, "url")
            url_child.text = str(url_str)
    dbx_data = server_data.get("dropbox")
    if isinstance(dbx_data, dict):
        _add_comment(server_el, "Dropbox app credentials (server-only, never sent to client)")
        dbx_el = ET.SubElement(server_el, "dropbox")
        for attr in ("app_key", "app_secret"):
            if dbx_data.get(attr):
                dbx_el.set(attr, str(dbx_data[attr]))

    server_provs = server_data.get("providers")
    if isinstance(server_provs, dict):
        _add_comment(server_el, desc_map["server.providers"])
        providers_el = ET.SubElement(server_el, "providers")
        for section_key in _PROVIDER_SECTION_KEYS:
            val = server_provs.get(section_key)
            if val is not None:
                desc = desc_map.get(f"server.providers.{section_key}")
                if desc:
                    _add_comment(providers_el, desc)
                child = ET.SubElement(providers_el, section_key)
                child.text = _val_str(val)
        for prov_name, prov_cfg in server_provs.items():
            if prov_name in _PROVIDER_SECTION_KEYS:
                continue
            if not isinstance(prov_cfg, dict):
                continue
            prov_el = ET.SubElement(providers_el, "provider")
            name_el = ET.SubElement(prov_el, "name")
            name_el.text = prov_name
            if prov_cfg.get("type"):
                type_el = ET.SubElement(prov_el, "type")
                type_el.text = str(prov_cfg["type"])
            for field_key, field_val in prov_cfg.items():
                if field_key in ("name", "type"):
                    continue
                child = ET.SubElement(prov_el, field_key)
                child.text = _val_str(field_val)

    # --- client section ---
    client_data = data.get("client") or {}
    _add_comment(root, desc_map["client"])
    client_el = ET.SubElement(root, "client")

    storage_data = client_data.get("storage")
    if isinstance(storage_data, dict):
        _add_comment(client_el, "Cloud storage backend")
        ET.SubElement(client_el, "storage")

    for tag in ("temperature", "url_fetch", "thought_free"):
        if tag in client_data:
            child = ET.SubElement(client_el, tag)
            child.text = _val_str(client_data[tag])

    ui_data = client_data.get("ui")
    if isinstance(ui_data, dict):
        _add_comment(client_el, desc_map["client.ui"])
        ui_el = ET.SubElement(client_el, "ui")
        for key, val in ui_data.items():
            child = ET.SubElement(ui_el, key)
            child.text = _val_str(val)

    client_provs = client_data.get("providers")
    if isinstance(client_provs, dict):
        _add_comment(client_el, desc_map["client.providers"])
        client_prov_el = ET.SubElement(client_el, "providers")
        for sel_key in ("default_provider", "default_model"):
            if client_provs.get(sel_key):
                desc = desc_map.get(f"client.providers.{sel_key}")
                if desc:
                    _add_comment(client_prov_el, desc)
                sel_child = ET.SubElement(client_prov_el, sel_key)
                sel_child.text = _val_str(client_provs[sel_key])
        for prov_name, prov_entry in client_provs.items():
            if prov_name in ("default_provider", "default_model"):
                continue
            if not isinstance(prov_entry, dict):
                continue
            api_key = prov_entry.get("api_key")
            if not api_key:
                continue
            prov_el = ET.SubElement(client_prov_el, "provider")
            name_el = ET.SubElement(prov_el, "name")
            name_el.text = prov_name
            key_el = ET.SubElement(prov_el, "api_key")
            key_el.text = str(api_key)

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
def get_allowed_urls() -> list:
    """Return the allowed URL prefixes for authority/provider fetches.

    Reads ``server.allowed_urls`` from the canonical config.  This list
    must be defined in ``data/config.xml`` (and may be overridden in the
    user-level ``config.xml``); there is no in-code fallback.
    """
    urls = TheConfig.get("server.allowed_urls")
    if not isinstance(urls, list):
        return []
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
    allowed = get_allowed_urls()
    url_lower = url.lower()
    # file:// URLs are allowed only when explicitly whitelisted.
    if url.startswith("file://"):
        return any(
            prefix.lower().startswith("file://") and url_lower.startswith(prefix.lower())
            for prefix in allowed
        )
    if not (url.startswith("https://")
            or url.startswith("http://127.0.0.1")
            or url.startswith("http://localhost")):
        return False
    return any(url_lower.startswith(prefix.lower()) for prefix in allowed)


# ---------------------------------------------------------------------------
# Client-facing projection
# ---------------------------------------------------------------------------
def _client_safe_config(cfg_data: dict) -> dict:
    """Project the canonical config into a form safe to send to the browser.

    - Strips server-only secrets (``server.dropbox``, any
      ``server.providers[name].api_key``).
    - Augments each provider definition with a ``models`` list drawn
      from :data:`_PROVIDER_MODELS` so the UI can populate dropdowns.

    No defaults are filled in here — the caller's ``cfg_data`` is the
    sole source of values, exactly as loaded from XML.
    """
    if not isinstance(cfg_data, dict):
        return {}
    cfg = copy.deepcopy(cfg_data)

    server = cfg.get("server")
    if isinstance(server, dict):
        server.pop("dropbox", None)
        provs = server.get("providers")
        if isinstance(provs, dict):
            for name, entry in provs.items():
                if name in _PROVIDER_SECTION_KEYS or not isinstance(entry, dict):
                    continue
                entry.pop("api_key", None)
                prov_type = entry.get("type", "")
                entry["name"] = name
                entry["models"] = _PROVIDER_MODELS.get(prov_type, [])
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

    Updates ``TheConfig`` in-place and re-populates ``PROVIDERS`` so
    the server picks up the new file immediately.
    Returns the new config dict.
    """
    if path is not None:
        p = Path(path)
        if p.suffix == ".xml" and p.is_file():
            TheConfig.replace(_load_config_xml(p))
        else:
            TheConfig.replace(_load_config(p.resolve().parent if p.is_file() else p.resolve()))
    else:
        TheConfig.replace(_load_config())
    _populate_providers()
    return TheConfig.data


def _populate_providers() -> None:
    """Refresh the module-level PROVIDERS dict from TheConfig."""
    PROVIDERS.clear()
    PROVIDERS.update(_build_providers())


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
