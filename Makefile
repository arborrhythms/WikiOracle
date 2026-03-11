# WikiOracle Makefile
# Builds, trains, and runs the NanoChat submodule.
# Supports both CPU/MPS (MacBook demo) and GPU (multi-GPU training) modes.

SHELL := /bin/bash

include /bits/projects/Make.mk

# --- Configuration -----------------------------------------------------------

NANOCHAT_DIR     := nanochat
VENV_DIR         := $(NANOCHAT_DIR)/.venv
ACTIVATE         := source "$(CURDIR)/$(VENV_DIR)/bin/activate"
SHIM_VENV        := .venv
SHIM_ACTIVATE    := source "$(CURDIR)/$(SHIM_VENV)/bin/activate"
NANOCHAT_BASE    := $(CURDIR)/$(NANOCHAT_DIR)
IDENTITY_DATA    := $(NANOCHAT_BASE)/identity_conversations.jsonl

# Checkpoint backup (for rollback before/after online training)
CHECKPOINT_BAK   := output/checkpoints
WO_NANOCHAT      ?= /opt/bitnami/wordpress/files/wikiOracle.org/nanochat
WO_CHECKPOINT    := $(WO_NANOCHAT)/chatsft_checkpoints
IDENTITY_URL     := https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl

# Architecture: cpu or gpu (override on command line, e.g. make train ARCH=gpu)
ARCH             ?= cpu

# GPU training defaults (override on command line, e.g. make NPROC=4 train_pretrain ARCH=gpu)
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

# --- Remote configuration (override via env or make VAR=value) ----------------

# Remote EC2 configuration
EC2_INSTANCE_TYPE ?= p5.4xlarge     # 1× H100-80GB ~$6.88/hr (alt: p4d.24xlarge 8× A100 ~$32.77/hr)
EC2_REGION        ?= us-west-2
EC2_KEY_NAME      ?= nanochat-key
EC2_KEY_FILE      ?= ~/.ssh/$(EC2_KEY_NAME).pem
EC2_DISK_SIZE     ?= 200
EC2_USER          ?= ubuntu
EC2_TARGET        ?=

# WikiOracle (Lightsail) deployment configuration
WO_KEY_FILE       ?= ./wikiOracle.pem
WO_USER           ?= bitnami
WO_HOST           ?= wikiOracle.org
WO_DEST           ?= /opt/bitnami/wordpress/files/wikiOracle.org/chat

ALERT_EMAIL ?=
WIKIORACLE_APP ?= bin/wikioracle.py

# --- Local/Remote switching ---------------------------------------------------
HOST      ?= local
NANO_PORT ?= 8000
NANO_HOST ?= 127.0.0.1
NANO_SOURCE ?= sft
NANO_MODEL_TAG ?= d26
NANO_STEP ?=
NANO_DTYPE ?= float32
NANO_DEVICE_TYPE ?= cpu
NANO_READY_TIMEOUT ?= 45
NANO_PID  := .nano.pid
WO_PID    := .wo.pid
NANO_LOG  ?= output/nanochat.log
WO_LOG    ?= output/wikioracle.log
WO_BIND_HOST ?= 127.0.0.1
WO_PORT ?= 8888
WO_READY_TIMEOUT ?= 45

DEPLOY_ARGS := --wo-key-file=$(WO_KEY_FILE) --wo-user=$(WO_USER) \
               --wo-host=$(WO_HOST) --wo-dest=$(WO_DEST)

# Vote question is now handled by test_voting.py::TestAlphaOutputDiamond

# --- Phony targets ------------------------------------------------------------

.PHONY: all some up down deploy help \
        build_venv build_setup \
        build_data build_tokenizer build_preprocess \
        train_pretrain train_finetune train \
        test_eval test_unit \
        run_init run_server run_debug run_cli run_web \
        nano_deploy nano_start nano_stop nano_restart nano_status nano_logs \
        wo_deploy wo_start wo_stop wo_restart wo_status wo_logs \
        parse \
        doc_report clean clean_all \
        remote remote_retrieve remote_ssh remote_status remote_logs \
        remote_deploy remote_deploy_launch \
        checkpoint_pull checkpoint_push \
        openclaw_setup openclaw_run openclaw_test \
        doc_pdf

