# Installation

## Prerequisites

- Python 3 and `make`.
- `uv` for NanoChat environment setup (`make setup-cpu` / `make setup-gpu` will bootstrap it if missing).
- AWS CLI configured for EC2 launch workflows (`make remote*` targets).
- SSH keys:
  - EC2 training key (`~/.ssh/nanochat-key.pem`, auto-created by remote tooling as needed).
  - Lightsail key (`./wikiOracle.pem` by default, configurable via `WO_KEY_FILE`).

## Building

### Local CPU/MPS setup

```bash
make setup-cpu
```

### Local GPU setup

```bash
make setup-gpu
```

### Data and tokenizer bootstrap

```bash
make data
make tokenizer
```

## Deployment

Two-machine deployment model:
- EC2 GPU instance (ephemeral) for training.
- Lightsail instance (`wikiOracle.org`, persistent) for hosting.

Primary orchestration files:
- `Makefile` for local and remote workflows.
- `remote.py` for EC2 lifecycle, training orchestration, deployment, and retrieval.

NanoChat model code lives in `nanochat/`.

### Remote training/deploy flow

1. `make remote` (or `make remote-deploy-launch`) launches EC2 and starts training.
2. Training runs in detached mode and is polled to completion.
3. Deploy flow (`make remote-deploy-launch` or `make remote-deploy`) has Lightsail pull artifacts from EC2.
4. EC2 key copied to Lightsail for pull is temporary and removed after deploy.
5. EC2 instance is terminated after retrieval/deploy completion.

### Useful remote operations

- `make remote-status`, `make remote-logs`, `make remote-ssh`
- `make remote-retrieve`, `make remote-deploy`

### Security notes

- WikiOracle credentials are not copied onto EC2.
- Deployment excludes local/dev artifacts from rsync (`.venv`, caches, local data, `.env`, etc.).

## Running

```bash
make run
```

This invokes `bin/wikioracle.py` via the `WIKIORACLE_APP` Make variable (default: `bin/wikioracle.py`).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WIKIORACLE_STATE_FILE` | `llm.jsonl` | Path to local state file |
| `WIKIORACLE_BASE_URL` | `https://wikioracle.org` | Upstream base URL |
| `WIKIORACLE_API_PATH` | `/chat/chat/completions` | Upstream chat path |
| `WIKIORACLE_STATELESS` | (unset) | Set truthy to disable all writes and use in-memory state |
| `WIKIORACLE_URL_PREFIX` | (unset) | Optional reverse-proxy path prefix |

## Local Shim & Client-Owned State

WikiOracle includes a local Flask server (`bin/wikioracle.py`) that enables chatting with any LLM (NanoChat, OpenAI, Anthropic) while keeping all conversation state on your own filesystem. The remote server remains strictly stateless.

### Key components

| File | Role |
|---|---|
| `bin/wikioracle.py` | Local shim server (binds to `0.0.0.0:8888` with TLS). Proxies chat requests upstream and persists state to a single `llm.jsonl` file. Also supports CLI merge: `python bin/wikioracle.py merge llm_*.jsonl` |
| `bin/config.py` | Config dataclass, YAML loader, provider registry, schema-driven YAML writer, normalization |
| `bin/state.py` | State validation, JSONL I/O, collision-safe merge with deterministic ID suffixing, and optional context-delta extraction |
| `bin/response.py` | Chat pipeline, provider coordination, state I/O |
| `bin/truth.py` | Trust processing, authority resolution, operator engine (and/or/not) |
| `test/test_*.py` | Automated tests for state, stateless contract, prompt bundles, authority, derived truth |
| `html/index.html` | Single-page web UI shell with chat, settings, and merge tools |
| `llm.jsonl` | Client-owned state file (line-delimited JSON). See `spec/llm_state_v2.json` for the formal schema |

### Quickstart

```bash
export WIKIORACLE_STATE_FILE="/path/to/your/project/llm.jsonl"
pip install -r requirements.txt
python bin/wikioracle.py
```

### Session portability

Export conversations from phone/browser as `llm_YYYY.MM.DD.HHMM.jsonl`, then merge them into a local project's `llm.jsonl` later. This provides a clean integration path with Claude Code, OpenAI Codex, or any local tooling that can read the state file for project context.
