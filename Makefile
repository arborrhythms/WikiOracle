# WikiOracle Makefile
#
# Top-level workflow:
#   make install          — create .venv (shim + NanoChat), install all deps
#   make build            — train model (alias for 'make train')
#   make sync HOST=remote — sync app + checkpoints to/from production server
#   make run              — start WikiOracle Flask shim locally
#
# Contributors: install → build → run gets you a working local instance.
# Maintainers:  sync and up/down manage the production Lightsail server.
#
# Key variables:
#   ARCH=cpu|gpu   — target architecture (default: cpu)
#   HOST=local|remote — target host for sync/up/down/nano_*/wo_* (default: local)

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
WO_NANOCHAT      ?= /opt/bitnami/wordpress/files/WikiOracle.org/nanochat
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
WO_DEST           ?= /opt/bitnami/wordpress/files/WikiOracle.org/client

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
        install build sync run \
        build_venv build_setup \
        build_data build_tokenizer build_preprocess build_sft \
        train_pretrain train_finetune train nano_train \
        train_remote train_retrieve train_ssh train_status train_logs train_deploy \
        test test_eval test_unit test_basicmodel \
        run_init run_server run_debug run_cli run_web parse \
        sync_remote sync_checkpoint_pull sync_checkpoint_push \
        nano_deploy nano_start nano_stop nano_restart nano_status nano_logs \
        wo_deploy wo_start wo_stop wo_restart wo_status wo_logs wo_migrate \
        basic_data basic_train basic_test basic_run basic_build \
        basic_start basic_stop basic_restart basic_status basic_logs \
        openclaw_setup openclaw_run openclaw_test \
        doc_report doc_pdf clean clean_all \
        remote remote_retrieve remote_ssh remote_status remote_logs \
        remote_deploy remote_deploy_launch \
        checkpoint_pull checkpoint_push

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
	@echo "Contributor workflow:  make install → make build → make run"
	@echo "Maintainer workflow:   make sync HOST=remote → make up HOST=remote"
	@echo ""
	@echo "Top-level targets:"
	@echo "  make install            Create .venv and install all dependencies (ARCH=cpu|gpu)"
	@echo "  make build              Train model (alias for 'make train', ARCH=cpu|gpu)"
	@echo "  make sync HOST=remote   Sync app + checkpoints to/from server"
	@echo "  make run                Start WikiOracle local shim (foreground)"
	@echo "  make up HOST=remote     Restart both services on production"
	@echo "  make down HOST=remote   Stop both services"
	@echo "  make all                Full pipeline: install + train + eval + report"
	@echo ""
	@echo "Training (train_*):"
	@echo "  make train              Train BasicModel (embeddings + model)"
	@echo "  make nano_train         Full NanoChat pipeline: data + tok + pretrain + finetune"
	@echo "  make train_pretrain     Pretrain NanoChat base model (ARCH=cpu|gpu)"
	@echo "  make train_finetune     NanoChat supervised fine-tuning (ARCH=cpu|gpu)"
	@echo "  make train_remote       Launch EC2, copy repo, start training"
	@echo "  make train_deploy       Launch EC2, train, deploy to WikiOracle"
	@echo "  make train_retrieve     Pull artifacts, terminate EC2 instance"
	@echo "  make train_ssh/status/logs"
	@echo ""
	@echo "Test / Evaluation (test_*):"
	@echo "  make test               Run all tests (unit + basicmodel)"
	@echo "  make test_unit          Run WikiOracle unit tests"
	@echo "  make test_basicmodel    Run BasicModel tests"
	@echo "  make test_eval          Evaluate model (ARCH=cpu|gpu)"
	@echo ""
	@echo "Run / Inference (run_*):"
	@echo "  make run_debug          Start WikiOracle local shim (debug mode)"
	@echo "  make run_init           Remove state files for a fresh start"
	@echo "  make run_cli            Chat with the model (CLI)"
	@echo "  make run_web            Chat with the model (Web UI + /train)"
	@echo ""
	@echo "Sync (sync_*):"
	@echo "  make sync HOST=remote            Sync app + checkpoints to/from server"
	@echo "  make sync_remote                 Sync from running EC2 to WikiOracle"
	@echo "  make sync_checkpoint_pull/push   Backup/restore fine-tuning weights"
	@echo ""
	@echo "BasicModel (basic_*):"
	@echo "  make basic_build            Full pipeline: data + train + test"
	@echo "  make basic_data             Download FineWeb-EDU shards"
	@echo "  make basic_train            Train sentence embeddings"
	@echo "  make basic_test             Run BasicModel tests"
	@echo "  make basic_run              Run BasicModel (BASIC_XML=data/simple.xml)"
	@echo ""
	@echo "Service control (nano_*/wo_*/basic_*, HOST=local|remote):"
	@echo "  make nano_start/stop/restart/status/logs"
	@echo "  make wo_start/stop/restart/status/logs"
	@echo "  make basic_start/stop/restart/status/logs"
	@echo ""
	@echo "Other:"
	@echo "  make openclaw_setup/run/test"
	@echo "  make doc_pdf / doc_report"
	@echo "  make clean / clean_all"
	@echo ""
	@echo "Key variables:"
	@echo "  ARCH=cpu|gpu            Target architecture (default: cpu)"
	@echo "  HOST=local|remote       Target host for up/down/nano_*/wo_* (default: local)"
	@echo "  NANO_PORT=8000          NanoChat server port (local mode)"
	@echo "  NPROC=8                 GPUs per node for torchrun"