# Ordered list of doc chapters for PDF generation
PDF_CHAPTERS := README.md \
  doc/WikiOracle.md \
  doc/Constitution.md \
  doc/Installation.md \
  doc/Truth.md \
  doc/Ethics.md \
  doc/PrivacyAndSecurity.md \
  doc/Freedom.md \
  doc/Voting.md \
  doc/Logic.md \
  doc/Grammar.md \
  doc/Training.md \
  doc/Implementation.md \
  doc/Config.md \
  doc/State.md \
  doc/UserInterface.md \
  doc/FutureWork.md \
  doc/BuddhistParallels.md \
  doc/ProposedLicense.md


# --- Help ---------------------------------------------------------------------

help:
	@echo "WikiOracle / NanoChat Makefile"
	@echo ""
	@echo "  make all                Full pipeline: setup + train + eval + report (ARCH=cpu)"
	@echo "  make all ARCH=gpu       Full pipeline (GPU)"
	@echo "  make some               Lightweight smoke test (10 iters, ARCH=cpu)"
	@echo "  make some ARCH=gpu      Lightweight smoke test (GPU)"
	@echo "  make up                 Deploy + restart nano and wo services"
	@echo "  make down               Stop nano and wo services"
	@echo "  make remote             Launch EC2, copy code, train, auto-terminate"
	@echo ""
	@echo "Build / Setup (build_*):"
	@echo "  make build_venv         Create .venv and install shim deps (flask, requests)"
	@echo "  make build_setup        Install NanoChat dependencies (CPU/MPS)"
	@echo "  make build_setup ARCH=gpu  Install dependencies (GPU/CUDA)"
	@echo "  make build_data         Download training data shards"
	@echo "  make build_tokenizer    Train and evaluate the BPE tokenizer"
	@echo "  make build_preprocess   Preprocess corpus for sensation tags"
	@echo ""
	@echo "Training (train_*):"
	@echo "  make train_pretrain     Pretrain base model (ARCH=cpu|gpu)"
	@echo "  make train_finetune     Supervised fine-tuning (ARCH=cpu|gpu)"
	@echo "  make train              Full pipeline: data + tok + pretrain + finetune (ARCH=cpu|gpu)"
	@echo ""
	@echo "Test / Evaluation (test_*):"
	@echo "  make test_unit          Run unit tests"
	@echo "  make test_eval          Evaluate model (ARCH=cpu|gpu)"
	@echo ""
	@echo "Run / Inference (run_*):"
	@echo "  make run_server         Start WikiOracle local shim (foreground)"
	@echo "  make run_debug          Start WikiOracle local shim (debug mode)"
	@echo "  make run_init           Remove state files for a fresh start"
	@echo "  make run_cli            Chat with the model (CLI)"
	@echo "  make run_web            Chat with the model (Web UI + /train)"
	@echo ""
	@echo "NanoChat Server (nano_*):"
	@echo "  make nano_deploy        Deploy nanochat.service     (remote only)"
	@echo "  make nano_start         Start NanoChat              (local: PID file, remote: systemctl)"
	@echo "  make nano_stop          Stop NanoChat"
	@echo "  make nano_restart       Restart NanoChat"
	@echo "  make nano_status        Check NanoChat status"
	@echo "  make nano_logs          Tail NanoChat logs           (remote only)"
	@echo ""
	@echo "WikiOracle Server (wo_*):"
	@echo "  make wo_deploy          Deploy WikiOracle shim      (remote only)"
	@echo "  make wo_start           Start WikiOracle             (local: PID file, remote: systemctl)"
	@echo "  make wo_stop            Stop WikiOracle"
	@echo "  make wo_restart         Restart WikiOracle"
	@echo "  make wo_status          Check WikiOracle status"
	@echo "  make wo_logs            Tail WikiOracle logs         (remote only)"
	@echo ""
	@echo "Remote (remote_*):"
	@echo "  make remote             Launch EC2 instance, copy repo, start training"
	@echo "  make remote_retrieve    Pull artifacts, generate summary, terminate instance"
	@echo "  make remote_ssh         SSH into running EC2 instance"
	@echo "  make remote_status      Check EC2 instance state"
	@echo "  make remote_logs        Tail training log on remote instance"
	@echo ""
	@echo "Deploy (remote_ → wo):"
	@echo "  make remote_deploy_launch  Launch EC2, train, deploy to WikiOracle"
	@echo "  make remote_deploy         Deploy from running EC2 to WikiOracle"
	@echo ""
	@echo "Checkpoint Backup (checkpoint_*):"
	@echo "  make checkpoint_pull    Pull SFT weights from WikiOracle → output/checkpoints/"
	@echo "  make checkpoint_push    Push output/checkpoints/ → WikiOracle SFT weights"
	@echo ""
	@echo "OpenClaw (openclaw_*):"
	@echo "  make openclaw_setup     Install OpenClaw + WikiOracle extension (pnpm install)"
	@echo "  make openclaw_run       Start OpenClaw with WikiOracle provider"
	@echo "  make openclaw_test      Run WikiOracle extension unit tests"
	@echo ""
	@echo "Documentation (doc_*):"
	@echo "  make doc_pdf            Generate PDF from all doc/*.md → output/WikiOracle.pdf"
	@echo "  make doc_report         Generate training report"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              Remove Python caches"
	@echo "  make clean_all          Remove caches and venv"
	@echo ""
	@echo "Overridable variables (pass on command line):"
	@echo "  ARCH=cpu|gpu            Target architecture (default: cpu)"
	@echo "  HOST=local|remote       Target host for nano_*/wo_* (default: local)"
	@echo "  NANO_PORT=8000          NanoChat server port (local mode)"
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

