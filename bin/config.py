"""WikiOracle configuration.

Sections:
  - TLS certificate helpers     (_ensure_self_signed_cert)
  - Config dataclass + loader   (Config, load_config)
  - config.yaml loader          (_load_config_yaml, _CONFIG_YAML)
  - Provider registry           (_build_providers, PROVIDERS, _PROVIDER_MODELS)
  - Config schema + YAML writer (CONFIG_SCHEMA, config_to_yaml)
  - Config normalization         (_normalize_config)
  - Module-level mode flags     (DEBUG_MODE, STATELESS_MODE, URL_PREFIX)
  - CLI argument parsing        (parse_args)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


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
    base_url: str = "https://wikioracle.org"  # Upstream NanoChat-compatible base URL.
    api_path: str = "/chat/completions"  # Upstream endpoint path appended to base_url.
    bind_host: str = "0.0.0.0"  # Bind all interfaces (LAN-accessible).
    bind_port: int = 8888  # Local port for browser/UI traffic.
    ssl_cert: Path = field(default_factory=lambda: _DEFAULT_CERT)  # TLS certificate.
    ssl_key: Path = field(default_factory=lambda: _DEFAULT_KEY)  # TLS private key.
    timeout_s: float = 120.0  # Network timeout for provider requests.
    max_state_bytes: int = 5_000_000  # Hard upper bound for serialized state size.
    max_context_chars: int = 40_000  # Context rewrite cap for merge appendix generation.
    reject_symlinks: bool = True  # Refuse symlinked state files for safer local ownership.
    auto_merge_on_start: bool = True  # Auto-import llm_*.jsonl/.json files at startup.
    auto_context_rewrite: bool = False  # Enable delta-based context append during merges.
    merged_suffix: str = ".merged"  # Suffix applied to files after successful import.
    allowed_origins: set = field(default_factory=lambda: {
        "https://127.0.0.1:8888", "https://localhost:8888"
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

    port = int(os.environ.get("WIKIORACLE_BIND_PORT", "8888"))
    allowed_origins_raw = os.environ.get(
        "WIKIORACLE_ALLOWED_ORIGINS",
        f"https://127.0.0.1:{port},https://localhost:{port}",
    )
    allowed_origins = {v.strip() for v in allowed_origins_raw.split(",") if v.strip()}

    ssl_cert = Path(os.environ.get("WIKIORACLE_SSL_CERT", str(_DEFAULT_CERT))).expanduser()
    ssl_key = Path(os.environ.get("WIKIORACLE_SSL_KEY", str(_DEFAULT_KEY))).expanduser()

    return Config(
        state_file=state_file,
        base_url=os.environ.get("WIKIORACLE_BASE_URL", "https://wikioracle.org").rstrip("/"),
        api_path=os.environ.get("WIKIORACLE_API_PATH", "/chat/chat/completions"),
        bind_host=os.environ.get("WIKIORACLE_BIND_HOST", "0.0.0.0"),
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
    )


# ---------------------------------------------------------------------------
# config.yaml loader
# ---------------------------------------------------------------------------
_CONFIG_YAML_STATUS = ""  # human-readable load status for startup banner


def _load_config_yaml(project_root: Path | None = None) -> Dict[str, Any]:
    """Load config.yaml from the project directory.

    *project_root* defaults to the parent of the bin/ directory (i.e. the
    repo root).
    """
    global _CONFIG_YAML_STATUS
    try:
        import yaml
    except ImportError:
        _CONFIG_YAML_STATUS = "pyyaml not installed (pip install pyyaml)"
        return {}
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    cfg_path = project_root / "config.yaml"
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


_CONFIG_YAML: Dict[str, Any] = _load_config_yaml()



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
            "default_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
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


PROVIDERS: Dict[str, Dict[str, Any]] = _build_providers()

# Known models per provider (for UI model selector dropdown)
_PROVIDER_MODELS: Dict[str, list] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
}


# ---------------------------------------------------------------------------
# Config schema + YAML writer
# ---------------------------------------------------------------------------
# Ordered mapping of dotted config paths → human-readable descriptions.
# Drives field ordering and inline comments when writing config.yaml.
CONFIG_SCHEMA = [
    ("user.name",                   "Your display name in chat messages"),
    ("providers",                   "LLM provider configuration"),
    ("providers.wikioracle.name",   "Display name for NanoChat provider"),
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
    ("chat.temperature",            "Sampling temperature (0.0–2.0)"),
    ("chat.message_window",         "Recent turns to send upstream"),
    ("chat.output_format",          'Appended as "output_format: <value>" line'),
    ("chat.rag",                    "Use truth entries for retrieval"),
    ("chat.url_fetch",              "Allow URL fetching in responses"),
    ("chat.confirm_actions",        "Prompt before deletes, merges, etc."),
    ("chat.retrieval.max_entries",  "Max RAG entries per query"),
    ("chat.retrieval.min_certainty", "|certainty| threshold (Kleene: 0 = ignorance)"),
    ("ui.default_provider",         "Provider selected on startup"),
    ("ui.layout",                   "Layout mode: flat | horizontal | vertical"),
    ("ui.theme",                    "Color theme: system | light | dark"),
    ("ui.splitter_pct",             "Tree/chat splitter position (percentage)"),
    ("ui.swipe_nav_horizontal",     "Swipe left/right to navigate siblings"),
    ("ui.swipe_nav_vertical",       "Swipe up/down to navigate siblings"),
    ("server",                      "Runtime parameters (usually set via CLI flags)"),
    ("server.stateless",            "Stateless mode — no disk writes (set via --stateless)"),
    ("server.url_prefix",           "URL path prefix, e.g. /chat (set via --url-prefix)"),
    ("ssh.wikioracle.key_file",     "Web-server deployment key"),
    ("ssh.wikioracle.user",         "SSH user"),
    ("ssh.wikioracle.host",         "SSH host"),
    ("ssh.wikioracle.dest",         "Remote destination path"),
    ("ssh.ec2.key_file",            "GPU training instance key"),
    ("ssh.ec2.user",                "SSH user"),
    ("ssh.ec2.region",              "AWS region"),
    ("ssh.ec2.key_name",            "AWS key name"),
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


def _yaml_scalar(value) -> str:
    """Format a single value as a YAML scalar string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # Quote strings that could be mis-parsed or are empty
    if not s or s in ("true", "false", "null", "yes", "no", "on", "off"):
        return f'"{s}"'
    if any(c in s for c in ":#{}[]&*?|>!%@`'\""):
        return f'"{s}"'
    return s