# ---- All / Service Control ----------------------------------------------------

all: install train test_eval doc_report

up: nano_restart wo_restart

down: nano_stop wo_stop

deploy: up

some:
ifeq ($(ARCH),gpu)
	$(MAKE) all ARCH=gpu GPU_ITERS=10 DATA_SHARDS_FULL=8 EVAL_MAX_PER_TASK=16
else
	$(MAKE) all ARCH=cpu CPU_ITERS=10
endif

# --- Training on EC2 (train_remote/retrieve/ssh/status/logs/deploy) ----------

REMOTE_ARGS := --region=$(EC2_REGION) --key-name=$(EC2_KEY_NAME) \
               --key-file=$(EC2_KEY_FILE) --user=$(EC2_USER)

train_remote:
ifndef ALERT_EMAIL
	$(error ALERT_EMAIL is required — e.g. make train_remote ALERT_EMAIL=you@example.com)
endif
ifndef EC2_TARGET
	$(error EC2_TARGET is required — e.g. make train_remote EC2_TARGET=all)
endif
	python3 bin/remote.py $(REMOTE_ARGS) launch \
		--instance-type=$(EC2_INSTANCE_TYPE) \
		--disk-size=$(EC2_DISK_SIZE) \
		--nproc=$(NPROC) \
		--wandb-run=$(WANDB_RUN) \
		--data-shards=$(DATA_SHARDS_FULL) \
		--target="$(EC2_TARGET)" \
		--alert-email=$(ALERT_EMAIL)

train_retrieve:
	python3 bin/remote.py $(REMOTE_ARGS) retrieve

train_ssh:
	python3 bin/remote.py $(REMOTE_ARGS) ssh

train_logs:
	python3 bin/remote.py $(REMOTE_ARGS) logs

train_status:
	python3 bin/remote.py $(REMOTE_ARGS) status

train_deploy:
ifndef ALERT_EMAIL
	$(error ALERT_EMAIL is required — e.g. make train_deploy ALERT_EMAIL=you@example.com)
endif
ifndef EC2_TARGET
	$(error EC2_TARGET is required — e.g. make train_deploy EC2_TARGET=all)
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

sync_remote:
	python3 bin/remote.py $(REMOTE_ARGS) deploy $(DEPLOY_ARGS)

# Legacy aliases for remote_* targets
remote: train_remote
remote_retrieve: train_retrieve
remote_ssh: train_ssh
remote_logs: train_logs
remote_status: train_status
remote_deploy_launch: train_deploy
remote_deploy: sync_remote

# --- NanoChat Server (HOST=local|remote) --------------------------------------
# When HOST=local  → background process with PID file (localhost:NANO_PORT)
# When HOST=remote → SSH to WO_HOST, manage via systemctl nanochat

WO_SSH := ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10 $(WO_USER)@$(WO_HOST)

WO_RSYNC := rsync -avz -e "ssh -i $(WO_KEY_FILE) -o ConnectTimeout=10"

sync:
ifeq ($(HOST),local)
	@echo "Sync is a remote-only operation. Use: make sync HOST=remote"