# ---- All / Service Control ----------------------------------------------------

all: build_setup train test_eval doc_report

up: nano_deploy wo_deploy nano_restart wo_restart

down: nano_stop wo_stop

deploy: up

some:
ifeq ($(ARCH),gpu)
	$(MAKE) all ARCH=gpu GPU_ITERS=10 DATA_SHARDS_FULL=8 EVAL_MAX_PER_TASK=16
else
	$(MAKE) all ARCH=cpu CPU_ITERS=10
endif

# --- Remote (EC2) -------------------------------------------------------------

REMOTE_ARGS := --region=$(EC2_REGION) --key-name=$(EC2_KEY_NAME) \
               --key-file=$(EC2_KEY_FILE) --user=$(EC2_USER)

remote:
ifndef ALERT_EMAIL
	$(error ALERT_EMAIL is required for remote builds — e.g. make remote ALERT_EMAIL=you@example.com)
endif
ifndef EC2_TARGET
	$(error EC2_TARGET is required for remote builds — e.g. make remote EC2_TARGET=all)
endif
	python3 bin/remote.py $(REMOTE_ARGS) launch \
		--instance-type=$(EC2_INSTANCE_TYPE) \
		--disk-size=$(EC2_DISK_SIZE) \
		--nproc=$(NPROC) \
		--wandb-run=$(WANDB_RUN) \
		--data-shards=$(DATA_SHARDS_FULL) \
		--target="$(EC2_TARGET)" \
		--alert-email=$(ALERT_EMAIL)

remote_retrieve:
	python3 bin/remote.py $(REMOTE_ARGS) retrieve

remote_ssh:
	python3 bin/remote.py $(REMOTE_ARGS) ssh

remote_logs:
	python3 bin/remote.py $(REMOTE_ARGS) logs

remote_status:
	python3 bin/remote.py $(REMOTE_ARGS) status

remote_deploy_launch:
ifndef ALERT_EMAIL
	$(error ALERT_EMAIL is required for remote builds — e.g. make remote_deploy_launch ALERT_EMAIL=you@example.com)
endif
ifndef EC2_TARGET
	$(error EC2_TARGET is required for remote builds — e.g. make remote_deploy_launch EC2_TARGET=all)
endif
	python3 bin/remote.py $(REMOTE_ARGS) launch \
		--instance-type=$(EC2_INSTANCE_TYPE) \
		--disk-size=$(EC2_DISK_SIZE) \
		--nproc=$(NPROC) \
		--wandb-run=$(WANDB_RUN) \
		--data-shards=$(DATA_SHARDS_FULL) \
		--target="$(EC2_TARGET)" \
		--alert-email=$(ALERT_EMAIL) \
		--deploy $(DEPLOY_ARGS)

remote_deploy:
	python3 bin/remote.py $(REMOTE_ARGS) deploy $(DEPLOY_ARGS)

# --- NanoChat Server (HOST=local|remote) --------------------------------------
# When HOST=local  → background process with PID file (localhost:NANO_PORT)
# When HOST=remote → SSH to WO_HOST, manage via systemctl nanochat

