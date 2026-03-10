# Installation


## Environment and System Preparation

### Requirements

* Python 3 and `make`.
* `uv` for NanoChat environment setup (`make build_setup` will bootstrap it if missing).
* AWS CLI configured for EC2 launch workflows (`make remote*` targets).
* SSH keys:
  * EC2 training key (`~/.ssh/nanochat-key.pem`, auto-created by remote tooling as needed).
  * Lightsail key (`./wikiOracle.pem` by default, configurable via `WO_KEY_FILE`).

### Python dependencies

The WikiOracle shim server requires only `flask` and `requests` (see `requirements.txt`). These are installed into a local `.venv`:

```bash
make build_venv
```

NanoChat (the local LLM) has its own environment under `nanochat/.venv`, managed by `uv`:

```bash
make build_setup              # CPU/MPS
make build_setup ARCH=gpu     # GPU/CUDA
```

### Data and tokenizer bootstrap

```bash
make build_data
make build_tokenizer
```

### Environment variables

| Variable                | Default                  | Purpose                                                  |
| ----------------------- | ------------------------ | -------------------------------------------------------- |
| `WIKIORACLE_STATE_FILE` | `state.xml`              | Path to local state file (WikiOracle State XML)          |
| `WIKIORACLE_BASE_URL`   | `https://wikioracle.org` | Upstream base URL                                        |
| `WIKIORACLE_API_PATH`   | `/chat/chat/completions` | Upstream chat path                                       |
| `WIKIORACLE_STATELESS`  | (unset)                  | Set truthy to disable all writes and use in-memory state |
| `WIKIORACLE_URL_PREFIX` | (unset)                  | Optional reverse-proxy path prefix                       |
| `WIKIORACLE_BIND_HOST`  | `127.0.0.1`              | Network interface to bind                                |
| `WIKIORACLE_PORT`       | `8888`                   | Server port                                              |


## The Makefile: Running and Building

All local and remote workflows are orchestrated through the Makefile. Targets are grouped by prefix.

### Build / Setup (`build_*`)

| Target                      | Purpose                                                |
| --------------------------- | ------------------------------------------------------ |
| `make build_venv`           | Create `.venv` and install shim deps (flask, requests) |
| `make build_setup`          | Install NanoChat dependencies (CPU/MPS)                |
| `make build_setup ARCH=gpu` | Install NanoChat dependencies (GPU/CUDA)               |
| `make build_data`           | Download training data shards                          |
| `make build_tokenizer`      | Train and evaluate the BPE tokenizer                   |
| `make build_preprocess`     | Preprocess corpus for sensation tags                   |

### Training (`train_*`)

| Target                | Purpose                                               |
| --------------------- | ----------------------------------------------------- |
| `make train_pretrain` | Pretrain base model (`ARCH=cpu\|gpu`)                 |
| `make train_finetune` | Supervised fine-tuning (`ARCH=cpu\|gpu`)              |
| `make train`          | Full pipeline: data + tokenizer + pretrain + finetune |

### Test / Evaluation (`test_*`)

| Target           | Purpose                          |
| ---------------- | -------------------------------- |
| `make test_unit` | Run unit tests                   |
| `make test_eval` | Evaluate model (`ARCH=cpu\|gpu`) |

### Run / Inference (`run_*`)

| Target            | Purpose                                  |
| ----------------- | ---------------------------------------- |
| `make run_server` | Start WikiOracle local shim (foreground) |
| `make run_debug`  | Start WikiOracle local shim (debug mode) |
| `make run_init`   | Remove state files for a fresh start     |
| `make run_cli`    | Chat with the model (CLI)                |
| `make run_web`    | Chat with the model (Web UI + /train)    |

### Service control (`nano_*`, `wo_*`)

Both NanoChat and WikiOracle support local (PID file) and remote (systemctl) operation, controlled by `HOST=local|remote`.

| Target                                           | Purpose                          |
| ------------------------------------------------ | -------------------------------- |
| `make nano_start` / `nano_stop` / `nano_restart` | Manage NanoChat server           |
| `make nano_status` / `nano_logs`                 | Check NanoChat server            |
| `make wo_start` / `wo_stop` / `wo_restart`       | Manage WikiOracle server         |
| `make wo_status` / `wo_logs`                     | Check WikiOracle server          |
| `make up`                                        | Deploy and restart both services |
| `make down`                                      | Stop both services               |

### Remote / Deployment (`remote_*`)