else
	@echo "=== Syncing app → $(WO_HOST):$(WO_DEST) ==="
	$(WO_RSYNC) --delete \
		--exclude .venv \
		--exclude .git/ \
		--exclude output/ \
		--exclude nanochat/ \
		--exclude config.xml \
		--exclude state.xml \
		--exclude '*.pem' \
		--exclude __pycache__/ \
		--exclude .DS_Store \
		. $(WO_USER)@$(WO_HOST):$(WO_DEST)/
	@echo ""
	@echo "=== Syncing checkpoints (bidirectional) ==="
	mkdir -p "$(CHECKPOINT_BAK)" output/base_checkpoints
	$(WO_RSYNC) --update "$(WO_USER)@$(WO_HOST):$(WO_CHECKPOINT)/" "$(CHECKPOINT_BAK)/"
	$(WO_RSYNC) --update "$(CHECKPOINT_BAK)/" "$(WO_USER)@$(WO_HOST):$(WO_CHECKPOINT)/"
	$(WO_RSYNC) --update "$(WO_USER)@$(WO_HOST):$(WO_NANOCHAT)/base_checkpoints/" "output/base_checkpoints/" 2>/dev/null || true
	$(WO_RSYNC) --update "output/base_checkpoints/" "$(WO_USER)@$(WO_HOST):$(WO_NANOCHAT)/base_checkpoints/" 2>/dev/null || true
	@echo ""
	@echo "=== Installing service files ==="
	$(WO_SSH) "sudo cp $(WO_DEST)/data/wikioracle.service /etc/systemd/system/ && \
		sudo cp $(WO_DEST)/data/nanochat.service /etc/systemd/system/ && \
		sudo cp $(WO_DEST)/data/basicmodel.service /etc/systemd/system/ && \
		sudo systemctl daemon-reload"
	@echo "Sync complete. Run 'make up HOST=remote' to restart services."
endif

nano_deploy: sync
wo_deploy: sync

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

## wo_deploy is now an alias for sync (above)

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

# --- Migration (chat/ → client/) ---------------------------------------------
# Rename WikiOracle.org/chat to WikiOracle.org/client, preserving NanoChat
# build derivatives (.venv, checkpoints) by pulling them locally first.
#
# Usage: make wo_migrate HOST=remote

WO_BASE         := /opt/bitnami/wordpress/files/WikiOracle.org
WO_OLD_CHAT     := $(WO_BASE)/chat

wo_migrate:
ifeq ($(HOST),local)
	@echo "Migration is a remote-only operation. Use: make wo_migrate HOST=remote"
	@exit 1
else
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  WikiOracle Directory Migration                            ║"
	@echo "║  WikiOracle.org/chat → WikiOracle.org/client               ║"
	@echo "║  WikiOracle.org/nanochat (unchanged)                       ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@printf "Type YES to continue: " && read answer && [ "$$answer" = "YES" ] || { echo "Aborted."; exit 1; }

	@echo ""
	@echo "=== Step 1/4: Stop services ==="
	$(WO_SSH) "sudo systemctl stop wikioracle nanochat || true"

	@echo ""
	@echo "=== Step 2/4: Copy chat → client on remote ==="
	$(WO_SSH) "cp -a $(WO_OLD_CHAT) $(WO_BASE)/client"

	@echo ""
	@echo "=== Step 3/4: Deploy updated service files + app code ==="
	$(MAKE) wo_deploy HOST=remote
	$(MAKE) nano_deploy HOST=remote
	$(WO_SSH) "cd $(WO_BASE)/client && rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

	@echo ""
	@echo "=== Step 4/4: Restart services and verify ==="
	$(WO_SSH) "sudo systemctl daemon-reload && sudo systemctl start nanochat wikioracle"
	@sleep 3
	$(WO_SSH) "sudo systemctl status nanochat wikioracle --no-pager -l" || true

	@echo ""
	@echo "=== Done ==="
	@echo "Migration complete. Old directory preserved at $(WO_OLD_CHAT)/"
	@echo "Once verified, remove manually:"
	@echo "  ssh -i $(WO_KEY_FILE) $(WO_USER)@$(WO_HOST) 'rm -rf $(WO_OLD_CHAT)'"
endif

# --- Install / Build / Run (top-level) ----------------------------------------

$(VENV_DIR):
	command -v uv &> /dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$$HOME/.local/bin:$$PATH"; }
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv venv