WO_SSH := ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10 $(WO_USER)@$(WO_HOST)

nano_deploy:
ifeq ($(HOST),local)
	@echo "Nothing to deploy locally."
else
	@echo "Deploying nanochat.service to $(WO_HOST) ..."
	scp -i $(WO_KEY_FILE) -o ConnectTimeout=10 \
		data/nanochat.service $(WO_USER)@$(WO_HOST):/tmp/nanochat.service
	$(WO_SSH) "sudo cp /tmp/nanochat.service /etc/systemd/system/ && sudo systemctl daemon-reload && rm /tmp/nanochat.service"
	@echo "nanochat.service deployed. Run 'make nano_restart HOST=remote' to apply."
endif

nano_start:
ifeq ($(HOST),local)
	@if [ -f $(NANO_PID) ] && kill -0 $$(cat $(NANO_PID)) 2>/dev/null; then \
		echo "NanoChat already running (PID $$(cat $(NANO_PID)), port $(NANO_PORT))"; \
	else \
		rm -f $(NANO_PID); \
		if "$(CURDIR)/$(VENV_DIR)/bin/python" "$(CURDIR)/bin/launch_background.py" \
			--cwd "$(CURDIR)/$(NANOCHAT_DIR)" \
			--pid-file "$(NANO_PID)" \
			--log-file "$(NANO_LOG)" \
			--wait 1.0 \
			--ready-url "http://127.0.0.1:$(NANO_PORT)/health" \
			--ready-timeout $(NANO_READY_TIMEOUT) \
			--env NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" \
			-- "$(CURDIR)/$(VENV_DIR)/bin/python" -m scripts.chat_web \
				-p $(NANO_PORT) \
				-d $(NANO_DTYPE) \
				--device-type $(NANO_DEVICE_TYPE) \
				--host $(NANO_HOST) \
				-i $(NANO_SOURCE) \
				$(if $(strip $(NANO_MODEL_TAG)),--model-tag $(NANO_MODEL_TAG),) \
				$(if $(strip $(NANO_STEP)),--step $(NANO_STEP),) \
			> /dev/null; then \
			echo "NanoChat starting on port $(NANO_PORT) (PID $$(cat $(NANO_PID)))"; \
		else \
			echo "NanoChat failed to start. See $(NANO_LOG)"; \
			rm -f $(NANO_PID); \
			exit 1; \
		fi; \
	fi
else
	$(WO_SSH) "sudo systemctl start nanochat"
	@echo "NanoChat server started on $(WO_HOST)"
endif

nano_stop:
ifeq ($(HOST),local)
	@if [ -f $(NANO_PID) ]; then \
		kill $$(cat $(NANO_PID)) 2>/dev/null && echo "NanoChat stopped" || echo "NanoChat not running"; \
		rm -f $(NANO_PID); \
	else \
		echo "No PID file found"; \
	fi
else
	$(WO_SSH) "sudo systemctl stop nanochat"
	@echo "NanoChat server stopped on $(WO_HOST)"
endif

nano_restart:
ifeq ($(HOST),local)
	$(MAKE) nano_stop
	$(MAKE) nano_start \
		NANO_PORT=$(NANO_PORT) \
		NANO_HOST=$(NANO_HOST) \
		NANO_SOURCE=$(NANO_SOURCE) \
		NANO_MODEL_TAG=$(NANO_MODEL_TAG) \
		NANO_STEP=$(NANO_STEP) \
		NANO_DTYPE=$(NANO_DTYPE) \
		NANO_DEVICE_TYPE=$(NANO_DEVICE_TYPE) \
		NANO_READY_TIMEOUT=$(NANO_READY_TIMEOUT) \
		NANO_PID=$(NANO_PID) \
		NANO_LOG=$(NANO_LOG)
else
	$(WO_SSH) "sudo systemctl restart nanochat"
	@echo "NanoChat server restarted on $(WO_HOST)"
endif

nano_status:
ifeq ($(HOST),local)
	@if [ -f $(NANO_PID) ] && kill -0 $$(cat $(NANO_PID)) 2>/dev/null; then \
		echo "NanoChat running (PID $$(cat $(NANO_PID)), port $(NANO_PORT))"; \
	else \
		echo "NanoChat not running"; \
	fi
else
	$(WO_SSH) "sudo systemctl status nanochat --no-pager -l"
endif