def config_to_yaml(data: dict) -> str:
    """Serialize a parsed config dict to YAML text with schema-driven comments.

    Walks CONFIG_SCHEMA in order, emitting `# description` comment lines
    before each key.  Unknown keys in *data* are appended at the end.
    Handles two levels of nesting (sections and sub-sections).
    """
    if not isinstance(data, dict):
        return ""

    lines: list[str] = []
    emitted: set[str] = set()  # Track dotted paths already written

    # Group schema entries by top-level section
    current_section = None

    for dotted, description in CONFIG_SCHEMA:
        parts = dotted.split(".")
        top = parts[0]
        value, found = _get_nested(data, dotted)

        # Skip entries not present in data (don't emit defaults)
        if not found:
            continue

        # Top-level section header (1-part path like "server" or "providers")
        if len(parts) == 1:
            if current_section is not None:
                lines.append("")
            current_section = top
            lines.append(f"{top}:  # {description}")
            emitted.add(top)
            continue

        # Section break
        if top != current_section:
            if current_section is not None:
                lines.append("")  # blank line between sections
            current_section = top

            # Handle top-level simple keys (e.g. "user.name" → emit "user:" header)
            if len(parts) == 2 and parts[0] not in ("providers", "ssh"):
                # Simple section: user, chat, ui
                section_data, _ = _get_nested(data, top)
                if isinstance(section_data, dict):
                    lines.append(f"{top}:")
                    emitted.add(top)

        # Emit the actual key with comment
        if len(parts) == 2:
            # e.g. user.name → "  name: User  # description"
            key = parts[1]
            lines.append(f"  {key}: {_yaml_scalar(value)}  # {description}")
            emitted.add(dotted)
        elif len(parts) == 3:
            # e.g. providers.openai.name or chat.retrieval.max_entries
            section, subsec, key = parts
            # Ensure section header exists
            if section not in emitted:
                lines.append(f"{section}:")
                emitted.add(section)
            # Ensure subsection header exists
            subsec_path = f"{section}.{subsec}"
            if subsec_path not in emitted:
                lines.append(f"  {subsec}:")
                emitted.add(subsec_path)
            lines.append(f"    {key}: {_yaml_scalar(value)}  # {description}")
            emitted.add(dotted)
        elif len(parts) == 4:
            section, sub1, sub2, key = parts
            if section not in emitted:
                lines.append(f"{section}:")
                emitted.add(section)
            sub1_path = f"{section}.{sub1}"
            if sub1_path not in emitted:
                lines.append(f"  {sub1}:")
                emitted.add(sub1_path)
            sub2_path = f"{section}.{sub1}.{sub2}"
            if sub2_path not in emitted:
                lines.append(f"    {sub2}:")
                emitted.add(sub2_path)
            lines.append(f"      {key}: {_yaml_scalar(value)}  # {description}")
            emitted.add(dotted)

    # Append any unknown top-level keys not covered by schema
    for key in data:
        if key not in emitted and key not in {p.split(".")[0] for p in emitted}:
            lines.append("")
            try:
                import yaml
                chunk = yaml.dump({key: data[key]}, default_flow_style=False, allow_unicode=True)
                lines.append(f"# (unrecognized section)")
                lines.append(chunk.rstrip())
            except ImportError:
                lines.append(f"# {key}: (yaml module not available)")
            emitted.add(key)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Config normalization (fill defaults, keep YAML shape)
