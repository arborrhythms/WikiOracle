# WikiOracle Makefile
# Builds, trains, and runs the NanoChat submodule.
# Supports both CPU/MPS (MacBook demo) and GPU (multi-GPU training) modes.

SHELL := /bin/bash

# --- Configuration -----------------------------------------------------------

NANOCHAT_DIR     := nanochat
VENV_DIR         := $(NANOCHAT_DIR)/.venv
ACTIVATE         := source "$(CURDIR)/$(VENV_DIR)/bin/activate"
SHIM_VENV        := .venv
SHIM_ACTIVATE    := source "$(CURDIR)/$(SHIM_VENV)/bin/activate"
NANOCHAT_BASE    := $(CURDIR)/$(NANOCHAT_DIR)
IDENTITY_DATA    := $(NANOCHAT_BASE)/identity_conversations.jsonl
IDENTITY_URL     := https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl

# GPU training defaults (override on command line, e.g. make NPROC=4 pretrain-gpu)
NPROC            ?= 1               # 1 for p5.4xlarge (use 8 for p4d.24xlarge)
WANDB_RUN        ?= dummy

# CPU training defaults
CPU_DEPTH        ?= 6
CPU_ITERS        ?= 5000
CPU_BATCH        ?= 32
CPU_SEQ_LEN      ?= 512

# GPU training defaults (p5.4xlarge — 1× H100-80GB, ~$6.88/hr)
GPU_DEPTH        ?= 26
GPU_BATCH        ?= 16             # 16 for H100-80GB (use 4 for A100-40GB)
GPU_WINDOW       ?= SSSL           # SSSL for H100+ w/ FA3 (use L for A100)
# Alternative: p4d.24xlarge — 8× A100-40GB, ~$32.77/hr
# GPU_BATCH      ?= 4
# GPU_WINDOW     ?= L

# Data download shard counts
DATA_SHARDS_INIT ?= 8
DATA_SHARDS_FULL ?= 370

