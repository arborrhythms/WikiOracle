# Installation


## Environment and System Preparation

### Requirements

| Requirement | Needed for | Notes |
|---|---|---|
| Git with submodule support | All workflows | Run `git submodule update --init --recursive` after cloning |
| Python 3.12 and `make` | WikiOracle install/run | The tracked Makefile creates the shim venv with `python3.12` |
| `uv` | NanoChat environment | `make install` bootstraps it when absent |
| Pandoc + XeLaTeX | PDF documentation | Required for `make WikiOracle.pdf` / `make doc` |
| LibreOffice | MOC poster PDF export | Required by `make doc` only when the PPTX is newer than the checked-in PDF or the PDF is missing |
| AWS CLI | EC2 build host | Required only for `REMOTE_PROVIDER=ec2` workflows |
| Lambda Labs API key | Lambda build host | `./.lambda-api-key`, `LAMBDA_API_KEY_FILE`, or `LAMBDA_API_KEY` |
| SSH keys | Remote build/deploy | Lambda (`LAMBDA_KEY_FILE`), EC2 (`EC2_KEY_FILE`), and WikiOracle/Lightsail (`WO_KEY_FILE`) |
| Ignored `Makefile.local` | Private LAN/tunnel hooks | Holds machine-specific `up/down/sync/tunnel` targets |

### Python dependencies

`make install` creates both virtual environments and installs all dependencies:

```bash
make install              # CPU/MPS (default)
make install ARCH=gpu     # GPU/CUDA
```

| Environment | Contents |
|---|---|
| `.venv` | WikiOracle Flask shim and dependencies from `requirements.txt` |
| `nanochat/.venv` | NanoChat runtime managed by `uv` |

### Data and tokenizer bootstrap

```bash
make build_data
make build_tokenizer
```

### Environment variables

| Variable                | Default                  | Purpose                                                  |
| ----------------------- | ------------------------ | -------------------------------------------------------- |
| `WIKIORACLE_STATE_FILE` | `state.xml`              | Path to local state file (WikiOracle State XML)          |
| `WIKIORACLE_BASE_URL`   | `http://127.0.0.1:8000`  | Upstream NanoChat-compatible base URL                    |
| `WIKIORACLE_API_PATH`   | `/chat/completions`      | Upstream chat path                                       |
| `WIKIORACLE_STATELESS`  | (unset)                  | Set truthy to disable all writes and use in-memory state |
| `WIKIORACLE_URL_PREFIX` | (unset)                  | Optional reverse-proxy path prefix                       |
| `WIKIORACLE_BIND_HOST`  | `127.0.0.1`              | Network interface to bind                                |
| `WIKIORACLE_BIND_PORT`  | `8888`                   | Server port                                              |


## The Makefile: Running and Building

All local and remote workflows are orchestrated through the Makefile.

### Top-level targets

These are the primary entry points. For a local WikiOracle + NanoChat stack, use `install`, then the `nano_*` and `wo_*` service targets. `build` is still present, but it delegates to `train`, which currently runs the BasicModel training pipeline.

| Target                 | Purpose                                                        |
| ---------------------- | -------------------------------------------------------------- |
| `make install`         | Create `.venv` (shim + NanoChat), install all deps             |
| `make build`           | Alias for `make train` (currently the BasicModel pipeline)     |
| `make nano_train`      | Full NanoChat training pipeline                                |
| `make sync HOST=local` | Optional private sync hook from `Makefile.local`               |
| `make sync HOST=remote`| Sync app + checkpoints to/from production server               |
| `make sync HOST=build` | Deploy active remote training artifacts to WikiOracle          |
| `make run HOST=local`  | Start WikiOracle Flask shim locally (foreground)               |
| `make up HOST=remote`  | Restart both services on production                            |
| `make down HOST=remote`| Stop both services                                             |
| `make all`             | Full pipeline: install + train + eval + report                 |

### Training (`train_*`)

| Target                | Purpose                                               |
| --------------------- | ----------------------------------------------------- |
| `make train HOST=local` | BasicModel training pipeline                        |
| `make train HOST=build` | Launch remote GPU instance, copy repo, start training |
| `make nano_train`     | Full NanoChat pipeline: data + tokenizer + SFT model  |
| `make train_pretrain` | Pretrain base model (`ARCH=cpu\|gpu`)                 |
| `make train_finetune` | Supervised fine-tuning (`ARCH=cpu\|gpu`)              |
| `make train_deploy HOST=build`   | Launch remote instance, train, then deploy to WikiOracle |
| `make train_retrieve HOST=build` | Pull artifacts from build instance, terminate it         |
| `make train_ssh HOST=build`      | SSH into running build instance                           |
| `make train_status HOST=build`   | Check build instance state                                |
| `make train_logs HOST=build`     | Tail training log on build instance                       |