install: $(VENV_DIR)
	deactivate 2>/dev/null || true
	rm -rf $(SHIM_VENV)
	python3 -m venv $(SHIM_VENV)
	$(SHIM_ACTIVATE) && python -m pip install --upgrade pip setuptools wheel && \
		python -m pip install -r requirements.txt
ifeq ($(ARCH),gpu)
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv sync --extra gpu
else
	export PATH="$$HOME/.local/bin:$$PATH" && cd $(NANOCHAT_DIR) && uv sync --extra cpu
endif

build: train

run:
	$(SHIM_ACTIVATE) && python3 $(WIKIORACLE_APP)

# --- Build / Setup (legacy aliases) ------------------------------------------

build_venv: install

build_setup: install

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

train: basic_train
	@echo "BasicModel training pipeline complete."

nano_train: build_data build_tokenizer train_pretrain train_finetune
	@echo "$(ARCH) NanoChat training pipeline complete."

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

test: test_unit test_basicmodel

test_unit:
	$(SHIM_ACTIVATE) && PYTHONPATH="$(NANOCHAT_BASE):$(CURDIR)/bin" NANOCHAT_BASE_DIR="$(NANOCHAT_BASE)" \
		python3 test/run_tests.py

test_basicmodel: basic_test

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

# --- Checkpoint sync (sync_checkpoint_*) ---------------------------------------
# Use sync_checkpoint_pull before enabling online training to snapshot the
# current fine-tuning weights.  Use sync_checkpoint_push to restore them.

sync_checkpoint_pull:
	@echo "Pulling fine-tuning checkpoints from $(WO_HOST) → $(CHECKPOINT_BAK)/ ..."
	mkdir -p "$(CHECKPOINT_BAK)"
	$(WO_RSYNC) --delete \
		"$(WO_USER)@$(WO_HOST):$(WO_CHECKPOINT)/" "$(CHECKPOINT_BAK)/"
	@echo "Done. Backup at $(CHECKPOINT_BAK)/"

sync_checkpoint_push:
	@test -d "$(CHECKPOINT_BAK)" || { echo "No backup at $(CHECKPOINT_BAK)/"; exit 1; }
	@echo "Pushing $(CHECKPOINT_BAK)/ → $(WO_HOST) fine-tuning checkpoints ..."
	$(WO_RSYNC) --delete \
		"$(CHECKPOINT_BAK)/" "$(WO_USER)@$(WO_HOST):$(WO_CHECKPOINT)/"
	@echo "Done. Run 'make wo_restart' to reload weights."

# Legacy aliases
checkpoint_pull: sync_checkpoint_pull
checkpoint_push: sync_checkpoint_push

# --- BasicModel (basic_*) -----------------------------------------------------
# Mirrors nano_* structure for the BasicModel subsystem.
#   Training:  basic_data, basic_train, basic_build
#   Testing:   basic_test
#   Execution: basic_run (foreground XML)
#   Server:    basic_start, basic_stop, basic_restart, basic_status, basic_logs

BASIC_DIR        := basicmodel
BASIC_PYTHON     := cd $(BASIC_DIR) && PYTHONPATH=bin .venv/bin/python
BASIC_XML        ?= data/BasicModel.xml
BASIC_SHARDS     ?= 1
BASIC_MAX_DOCS   ?= 10000
BASIC_VEC_SIZE   ?= 100
BASIC_EPOCHS     ?= 1
BASIC_MIN_COUNT  ?= 5
BASIC_BATCH_SIZE ?= 256
BASIC_PORT       ?= 8001
BASIC_HOST       ?= 127.0.0.1
BASIC_PID        := .basic.pid
BASIC_LOG        ?= output/basicmodel.log

basic_data:
	cd $(BASIC_DIR) && PYTHONPATH=bin .venv/bin/python -c \
		"from embed import get_shard_paths; paths = get_shard_paths('data/fineweb', $(BASIC_SHARDS)); print(f'{len(paths)} shard(s) ready')"

basic_train: basic_data
	@if [ -f $(BASIC_DIR)/output/embeddings/sentence.pt ]; then \
		echo "[BasicModel] Step 1/2: Embeddings already exist, skipping (delete to retrain)"; \
	else \
		echo "[BasicModel] Step 1/2: Training sentence embeddings..."; \
		$(BASIC_PYTHON) bin/embed.py \
			--config data/sentence.cfg \
			--output output/embeddings/sentence.pt \
			--num-shards $(BASIC_SHARDS) --max-docs $(BASIC_MAX_DOCS) \
			--vector-size $(BASIC_VEC_SIZE) --epochs $(BASIC_EPOCHS) \
			--min-count $(BASIC_MIN_COUNT) \
			--batch-size $(BASIC_BATCH_SIZE); \
	fi
	@echo "[BasicModel] Step 2/2: Training model ($(BASIC_XML))..."
	$(BASIC_PYTHON) bin/BasicModel.py $(BASIC_XML)