# ---------------------------------------------------------------------------
def _normalize_config(cfg_yaml: dict) -> dict:
    """Ensure all expected fields exist with defaults in a config dict.

    The returned dict has the same shape as config.yaml — no flattening or
    renaming.  Missing sections/keys are filled with sensible defaults.
    """
    cfg = dict(cfg_yaml) if isinstance(cfg_yaml, dict) else {}
    cfg.setdefault("user", {}).setdefault("name", "User")
    ui = cfg.setdefault("ui", {})
    ui.setdefault("default_provider", "wikioracle")
    ui.setdefault("layout", "flat")
    ui.setdefault("theme", "system")
    ui.setdefault("swipe_nav_horizontal", True)
    ui.setdefault("swipe_nav_vertical", False)
    chat = cfg.setdefault("chat", {})
    chat.setdefault("temperature", 0.7)
    chat.setdefault("message_window", 40)
    chat.setdefault("rag", True)
    chat.setdefault("url_fetch", False)
    chat.setdefault("confirm_actions", False)
    server = cfg.setdefault("server", {})
    server.setdefault("stateless", False)
    server.setdefault("url_prefix", "")
    # Non-secret provider metadata for UI dropdowns / key-status badges
    prov_meta = {}
    for key, pcfg in PROVIDERS.items():
        needs_key = key not in ("wikioracle",)
        prov_meta[key] = {
            "name": pcfg["name"],
            "streaming": pcfg.get("streaming", False),
            "model": pcfg.get("default_model", ""),
            "models": _PROVIDER_MODELS.get(key, []),
            "has_key": bool(pcfg.get("api_key")) or not needs_key,
            "needs_key": needs_key,
        }
    server["providers"] = prov_meta
    # Factory defaults for reset buttons (context, output)
    cfg["defaults"] = {
        "context": "<div/>",
        "output": "",
    }
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