nano_logs:
ifeq ($(HOST),local)
	@echo "Local NanoChat logs go to stdout. Use 'make run_web' for foreground mode."
else
	$(WO_SSH) "sudo journalctl -u nanochat -f --no-pager"
endif

# --- WikiOracle Server (HOST=local|remote) ------------------------------------
# When HOST=local  → background Flask shim with PID file
# When HOST=remote → SSH to WO_HOST, manage via systemctl wikioracle

# Extra untracked files the server needs (e.g. runtime config with secrets).
WO_DEPLOY_EXTRA := config.xml

wo_deploy:
ifeq ($(HOST),local)
	@echo "Nothing to deploy locally."
else
	@echo "Deploying WikiOracle to $(WO_HOST):$(WO_DEST) ..."
	rsync -avz --delete --exclude .venv \
		-e "ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10" \
		--files-from=<(git ls-files -- bin client data test requirements.txt; echo $(WO_DEPLOY_EXTRA)) \
		. $(WO_USER)@$(WO_HOST):$(WO_DEST)/
	$(WO_SSH) "sudo cp $(WO_DEST)/data/wikioracle.service /etc/systemd/system/ && sudo systemctl daemon-reload"
	@echo "WikiOracle deployed. Run 'make wo_restart HOST=remote' to apply."
endif

wo_start:
ifeq ($(HOST),local)
	@if [ -f $(WO_PID) ] && kill -0 $$(cat $(WO_PID)) 2>/dev/null; then \
		echo "WikiOracle already running (PID $$(cat $(WO_PID)))"; \
	else \
		rm -f $(WO_PID); \
		if "$(CURDIR)/$(SHIM_VENV)/bin/python3" "$(CURDIR)/bin/launch_background.py" \
			--cwd "$(CURDIR)" \
			--pid-file "$(WO_PID)" \
			--log-file "$(WO_LOG)" \
			--wait 1.0 \
			--ready-url "https://$(WO_BIND_HOST):$(WO_PORT)/health" \
			--ready-timeout $(WO_READY_TIMEOUT) \
			--ready-insecure \
			--env WIKIORACLE_BIND_HOST="$(WO_BIND_HOST)" \
			--env WIKIORACLE_PORT="$(WO_PORT)" \
			-- "$(CURDIR)/$(SHIM_VENV)/bin/python3" "$(CURDIR)/$(WIKIORACLE_APP)" \
			> /dev/null; then \
			echo "WikiOracle starting (PID $$(cat $(WO_PID)))"; \
		else \
			echo "WikiOracle failed to start. See $(WO_LOG)"; \
			rm -f $(WO_PID); \
			exit 1; \
		fi; \
	fi
else
	$(WO_SSH) "sudo systemctl start wikioracle"
	@echo "WikiOracle started on $(WO_HOST)"
endif

wo_stop:
ifeq ($(HOST),local)
	@if [ -f $(WO_PID) ]; then \
		kill $$(cat $(WO_PID)) 2>/dev/null && echo "WikiOracle stopped" || echo "WikiOracle not running"; \
		rm -f $(WO_PID); \
	else \
		echo "No PID file found"; \
	fi
else
	$(WO_SSH) "sudo systemctl stop wikioracle"
	@echo "WikiOracle stopped on $(WO_HOST)"
endif

wo_restart:
ifeq ($(HOST),local)
	$(MAKE) wo_stop
	$(MAKE) wo_start \
		WO_BIND_HOST=$(WO_BIND_HOST) \
		WO_PORT=$(WO_PORT) \
		WO_READY_TIMEOUT=$(WO_READY_TIMEOUT) \
		WO_PID=$(WO_PID) \
		WO_LOG=$(WO_LOG)
else
	$(WO_SSH) "sudo systemctl restart wikioracle"
	@echo "WikiOracle restarted on $(WO_HOST)"
endif

wo_status:
ifeq ($(HOST),local)
	@if [ -f $(WO_PID) ] && kill -0 $$(cat $(WO_PID)) 2>/dev/null; then \
		echo "WikiOracle running (PID $$(cat $(WO_PID)))"; \
	else \
		echo "WikiOracle not running"; \
	fi
else
	$(WO_SSH) "sudo systemctl status wikioracle --no-pager -l"
endif

wo_logs:
ifeq ($(HOST),local)
	@echo "Local WikiOracle logs go to stdout. Use 'make run_server' for foreground mode."
