# WikiOracle

**WikiOracle** is an open-source LLM (based on GPT or Apertus) which is truthful, capable of online learning, and which serves as a public good.

The project is motivated by a simple question:

> Can we design an LLM whose outputs are explicitly grounded in trusted sources, such that its conclusions are explainable and consistent, and whose conversations can serve as training data?

## Motivation
Right now for-profit corporations are using our data (sourced from a billion people) to train their LLMs. The world is using LLMs to train its children. This raises privacy concerns (how do we prevent malicious commercial use?), concerns about the psychological health of our children (do we want them imprinting on a prediction-engine based on arbitrary internet content?), and good opportunities (can we create a public good similar to Wikipedia?).

So to enumerate several problems with existing LLMs:
- they frequently produce ungrounded or fabricated claims,
- they are difficult to explain or audit,
- they are vulnerable to ideological or data-driven capture, especially under online learning.

## Core Idea

WikiOracle explores architectures where **truthfulness is a first-class design constraint**.

A central requirement is *explicit grounding*: 
users should be able to require that the model’s conclusions are derived *only* from a specified set of trusted sources (e.g. Wikipedia snapshots, peer-reviewed literature, curated datasets).

This approach directly supports:
- **Explainable AI (xAI):** reasoning chains and citations are inspectable.
- **Safety:** grounded models are less prone to hallucination and capture.
- **Public governance:** claims can be contested, improved, or revised openly.

## 2026 Prototype Goals

The initial goal is intentionally modest and low-cost.

We aim to extend Andrej Karpathy’s **NanoChat** (a minimal GPT-style implementation, https://github.com/karpathy/nanochat ) with:
- **Retrieval-Augmented Generation (RAG)** over trusted corpora,
- **User-specified trust sets** (configurable source whitelists),
- **Online learning**, constrained by trust and grounding requirements.
- Experiments in thought and symbolic computation that assist in grounding the truth of the outcome

Training and experimentation are feasible on rented compute (≈ $100 scale).

## Longer-Term Direction

If grounding-based truthfulness proves viable at small scale, the architecture can be evaluated and extended to larger open models (e.g. Apertus). The broader aim is to explore whether architectural commitments to truth can:
- enable honest self-explanation,
- reduce the need for ad-hoc guardrails,
- and support AI systems that function as durable public goods.

## How to Contribute

Contributions of many kinds are welcome:
- ML research and implementation
- xAI, interpretability, and safety analysis
- Epistemology, philosophy of science, and governance critique
- Documentation, evaluation, and testing

## Installing and Building

Operational details are split across `Makefile`, `remote.py`, and the docs in `doc/`.

- Two-machine deployment model:
  - EC2 GPU instance (ephemeral) for training.
  - Lightsail instance (`wikiOracle.org`, persistent) for hosting.
- Primary orchestration files:
  - `Makefile` for local and remote workflows.
  - `remote.py` for EC2 lifecycle, training orchestration, deployment, and retrieval.
- NanoChat model code lives in `nanochat/`.

Prerequisites:
- Python 3 and `make`.
- `uv` for NanoChat environment setup (`make setup-cpu` / `make setup-gpu` will bootstrap it if missing).
- AWS CLI configured for EC2 launch workflows (`make remote*` targets).
- SSH keys:
  - EC2 training key (`~/.ssh/nanochat-key.pem`, auto-created by remote tooling as needed).
  - Lightsail key (`./wikiOracle.pem` by default, configurable via `WO_KEY_FILE`).

Typical install/setup paths:
- Local CPU/MPS setup:
  - `make setup-cpu`
- Local GPU setup:
  - `make setup-gpu`
- Data and tokenizer bootstrap:
  - `make data`
  - `make tokenizer`

Remote training/deploy flow:
1. `make remote` (or `make remote-deploy-launch`) launches EC2 and starts training.
2. Training runs in detached mode and is polled to completion.
3. Deploy flow (`make remote-deploy-launch` or `make remote-deploy`) has Lightsail pull artifacts from EC2.
4. EC2 key copied to Lightsail for pull is temporary and removed after deploy.
5. EC2 instance is terminated after retrieval/deploy completion.

Useful remote operations:
- `make remote-status`, `make remote-logs`, `make remote-ssh`
- `make remote-retrieve`, `make remote-deploy`

Security notes:
- WikiOracle credentials are not copied onto EC2.
- Deployment excludes local/dev artifacts from rsync (`.venv`, caches, local data, `.env`, etc.).

## Running

Use:

`make run`

This invokes `bin/wikioracle.py` via the `WIKIORACLE_APP` Make variable (default: `bin/wikioracle.py`).

Common runtime environment variables for the local shim:
- `WIKIORACLE_STATE_FILE` (path to local state file, default: `llm.jsonl`)
- `WIKIORACLE_BASE_URL` (upstream base URL, default: `https://wikioracle.org`)
- `WIKIORACLE_API_PATH` (upstream chat path, default: `/chat/chat/completions`)
- `WIKIORACLE_STATELESS` (set truthy to disable all writes and use in-memory state)
- `WIKIORACLE_URL_PREFIX` (optional reverse-proxy path prefix)

## Local Shim & Client-Owned State

WikiOracle includes a local Flask server (`bin/wikioracle.py`) that enables chatting with any LLM (NanoChat, OpenAI, Anthropic) while keeping all conversation state on your own filesystem. The remote server remains strictly stateless.

**Key components:**

- `bin/wikioracle.py` — Local shim server (binds to `0.0.0.0:8888` with TLS). Proxies chat requests upstream and persists state to a single `llm.jsonl` file. Also supports CLI merge: `python bin/wikioracle.py merge llm_*.jsonl`
- `bin/config.py` — Config dataclass, YAML loader, provider registry, schema-driven YAML writer, normalization.
- `bin/state.py` — State validation, JSONL I/O, collision-safe merge with deterministic ID suffixing, and optional context-delta extraction.
- `bin/response.py` — Chat pipeline, provider coordination, state I/O.
- `bin/truth.py` — Trust processing, authority resolution, operator engine (and/or/not).
- `test/test_*.py` — Automated tests for state, stateless contract, prompt bundles, authority, derived truth.
- `html/index.html` — Single-page web UI shell with chat, settings, and merge tools.
- `llm.jsonl` — Client-owned state file (line-delimited JSON). See `spec/llm_state_v2.json` for the formal schema.

**Quickstart:**

```bash
export WIKIORACLE_STATE_FILE="/path/to/your/project/llm.jsonl"
pip install -r requirements.txt
python bin/wikioracle.py
```

**Session portability:** Export conversations from phone/browser as `llm_YYYY.MM.DD.HHMM.jsonl`, then merge them into a local project's `llm.jsonl` later. This provides a clean integration path with Claude Code, OpenAI Codex, or any local tooling that can read the state file for project context.