basic_test:
	BASICMODEL_DEVICE=cpu $(MAKE) -C $(BASIC_DIR) test

basic_run:
	$(BASIC_PYTHON) bin/BasicModel.py $(BASIC_XML)

basic_build: basic_data basic_train basic_test
	@echo "BasicModel build complete."

basic_start:
ifeq ($(HOST),local)
	@if [ -f $(BASIC_PID) ] && kill -0 $$(cat $(BASIC_PID)) 2>/dev/null; then \
		echo "BasicModel already running (PID $$(cat $(BASIC_PID)), port $(BASIC_PORT))"; \
	else \
		rm -f $(BASIC_PID); \
		if "$(CURDIR)/$(BASIC_DIR)/.venv/bin/python" "$(CURDIR)/bin/launch_background.py" \
			--cwd "$(CURDIR)/$(BASIC_DIR)" \
			--pid-file "$(BASIC_PID)" \
			--log-file "$(BASIC_LOG)" \
			--wait 1.0 \
			--ready-url "http://127.0.0.1:$(BASIC_PORT)/health" \
			--ready-timeout 30 \
			--env PYTHONPATH=bin \
			-- "$(CURDIR)/$(BASIC_DIR)/.venv/bin/python" bin/serve.py \
				-p $(BASIC_PORT) \
				--host $(BASIC_HOST) \
			> /dev/null; then \
			echo "BasicModel starting on port $(BASIC_PORT) (PID $$(cat $(BASIC_PID)))"; \
		else \
			echo "BasicModel failed to start. See $(BASIC_LOG)"; \
			rm -f $(BASIC_PID); \
			exit 1; \
		fi; \
	fi
else
	$(WO_SSH) "sudo systemctl start basicmodel"
	@echo "BasicModel server started on $(WO_HOST)"
endif

basic_stop:
ifeq ($(HOST),local)
	@if [ -f $(BASIC_PID) ]; then \
		kill $$(cat $(BASIC_PID)) 2>/dev/null && echo "BasicModel stopped" || echo "BasicModel not running"; \
		rm -f $(BASIC_PID); \
	else \
		echo "No PID file found"; \
	fi
else
	$(WO_SSH) "sudo systemctl stop basicmodel"
	@echo "BasicModel server stopped on $(WO_HOST)"
endif

basic_restart:
ifeq ($(HOST),local)
	$(MAKE) basic_stop
	$(MAKE) basic_start \
		BASIC_PORT=$(BASIC_PORT) \
		BASIC_HOST=$(BASIC_HOST) \
		BASIC_PID=$(BASIC_PID) \
		BASIC_LOG=$(BASIC_LOG)
else
	$(WO_SSH) "sudo systemctl restart basicmodel"
	@echo "BasicModel server restarted on $(WO_HOST)"
endif

basic_status:
ifeq ($(HOST),local)
	@echo "BasicModel:"
	@if [ -f $(BASIC_PID) ] && kill -0 $$(cat $(BASIC_PID)) 2>/dev/null; then \
		echo "  Server: running (PID $$(cat $(BASIC_PID)), port $(BASIC_PORT))"; \
	else \
		echo "  Server: not running"; \
	fi
	@if [ -f $(BASIC_DIR)/output/embeddings/sentence.pt ]; then \
		echo "  Embeddings: $(BASIC_DIR)/output/embeddings/sentence.pt (exists)"; \
	else \
		echo "  Embeddings: not built (run 'make basic_train')"; \
	fi
else
	$(WO_SSH) "sudo systemctl status basicmodel --no-pager -l"
endif

basic_logs:
ifeq ($(HOST),local)
	@if [ -f $(BASIC_LOG) ]; then \
		tail -f $(BASIC_LOG); \
	else \
		echo "No log file at $(BASIC_LOG). Start the server first."; \
	fi
else
	$(WO_SSH) "sudo journalctl -u basicmodel -f --no-pager"
endif

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
