# WikiOracle Makefile
# Builds, trains, and runs the NanoChat submodule.
# Supports both CPU/MPS (MacBook demo) and GPU (multi-GPU training) modes.

SHELL := /bin/bash

# --- Configuration -----------------------------------------------------------

NANOCHAT_DIR     := nanochat
VENV_DIR         := $(NANOCHAT_DIR)/.venv
ACTIVATE         := source "$(CURDIR)/$(VENV_DIR)/bin/activate"
NANOCHAT_BASE    := $(CURDIR)/$(NANOCHAT_DIR)
IDENTITY_DATA    := $(NANOCHAT_BASE)/identity_conversations.jsonl
IDENTITY_URL     := https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl

# GPU training defaults (override on command line, e.g. make NPROC=4 pretrain-gpu)
NPROC            ?= 8
WANDB_RUN        ?= dummy

# CPU training defaults
CPU_DEPTH        ?= 6
CPU_ITERS        ?= 5000
CPU_BATCH        ?= 32
CPU_SEQ_LEN      ?= 512

# GPU training defaults
GPU_DEPTH        ?= 26
GPU_BATCH        ?= 4              # 4 for A100-40GB, 16 for H100-80GB

# Data download shard counts
DATA_SHARDS_INIT ?= 8
DATA_SHARDS_FULL ?= 370

# Remote EC2 configuration
EC2_INSTANCE_TYPE ?= p4d.24xlarge
EC2_REGION        ?= us-west-2
EC2_KEY_NAME      ?= nanochat-key
EC2_KEY_FILE      ?= ~/.ssh/$(EC2_KEY_NAME).pem
EC2_DISK_SIZE     ?= 200
EC2_USER          ?= ubuntu
EC2_TARGET        ?= all-gpu

# --- Phony targets ------------------------------------------------------------

.PHONY: all all-gpu some some-gpu help \
        setup-cpu setup-gpu \
        data tokenizer \
        pretrain-cpu pretrain-gpu \
        sft-cpu sft-gpu \
        train-cpu train-gpu \
        eval-cpu eval-gpu \
        run-cli run-web \
        report clean clean-all \
        remote remote-retrieve remote-ssh remote-status remote-logs

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
	@echo "  make setup-cpu          Install dependencies (CPU/MPS)"
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
	@echo "Training (GPU - 8xH100, ~3 hours):"
	@echo "  make pretrain-gpu       Pretrain base model on GPU"
	@echo "  make sft-gpu            Supervised fine-tuning on GPU"
	@echo "  make train-gpu          Full pipeline: data + tok + pretrain + sft (GPU)"
	@echo ""
	@echo "Evaluation & Inference:"
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
	@echo "  EC2_INSTANCE_TYPE       EC2 instance type (default: p4d.24xlarge)"
	@echo "  EC2_DISK_SIZE           Root EBS volume in GB (default: 200)"

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
	python3 remote.py $(REMOTE_ARGS) launch \
		--instance-type=$(EC2_INSTANCE_TYPE) \
		--disk-size=$(EC2_DISK_SIZE) \
		--nproc=$(NPROC) \
		--wandb-run=$(WANDB_RUN) \
		--data-shards=$(DATA_SHARDS_FULL) \
		--target="$(EC2_TARGET)"

remote-retrieve:
	python3 remote.py $(REMOTE_ARGS) retrieve

remote-ssh:
	python3 remote.py $(REMOTE_ARGS) ssh

remote-logs:
	python3 remote.py $(REMOTE_ARGS) logs

remote-status:
	python3 remote.py $(REMOTE_ARGS) status

# --- Setup --------------------------------------------------------------------

$(VENV_DIR):
	command -v uv &> /dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$$HOME/.local/bin:$$PATH"; }
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv venv

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
			--window-pattern=L \
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
			--window-pattern=L \
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