else
	$(WO_SSH) "sudo journalctl -u wikioracle -f --no-pager"
endif

# --- Build / Setup ------------------------------------------------------------

$(VENV_DIR):
	command -v uv &> /dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$$HOME/.local/bin:$$PATH"; }
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv venv

build_venv:
	python3 -m venv $(SHIM_VENV)
	$(SHIM_ACTIVATE) && pip install -r requirements.txt

build_setup: $(VENV_DIR)
ifeq ($(ARCH),gpu)
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv sync --extra gpu
else
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv sync --extra cpu
endif

# --- Data ---------------------------------------------------------------------

build_data:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m nanochat.dataset -n $(DATA_SHARDS_INIT)

# --- Tokenizer ----------------------------------------------------------------

build_tokenizer: build_data
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.tok_train && \
		python -m scripts.tok_eval

# --- Identity conversations (fine-tuning data) --------------------------------

$(IDENTITY_DATA):
	curl -L -o "$(IDENTITY_DATA)" $(IDENTITY_URL)

# --- Pretrain -----------------------------------------------------------------

train_pretrain: build_tokenizer
ifeq ($(ARCH),gpu)
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
else
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
endif

# --- Fine-Tuning (Supervised) ------------------------------------------------

train_finetune: $(IDENTITY_DATA)
ifeq ($(ARCH),gpu)
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		export OMP_NUM_THREADS=1 && \
		torchrun --standalone --nproc_per_node=$(NPROC) \
			-m scripts.chat_sft -- \
			--device-batch-size=$(GPU_BATCH) \
			$(if $(GPU_ITERS),--num-iterations=$(GPU_ITERS)) \
			--run=$(WANDB_RUN)
else
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.chat_sft \
			--max-seq-len=$(CPU_SEQ_LEN) \
			--device-batch-size=$(CPU_BATCH) \
			--num-iterations=1500 \
			--run=$(WANDB_RUN)
endif

# --- Full training pipeline ---------------------------------------------------

train: build_data build_tokenizer train_pretrain train_finetune
	@echo "$(ARCH) training pipeline complete."

# --- Test / Evaluation --------------------------------------------------------

test_eval:
ifeq ($(ARCH),gpu)
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
else
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.base_eval \
			--device-batch-size=1 \
			--split-tokens=16384 \
			--max-per-task=16 && \
		python -m scripts.chat_eval -i sft
endif

# --- Run / Inference ----------------------------------------------------------

run_init:
	rm -f state.xml llm.xml
	@echo "State files removed — server will create a fresh one on next start."

run_server:
	$(SHIM_ACTIVATE) && python3 $(WIKIORACLE_APP)

run_debug:
	$(SHIM_ACTIVATE) && python3 $(WIKIORACLE_APP) --debug

test_unit:
	$(SHIM_ACTIVATE) && PYTHONPATH="$(NANOCHAT_BASE):$(CURDIR)/bin" NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" \
		python3 test/run_tests.py

run_cli:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m scripts.chat_cli

run_web:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python ../bin/nanochat_ext.py

parse:
	@$(SHIM_ACTIVATE) && python3 bin/parse.py $(SENTENCE)

# --- Documentation ------------------------------------------------------------

doc_report:
	cd $(NANOCHAT_DIR) && $(ACTIVATE) && \
		export NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" && \
		python -m nanochat.report generate

# --- Checkpoint backup / restore -----------------------------------------------
# Use checkpoint_pull before enabling online training to snapshot the current
# fine-tuning weights.  Use checkpoint_push to restore them if capture occurs.

checkpoint_pull:
	@echo "Pulling fine-tuning checkpoints from $(WO_HOST) → $(CHECKPOINT_BAK)/ ..."
	mkdir -p "$(CHECKPOINT_BAK)"
	rsync -avz --delete \
		-e "ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10" \
		"$(WO_USER)@$(WO_HOST):$(WO_CHECKPOINT)/" "$(CHECKPOINT_BAK)/"
	@echo "Done. Backup at $(CHECKPOINT_BAK)/"