### Test / Evaluation (`test_*`)

| Target           | Purpose                          |
| ---------------- | -------------------------------- |
| `make test HOST=local`      | Run WikiOracle + BasicModel tests          |
| `make test_all HOST=local`  | Run WikiOracle + BasicModel `test_all` target |
| `make test_unit HOST=local` | Run unit tests                             |
| `make test_basicmodel HOST=local` | Run BasicModel tests                 |
| `make test_eval HOST=local` | Evaluate model (`ARCH=cpu\|gpu`)           |

### Run / Inference (`run_*`)

| Target            | Purpose                                  |
| ----------------- | ---------------------------------------- |
| `make run HOST=local`       | Start WikiOracle local shim (foreground) |
| `make run_debug HOST=local` | Start WikiOracle local shim (debug mode) |
| `make run_init HOST=local`  | Remove state files for a fresh start     |
| `make run_cli HOST=local`   | Chat with NanoChat directly (CLI)        |
| `make run_web HOST=local`   | Run the NanoChat web extension           |

### Sync (`sync_*`)

| Target                       | Purpose                                          |
| ---------------------------- | ------------------------------------------------ |
| `make sync HOST=local`       | Optional private sync hook from `Makefile.local` |
| `make sync HOST=remote`      | Sync app + checkpoints to/from production server |
| `make sync HOST=build`       | Deploy active remote training artifacts to WikiOracle |
| `make sync_checkpoint_pull`  | Pull fine-tuning weights from production         |
| `make sync_checkpoint_push`  | Push fine-tuning weights to production            |

### Service control (`nano_*`, `wo_*`, `basicmodel_*`)

NanoChat, WikiOracle, and BasicModel support local (PID file + background process) and remote (`systemctl`) service control through `HOST=local|remote`. The `sync` target additionally accepts `HOST=build` to deploy artifacts from an active training host. Training uses `HOST=local|build`, while run/test entry points are local-only. BasicModel's OpenAI-compatible inference service runs on port 8001 by default.

Private LAN orchestration, developer-machine sync, and local service tunnel setup are intentionally excluded from the tracked Makefile. Put those workflows in an ignored `Makefile.local`; the public Makefile includes it automatically when present and otherwise emits clear stub messages for private hooks.

| Target                                           | Purpose                          |
| ------------------------------------------------ | -------------------------------- |
| `make nano_start` / `nano_stop` / `nano_restart` | Manage local or remote NanoChat  |
| `make nano_status` / `nano_logs`                 | Check NanoChat PID/service state |
| `make wo_start` / `wo_stop` / `wo_restart`       | Manage local or remote WikiOracle |
| `make wo_status` / `wo_logs`                     | Check WikiOracle PID/service state |
| `make basic_start` / `basic_stop` / `basic_restart` | Manage local or remote BasicModel |
| `make basic_status` / `basic_logs`               | Check BasicModel service/embeddings and logs |

For local debugging, the typical workflow is:

```bash
make nano_restart NANO_MODEL_TAG=d26 NANO_DEVICE_TYPE=cpu NANO_DTYPE=float32
make wo_restart
make nano_status wo_status
```

This starts an unchanged local NanoChat backend on port `8000` and the WikiOracle shim on port `8888`. `NANO_MODEL_TAG` selects the checkpoint, `NANO_DEVICE_TYPE` selects `cpu` or `cuda`, and `NANO_DTYPE` controls the runtime dtype.

### Other targets

| Target                          | Purpose                              |
| ------------------------------- | ------------------------------------ |
| `make openclaw_setup`/`run`/`test` | OpenClaw extension management     |
| `make WikiOracle.pdf`           | Rebuild the assembled WikiOracle manual only |
| `make doc`                      | Rebuild WikiOracle/BasicModel docs, the NanoChat report, and the MOC poster PDF when stale |
| `make clean` / `clean_all`      | Remove caches (and optionally venvs) |

### Key overridable variables