Two-machine deployment model: an EC2 GPU instance (ephemeral) for training and a Lightsail instance (`wikiOracle.org`, persistent) for hosting.

| Target                                              | Purpose                                              |
| --------------------------------------------------- | ---------------------------------------------------- |
| `make remote`                                       | Launch EC2, copy repo, start training                |
| `make remote_retrieve`                              | Pull artifacts, generate summary, terminate instance |
| `make remote_deploy_launch`                         | Launch EC2, train, deploy to WikiOracle              |
| `make remote_deploy`                                | Deploy from running EC2 to WikiOracle                |
| `make remote_ssh` / `remote_status` / `remote_logs` | Inspect remote instance                              |

### Other targets

| Target                                     | Purpose                                |
| ------------------------------------------ | -------------------------------------- |
| `make checkpoint_pull` / `checkpoint_push` | Backup and restore fine-tuning weights |
| `make doc_pdf`                             | Generate PDF from all `doc/*.md`       |
| `make doc_report`                          | Generate training report               |
| `make clean` / `clean_all`                 | Remove caches (and optionally venvs)   |

### Key overridable variables

| Variable    | Default | Purpose                                               |
| ----------- | ------- | ----------------------------------------------------- |
| `ARCH`      | `cpu`   | Target architecture (`cpu` or `gpu`)                  |
| `HOST`      | `local` | Target host for `nano_*`/`wo_*` (`local` or `remote`) |
| `NANO_PORT` | `8000`  | NanoChat server port                                  |
| `WO_PORT`   | `8888`  | WikiOracle server port                                |
| `NPROC`     | `1`     | GPUs per node for torchrun                            |


## Server and Client Setup

### Architecture

WikiOracle runs as a local Flask server (`bin/wikioracle.py`) that proxies chat requests to any LLM provider (NanoChat, OpenAI, Anthropic, Gemini, Grok) while keeping all conversation state on the local filesystem. The remote server at `wikiOracle.org` operates in stateless mode.

### Key files

| File                | Role                                                                                                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bin/wikioracle.py` | Flask server (binds to `127.0.0.1:8888` with self-signed TLS). Proxies chat upstream, persists state to `state.xml`. Also supports CLI merge: `python bin/wikioracle.py merge llm_*.xml` |
| `bin/config.py`     | Config loading, XML I/O, provider registry, schema-driven normalization. Auto-generates `server_id` (UUID4) on first run.                                                                |
| `bin/state.py`      | State validation, XML I/O, collision-safe merge, context-delta extraction                                                                                                                |
| `bin/response.py`   | Chat pipeline, provider coordination, voting fan-out, online training pipeline                                                                                                           |
| `bin/truth.py`      | Trust processing, authority resolution, operator engine (and/or/not), DegreeOfTruth, PII detection                                                                                       |
| `config.xml`        | Server configuration: provider credentials, chat settings, UI defaults, server identity. Validated by `data/config.xsd`.                                                                 |
| `state.xml`         | Client-owned state: header (user identity, timestamps), conversations, truth entries. Validated by `data/state.xsd`.                                                                     |
| `client/index.html` | Single-page web UI shell with chat, settings, and merge tools                                                                                                                            |
| `test/test_*.py`    | Automated tests for state, stateless contract, prompt bundles, authority, derived truth, voting, online training                                                                         |

### Quickstart

```bash
make build_venv                # install Python deps
make run_server                # start the local server
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 bin/wikioracle.py
```

Open `https://127.0.0.1:8888` in a browser (accept the self-signed certificate).

### Configuration

The server reads `config.xml` at startup. On first run, it auto-generates a `server_id` (UUID4) and writes it back. Provider API keys can be set in the XML or via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`).

User identity (name, user_id) lives in the state file, not in the config — the client is the authority for state, and the server is the authority for config.

### Session portability

Export conversations from phone or browser as `llm_YYYY.MM.DD.HHMM.xml`, then merge into a local project's `state.xml`:

```bash
python3 bin/wikioracle.py merge llm_*.xml
```

This provides a clean integration path with Claude Code, OpenAI Codex, or any local tooling that can read the state file for project context.

### Security notes

* WikiOracle credentials are not copied onto EC2 training instances.
* Deployment excludes local/dev artifacts from rsync (`.venv`, caches, local data, `.env`, etc.).
* The local server binds to `127.0.0.1` by default — not exposed to the network.
* TLS is enabled by default with a self-signed certificate (use `--no-ssl` to disable).