checkpoint_push:
	@test -d "$(CHECKPOINT_BAK)" || { echo "No backup at $(CHECKPOINT_BAK)/"; exit 1; }
	@echo "Pushing $(CHECKPOINT_BAK)/ → $(WO_HOST) fine-tuning checkpoints ..."
	rsync -avz --delete \
		-e "ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10" \
		"$(CHECKPOINT_BAK)/" "$(WO_USER)@$(WO_HOST):$(WO_CHECKPOINT)/"
	@echo "Done. Run 'make wo_restart' to reload weights."

# --- OpenClaw -----------------------------------------------------------------

OPENCLAW_DIR  := openclaw

# pnpm — resolve via corepack (ships with Node ≥ 22), fall back to npx
PNPM := COREPACK_INTEGRITY_KEYS=0 pnpm

# Safety gate — OpenClaw's pnpm install pulls native binaries, installs git
# hooks, and runs postinstall scripts.  Never run on a host machine; use a
# sandboxed / disposable environment only.
_openclaw_confirm:
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  DANGER!!! ONLY RUN THIS IN A SANDBOXED ENVIROMENT!!!      ║"
	@echo "║                                                            ║"
	@echo "║  This target runs pnpm install / OpenClaw tooling that     ║"
	@echo "║  will download native binaries, install git hooks, and     ║"
	@echo "║  execute arbitrary postinstall scripts.                    ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@printf "Type YES to continue: " && read answer && [ "$$answer" = "YES" ] || { echo "Aborted."; exit 1; }

openclaw_setup: _openclaw_confirm
	git submodule update --init $(OPENCLAW_DIR)
	@command -v node >/dev/null 2>&1 || { echo "Node.js is required — install from https://nodejs.org"; exit 1; }
	@echo "Enabling corepack for pnpm …"
	corepack enable pnpm 2>/dev/null || true
	@echo "Installing OpenClaw dependencies …"
	cd "$(CURDIR)/$(OPENCLAW_DIR)" && $(PNPM) install
	@echo ""
	@echo "OpenClaw setup complete.  WikiOracle extension at:"
	@echo "  $(OPENCLAW_DIR)/extensions/wikioracle/"
	@echo ""
	@echo "Run 'make openclaw_run' to start (ensure WikiOracle server is running first)."

openclaw_run: _openclaw_confirm
	@test -d "$(OPENCLAW_DIR)/node_modules" || { echo "Run 'make openclaw_setup' first"; exit 1; }
	cd "$(CURDIR)/$(OPENCLAW_DIR)" && $(PNPM) start $(OPENCLAW_ARGS)

openclaw_test: _openclaw_confirm
	@test -d "$(OPENCLAW_DIR)/node_modules" || { echo "Run 'make openclaw_setup' first"; exit 1; }
	cd "$(CURDIR)/$(OPENCLAW_DIR)" && $(PNPM) vitest run extensions/wikioracle/ --reporter=verbose

# --- Sensation preprocessing --------------------------------------------------

CORPUS_INPUT  ?= $(NANOCHAT_BASE)/identity_conversations.jsonl
CORPUS_OUTPUT ?= data/tagged_corpus.jsonl

build_preprocess:
	@echo "Preprocessing $(CORPUS_INPUT) → $(CORPUS_OUTPUT) ..."
	$(SHIM_ACTIVATE) && python3 bin/sensation.py corpus "$(CORPUS_INPUT)" "$(CORPUS_OUTPUT)"

SFT_INPUT   ?= $(NANOCHAT_BASE)/identity_conversations.jsonl
SFT_OUTPUT  ?= data/sft_tagged.jsonl

build_sft:
	@echo "Preparing SFT corpus $(SFT_INPUT) → $(SFT_OUTPUT) ..."
	$(SHIM_ACTIVATE) && python3 bin/sensation.py sft "$(SFT_INPUT)" "$(SFT_OUTPUT)"

# --- PDF generation -----------------------------------------------------------
# Generate a single PDF from all doc/*.md files with README as index.

doc_pdf : WikiOracle.pdf
TITLE := WikiOracle Documentation

WikiOracle.pdf : $(PDF_CHAPTERS)
	@echo "Generating PDF from doc/*.md → output/WikiOracle.pdf ..."
	mkdir -p output
	$(MAKE_PDF) -o $@ $^
	@echo "Done: output/WikiOracle.pdf"

# --- Cleanup ------------------------------------------------------------------

clean:
	find $(NANOCHAT_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(NANOCHAT_DIR) -name '*.pyc' -delete 2>/dev/null || true

clean_all: clean
	rm -rf $(VENV_DIR)