| Variable    | Default | Purpose                                                 |
| ----------- | ------- | ------------------------------------------------------- |
| `ARCH`      | `cpu`   | Target architecture (`cpu` or `gpu`)                    |
| `HOST`      | `local` | Target host for `up`/`down`/`nano_*`/`wo_*`             |
| `NANO_MODEL_TAG` | `d26` | NanoChat checkpoint tag used by `nano_start` / `nano_restart` |
| `NANO_SOURCE` | `sft` | NanoChat input family passed to `scripts.chat_web`      |
| `NANO_DTYPE` | `float32` | NanoChat inference dtype                              |
| `NANO_DEVICE_TYPE` | `cpu` | NanoChat device type (`cpu` or `cuda`)             |
| `NANO_PORT` | `8000`  | NanoChat server port                                    |
| `WO_BIND_HOST` | `127.0.0.1` | WikiOracle bind host                             |
| `WO_PORT`   | `8888`  | WikiOracle server port                                  |
| `NPROC`     | `1`     | GPUs per node for torchrun                              |


## Server and Client Setup

### Architecture

WikiOracle runs as a Flask server (`bin/wikioracle.py`) that proxies chat requests to NanoChat, BasicModel, OpenAI, Anthropic, Gemini, Grok, or OpenRouter. In stateful mode it owns a local state file; in stateless mode the browser/CLI supplies the complete state and runtime config on each request. The public `wikiOracle.org` deployment uses stateless mode.

### Key files

| File                | Role                                                                                                                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bin/wikioracle.py` | Flask server (binds to `127.0.0.1:8888` with self-signed TLS). Proxies chat upstream, persists state to `state.xml`. Also supports CLI merge: `python bin/wikioracle.py merge llm_*.xml` |
| `bin/config.py`     | Config loading, XML I/O, provider registry, schema-driven normalization. Auto-generates `server_id` (UUID4) on first run.                                                                |
| `bin/state.py`      | State validation, XML I/O, collision-safe merge, context-delta extraction                                                                                                                |
| `bin/response.py`   | Chat pipeline, provider coordination, voting fan-out, online training pipeline                                                                                                           |
| `bin/truth.py`      | Truth processing, authority resolution, `and/or/not/non`, DegreeOfTruth, and privacy classification                                                                                       |
| `config.xml`        | Server policy/provider definitions plus client UI, provider selection, and client API keys. Validated by `data/config.xsd`.                                                              |
| `state.xml`         | Client-owned state: header (user identity, timestamps), conversations, truth entries. Validated by `data/state.xsd`.                                                                     |
| `client/index.html` | Single-page web UI shell with chat, settings, and merge tools                                                                                                                            |
| `test/test_*.py`    | Automated tests for state, stateless contract, prompt bundles, authority, derived truth, voting, online training                                                                         |

### Quickstart

```bash
git submodule update --init --recursive
make install                   # create venvs, install all deps
make nano_restart NANO_MODEL_TAG=d26 NANO_DEVICE_TYPE=cpu NANO_DTYPE=float32
make wo_restart
make nano_status wo_status
```

Open `https://127.0.0.1:8888` in a browser and accept the self-signed certificate.

For a short CLI smoke test against the local stack:

```bash
./.venv/bin/python ./bin/wo -k --provider WikiOracle --model nanochat "Yes or no only?"
```

If you only want the WikiOracle shim in the foreground, use:

```bash
make run HOST=local
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python3 bin/wikioracle.py
```

### Configuration

The server loads `data/config.xml` as its baseline and deep-merges a project-root `config.xml` override when present. In writable mode it can generate a missing `server_id`. Main-provider API keys live under `config.client.providers`; selected environment variables are last-resort fallbacks only for matching dynamic truth-provider URLs.

User identity (name, user_id) lives in the state file, not in the config -- the client is the authority for state, and the server is the authority for config.

### Session portability

Export conversations from phone or browser as `llm_YYYY.MM.DD.HHMM.xml`, then merge into a local project's `state.xml`:

```bash
python3 bin/wikioracle.py merge llm_*.xml
```

This provides a clean integration path with Claude Code, OpenAI Codex, or any local tooling that can read the state file for project context.

### Security notes

* WikiOracle credentials are not copied onto EC2 training instances.
* Deployment excludes local/dev artifacts from rsync (`.venv`, caches, local data, `.env`, etc.).
* The local server binds to `127.0.0.1` by default -- not exposed to the network.
* TLS is enabled by default with a self-signed certificate (use `--no-ssl` to disable).