# --- Read SSH config from config.yaml (with fallback defaults) ----------------
# Helper: extract a value from config.yaml via Python
_yaml_val = $(shell python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')) if __import__('os').path.exists('config.yaml') else {}; print($(1))" 2>/dev/null)

# Remote EC2 configuration
EC2_INSTANCE_TYPE ?= p5.4xlarge     # 1× H100-80GB ~$6.88/hr (alt: p4d.24xlarge 8× A100 ~$32.77/hr)
EC2_REGION        ?= $(or $(call _yaml_val,c.get('ssh',{}).get('ec2',{}).get('region','')),us-west-2)
EC2_KEY_NAME      ?= $(or $(call _yaml_val,c.get('ssh',{}).get('ec2',{}).get('key_name','')),nanochat-key)
EC2_KEY_FILE      ?= $(or $(call _yaml_val,c.get('ssh',{}).get('ec2',{}).get('key_file','')),~/.ssh/$(EC2_KEY_NAME).pem)
EC2_DISK_SIZE     ?= 200
EC2_USER          ?= $(or $(call _yaml_val,c.get('ssh',{}).get('ec2',{}).get('user','')),ubuntu)
EC2_TARGET        ?=

# WikiOracle (Lightsail) deployment configuration
WO_KEY_FILE       ?= $(or $(call _yaml_val,c.get('ssh',{}).get('wikioracle',{}).get('key_file','')),./wikiOracle.pem)
WO_USER           ?= $(or $(call _yaml_val,c.get('ssh',{}).get('wikioracle',{}).get('user','')),bitnami)
WO_HOST           ?= $(or $(call _yaml_val,c.get('ssh',{}).get('wikioracle',{}).get('host','')),wikiOracle.org)
WO_DEST           ?= $(or $(call _yaml_val,c.get('ssh',{}).get('wikioracle',{}).get('dest','')),/opt/bitnami/wordpress/files/wikiOracle.org/chat)

ALERT_EMAIL ?=
WIKIORACLE_APP ?= bin/wikioracle.py

DEPLOY_ARGS := --wo-key-file=$(WO_KEY_FILE) --wo-user=$(WO_USER) \
               --wo-host=$(WO_HOST) --wo-dest=$(WO_DEST)

# --- Phony targets ------------------------------------------------------------

.PHONY: all all-gpu some some-gpu help \
        venv setup-cpu setup-gpu \
        data tokenizer \
        pretrain-cpu pretrain-gpu \
        sft-cpu sft-gpu \
        train-cpu train-gpu \
        eval-cpu eval-gpu \
        init run test run-cli run-web \
        report clean clean-all \
        remote remote-retrieve remote-ssh remote-status remote-logs \
        remote-deploy remote-deploy-launch \
        wo-start wo-stop wo-restart wo-status wo-logs \
        wo-chat-deploy wo-chat-start wo-chat-stop wo-chat-restart wo-chat-status wo-chat-logs

# --- Help ---------------------------------------------------------------------

help:
	@echo "WikiOracle / NanoChat Makefile"
	@echo ""
	@echo "  make all                Full local run: setup + train + eval + report (CPU)"
	@echo "  make all-gpu            Full local run (GPU)"
	@echo "  make some               Lightweight CPU smoke test (10 iters)"
	@echo "  make some-gpu           Lightweight GPU smoke test (10 iters)"
	@echo "  make remote             Launch EC2 p4d.24xlarge, copy code, train, auto-terminate"
	@echo ""
	@echo "Setup:"
	@echo "  make venv         Create .venv and install shim deps (flask, requests)"
	@echo "  make setup-cpu          Install NanoChat dependencies (CPU/MPS)"
	@echo "  make setup-gpu          Install dependencies (GPU/CUDA)"
	@echo ""
	@echo "Data & Tokenizer:"
	@echo "  make data               Download training data shards"
	@echo "  make tokenizer          Train and evaluate the BPE tokenizer"
	@echo ""
	@echo "Training (CPU/MPS - MacBook demo, ~30 min):"
	@echo "  make pretrain-cpu       Pretrain base model on CPU/MPS"
	@echo "  make sft-cpu            Supervised fine-tuning on CPU/MPS"
	@echo "  make train-cpu          Full pipeline: data + tok + pretrain + sft (CPU)"
	@echo ""
	@echo "Training (GPU - 1xH100-80GB on p5.4xlarge):"
	@echo "  make pretrain-gpu       Pretrain base model on GPU"
	@echo "  make sft-gpu            Supervised fine-tuning on GPU"
	@echo "  make train-gpu          Full pipeline: data + tok + pretrain + sft (GPU)"
	@echo ""
	@echo "Evaluation & Inference:"
	@echo "  make test              Run unit tests"
	@echo "  make run               Start WikiOracle local shim (bin/wikioracle.py)"
	@echo "  make eval-cpu           Evaluate model (CPU)"
	@echo "  make eval-gpu           Evaluate model (GPU)"
	@echo "  make run-cli            Chat with the model (CLI)"
	@echo "  make run-web            Chat with the model (Web UI)"
	@echo "  make report             Generate training report"
	@echo ""
	@echo "Remote (EC2):"
	@echo "  make remote             Launch EC2 instance, copy repo, start training"
	@echo "  make remote-retrieve    Pull artifacts, generate summary, terminate instance"
	@echo "  make remote-ssh         SSH into running EC2 instance"
	@echo "  make remote-status      Check EC2 instance state"
	@echo "  make remote-logs        Tail training log on remote instance"
	@echo ""
	@echo "Deploy (EC2 -> WikiOracle):"
	@echo "  make remote-deploy-launch  Launch EC2, train, deploy to WikiOracle"
	@echo "  make remote-deploy         Deploy from running EC2 to WikiOracle"
	@echo ""
	@echo "WikiOracle Server (NanoChat LLM):"
	@echo "  make wo-start              Start NanoChat server on WikiOracle"
	@echo "  make wo-stop               Stop NanoChat server on WikiOracle"
	@echo "  make wo-restart            Restart NanoChat server on WikiOracle"
	@echo "  make wo-status             Check NanoChat server status on WikiOracle"
	@echo "  make wo-logs               Tail NanoChat server logs on WikiOracle"
	@echo ""
	@echo "WikiOracle Chat Shim (served at /chat):"
	@echo "  make wo-chat-deploy        Deploy chat shim files to WikiOracle"
	@echo "  make wo-chat-start         Start chat shim on WikiOracle"
	@echo "  make wo-chat-stop          Stop chat shim on WikiOracle"
	@echo "  make wo-chat-restart       Restart chat shim on WikiOracle"
	@echo "  make wo-chat-status        Check chat shim status on WikiOracle"
	@echo "  make wo-chat-logs          Tail chat shim logs on WikiOracle"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              Remove Python caches"
	@echo "  make clean-all          Remove caches and venv"
	@echo ""
	@echo "Overridable variables (pass on command line):"
	@echo "  NPROC=8                 GPUs per node for torchrun"
	@echo "  WANDB_RUN=name          Weights & Biases run name (default: dummy)"
	@echo "  CPU_DEPTH=6             Model depth for CPU training"
	@echo "  CPU_ITERS=5000          Training iterations for CPU"
	@echo "  GPU_DEPTH=26            Model depth for GPU training"
	@echo "  DATA_SHARDS_INIT=8      Initial data shards to download"
	@echo "  DATA_SHARDS_FULL=370    Full data shards for GPU training"
	@echo "  EC2_INSTANCE_TYPE       EC2 instance type (default: p5.4xlarge)"
	@echo "  EC2_DISK_SIZE           Root EBS volume in GB (default: 200)"
	@echo "  ALERT_EMAIL             Email for idle-instance alerts (required for remote builds)"

# ---- All ----------------------------------------------------------------------

all: setup-cpu train-cpu eval-cpu report

all-gpu: setup-gpu train-gpu eval-gpu report

some:
	$(MAKE) all CPU_ITERS=10

some-gpu:
	$(MAKE) all-gpu GPU_ITERS=10 DATA_SHARDS_FULL=8 EVAL_MAX_PER_TASK=16

# --- Remote (EC2) -------------------------------------------------------------

REMOTE_ARGS := --region=$(EC2_REGION) --key-name=$(EC2_KEY_NAME) \
               --key-file=$(EC2_KEY_FILE) --user=$(EC2_USER)

remote:
ifndef ALERT_EMAIL
	$(error ALERT_EMAIL is required for remote builds — e.g. make remote ALERT_EMAIL=you@example.com)
endif
ifndef EC2_TARGET
	$(error EC2_TARGET is required for remote builds — e.g. make remote EC2_TARGET=all-gpu)
endif
	python3 remote.py $(REMOTE_ARGS) launch \
		--instance-type=$(EC2_INSTANCE_TYPE) \
		--disk-size=$(EC2_DISK_SIZE) \
		--nproc=$(NPROC) \
		--wandb-run=$(WANDB_RUN) \
		--data-shards=$(DATA_SHARDS_FULL) \
		--target="$(EC2_TARGET)" \
		--alert-email=$(ALERT_EMAIL)

remote-retrieve:
	python3 remote.py $(REMOTE_ARGS) retrieve

remote-ssh:
	python3 remote.py $(REMOTE_ARGS) ssh

remote-logs:
	python3 remote.py $(REMOTE_ARGS) logs

remote-status:
	python3 remote.py $(REMOTE_ARGS) status

remote-deploy-launch:
ifndef ALERT_EMAIL
	$(error ALERT_EMAIL is required for remote builds — e.g. make remote-deploy-launch ALERT_EMAIL=you@example.com)
endif
ifndef EC2_TARGET
	$(error EC2_TARGET is required for remote builds — e.g. make remote-deploy-launch EC2_TARGET=all-gpu)
endif
	python3 remote.py $(REMOTE_ARGS) launch \
		--instance-type=$(EC2_INSTANCE_TYPE) \
		--disk-size=$(EC2_DISK_SIZE) \
		--nproc=$(NPROC) \
		--wandb-run=$(WANDB_RUN) \
		--data-shards=$(DATA_SHARDS_FULL) \
		--target="$(EC2_TARGET)" \
		--alert-email=$(ALERT_EMAIL) \
		--deploy $(DEPLOY_ARGS)

remote-deploy:
	python3 remote.py $(REMOTE_ARGS) deploy $(DEPLOY_ARGS)

# --- WikiOracle Server (NanoChat LLM) -----------------------------------------

WO_SSH := ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10 $(WO_USER)@$(WO_HOST)

wo-start:
	$(WO_SSH) "sudo systemctl start nanochat"
	@echo "NanoChat server started on $(WO_HOST)"

wo-stop:
	$(WO_SSH) "sudo systemctl stop nanochat"
	@echo "NanoChat server stopped on $(WO_HOST)"

wo-restart:
	$(WO_SSH) "sudo systemctl restart nanochat"
	@echo "NanoChat server restarted on $(WO_HOST)"

wo-status:
	$(WO_SSH) "sudo systemctl status nanochat --no-pager -l"

wo-logs:
	$(WO_SSH) "sudo journalctl -u nanochat -f --no-pager"

# --- WikiOracle Chat Shim (served at /chat on WikiOracle.org) ----------------
# The chat shim runs as a stateless Flask app behind the WordPress reverse proxy.
# It listens on 127.0.0.1:8787 and serves from /chat URL prefix.

WO_CHAT_DEST     := $(WO_DEST)
WO_CHAT_FILES    := WikiOracle.py config.yaml requirements.txt html bin spec

.PHONY: wo-chat-deploy wo-chat-start wo-chat-stop wo-chat-restart wo-chat-status wo-chat-logs

wo-chat-deploy:
	@echo "Deploying WikiOracle chat shim to $(WO_HOST):$(WO_CHAT_DEST) ..."
	rsync -avz --delete --exclude .venv \
		-e "ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10" \
		$(WO_CHAT_FILES) \
		$(WO_USER)@$(WO_HOST):$(WO_CHAT_DEST)/
	@echo "Chat shim deployed. Run 'make wo-chat-restart' to apply."

wo-chat-start:
	$(WO_SSH) "sudo systemctl start wikioracle-chat"
	@echo "WikiOracle chat shim started on $(WO_HOST)"

wo-chat-stop:
	$(WO_SSH) "sudo systemctl stop wikioracle-chat"
	@echo "WikiOracle chat shim stopped on $(WO_HOST)"

wo-chat-restart:
	$(WO_SSH) "sudo systemctl restart wikioracle-chat"
	@echo "WikiOracle chat shim restarted on $(WO_HOST)"

wo-chat-status:
	$(WO_SSH) "sudo systemctl status wikioracle-chat --no-pager -l"

wo-chat-logs:
	$(WO_SSH) "sudo journalctl -u wikioracle-chat -f --no-pager"

# --- Setup --------------------------------------------------------------------

$(VENV_DIR):
	command -v uv &> /dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$$HOME/.local/bin:$$PATH"; }
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv venv

venv:
	python3 -m venv $(SHIM_VENV)
	$(SHIM_ACTIVATE) && pip install -r requirements.txt

setup-cpu: $(VENV_DIR)
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv sync --extra cpu

setup-gpu: $(VENV_DIR)
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv sync --extra gpu

# --- Data ---------------------------------------------------------------------

data:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m nanochat.dataset -n $(DATA_SHARDS_INIT)

# --- Tokenizer ----------------------------------------------------------------

tokenizer: data
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.tok_train && \
		python -m scripts.tok_eval

# --- Identity conversations (SFT data) ---------------------------------------

$(IDENTITY_DATA):
	curl -L -o "$(IDENTITY_DATA)" $(IDENTITY_URL)

# --- Pretrain -----------------------------------------------------------------

pretrain-cpu: tokenizer
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.base_train \
			--depth=$(CPU_DEPTH) \
			--head-dim=64 \
			--window-pattern=$(GPU_WINDOW) \
			--max-seq-len=$(CPU_SEQ_LEN) \
			--device-batch-size=$(CPU_BATCH) \
			--num-iterations=$(CPU_ITERS) \
			--run=$(WANDB_RUN)

pretrain-gpu: tokenizer
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		export OMP_NUM_THREADS=1 && \
		python -m nanochat.dataset -n $(DATA_SHARDS_FULL) && \
		torchrun --standalone --nproc_per_node=$(NPROC) \
			-m scripts.base_train -- \
			--depth=$(GPU_DEPTH) \
			--target-param-data-ratio=8.25 \
			--device-batch-size=$(GPU_BATCH) \
			--window-pattern=$(GPU_WINDOW) \
			$(if $(GPU_ITERS),--num-iterations=$(GPU_ITERS)) \
			--run=$(WANDB_RUN)

# --- SFT (Supervised Fine-Tuning) --------------------------------------------

sft-cpu: $(IDENTITY_DATA)
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.chat_sft \
			--max-seq-len=$(CPU_SEQ_LEN) \
			--device-batch-size=$(CPU_BATCH) \
			--num-iterations=1500 \
			--run=$(WANDB_RUN)

sft-gpu: $(IDENTITY_DATA)
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		export OMP_NUM_THREADS=1 && \
		torchrun --standalone --nproc_per_node=$(NPROC) \
			-m scripts.chat_sft -- \
			--device-batch-size=$(GPU_BATCH) \
			$(if $(GPU_ITERS),--num-iterations=$(GPU_ITERS)) \
			--run=$(WANDB_RUN)

# --- Full training pipelines --------------------------------------------------

train-cpu: data tokenizer pretrain-cpu sft-cpu
	@echo "CPU training pipeline complete."

train-gpu: data tokenizer pretrain-gpu sft-gpu
	@echo "GPU training pipeline complete."

# --- Evaluation ---------------------------------------------------------------

eval-cpu:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.base_eval \
			--device-batch-size=1 \
			--split-tokens=16384 \
			--max-per-task=16 && \
		python -m scripts.chat_eval -i sft

eval-gpu:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		export OMP_NUM_THREADS=1 && \
		torchrun --standalone --nproc_per_node=$(NPROC) \
			-m scripts.base_eval -- \
			--device-batch-size=$(GPU_BATCH) \
			$(if $(EVAL_MAX_PER_TASK),--max-per-task=$(EVAL_MAX_PER_TASK)) && \
		torchrun --standalone --nproc_per_node=$(NPROC) \
			-m scripts.chat_eval -- -i sft \
			$(if $(EVAL_MAX_PER_TASK),-x $(EVAL_MAX_PER_TASK))

# --- Inference ----------------------------------------------------------------

init:
	rm -f llm.jsonl
	@echo "llm.jsonl removed — server will create a fresh one on next start."

run:
	$(SHIM_ACTIVATE) && python3 $(WIKIORACLE_APP)

debug:
	$(SHIM_ACTIVATE) && python3 $(WIKIORACLE_APP) --debug

test:
	$(SHIM_ACTIVATE) && python3 -m unittest test.test_wikioracle_state test.test_prompt_bundle -v

run-cli:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.chat_cli

run-web:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.chat_web

# --- Report -------------------------------------------------------------------

report:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m nanochat.report generate

# --- Cleanup ------------------------------------------------------------------

clean:
	find $(NANOCHAT_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(NANOCHAT_DIR) -name '*.pyc' -delete 2>/dev/null || true

clean-all: clean
	rm -rf $(VENV_DIR)
