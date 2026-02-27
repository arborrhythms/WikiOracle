"""WikiOracle configuration: config.yaml loading, provider registry, TLS certs, CLI args."""

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
# Preferences
# ---------------------------------------------------------------------------
def _derive_prefs(cfg_yaml: dict) -> dict:
    """Derive the flat UI prefs dict from a parsed config.yaml dict."""
    ui = cfg_yaml.get("ui", {}) if isinstance(cfg_yaml, dict) else {}
    chat = cfg_yaml.get("chat", {}) if isinstance(cfg_yaml, dict) else {}
    user = cfg_yaml.get("user", {}) if isinstance(cfg_yaml, dict) else {}
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
        "splitter_pct": ui.get("splitter_pct"),
        "swipe_nav_horizontal": ui.get("swipe_nav_horizontal", True),
        "swipe_nav_vertical": ui.get("swipe_nav_vertical", False),
    }


# ---------------------------------------------------------------------------
# Module-level mode flags (set by main() at startup)
# ---------------------------------------------------------------------------
DEBUG_MODE: bool = False
STATELESS_MODE: bool = False


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
