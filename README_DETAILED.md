WikiOracle / NanoChat — Deployment Architecture
================================================

OVERVIEW
--------
WikiOracle trains a small language model (NanoChat) on EC2 GPU instances and
deploys the resulting artifacts to a Lightsail WordPress instance at
wikiOracle.org for hosting.

Two machines are involved beyond the local dev laptop:
  1. EC2 GPU instance (ephemeral) — trains the model, then gets terminated
  2. Lightsail instance (persistent) — hosts wikiOracle.org (Bitnami WordPress)

KEY FILES
---------
  Makefile          — Top-level orchestration. All commands run via `make`.
  remote.py         — Python script that manages EC2 lifecycle and deployment.
  nanochat/         — Git submodule containing the NanoChat model code.
  .ec2/             — Local state directory (instance-id, instance-ip, run-meta.json).
                      Created by `remote.py launch`. Gitignored.
  output/           — Local directory for run summaries. Gitignored.

SSH KEYS
--------
  ~/.ssh/nanochat-key.pem   EC2 key pair. Auto-created by remote.py if missing.
  ~/.ssh/wikiOracle.pem     Lightsail key for wikiOracle.org (user: bitnami).
                            Copied from /bits/cloud/bin/arssh.pem. Must exist
                            before running deploy commands.

REMOTE TRAINING FLOW (make remote)
-----------------------------------
  1. Launch EC2 instance (p4d.24xlarge by default)
  2. Wait for SSH
  3. Git clone WikiOracle repo, overlay any local modifications via rsync
  4. Start training in a detached screen session
  5. Poll every 30s for ~/done.json (training completion marker)
  6. On completion: retrieve artifacts to local machine, terminate EC2

DEPLOY FLOW (make remote-deploy-launch)
----------------------------------------
Same as above, but instead of retrieving to local machine:
  1. Pre-flight: Validate WikiOracle PEM exists, test SSH + write access to
     /opt/bitnami/wordpress/files/wikiOracle.org/nanochat BEFORE launching EC2
  2. Launch EC2 and train as normal
  3. After training completes:
     a. SCP the EC2 key (nanochat-key.pem) from local -> WikiOracle at /tmp/ec2.pem
     b. Write a deploy.sh script on WikiOracle at
        /opt/bitnami/wordpress/files/wikiOracle.org/deploy.sh
     c. Execute deploy.sh: WikiOracle rsyncs from EC2 into ./nanochat/
        (excludes .venv, __pycache__, base_data, wandb, .env, etc.)
     d. Pull only lightweight metadata (train.log, sysinfo.txt) to local
     e. Generate summary.md locally
     f. Terminate EC2 instance
     g. Cleanup: delete /tmp/ec2.pem and deploy.sh from WikiOracle

SECURITY MODEL
--------------
WikiOracle pulls FROM EC2 (not the other way around). The EC2 key is
temporarily placed on WikiOracle so it can rsync from EC2. After the transfer,
the EC2 key is deleted from WikiOracle AND the EC2 instance is terminated,
making the key permanently useless. WikiOracle credentials never touch EC2.

MAKE TARGETS
------------
  make remote                  Launch EC2, train, retrieve artifacts locally
  make remote-deploy-launch    Launch EC2, train, deploy to WikiOracle
  make remote-deploy           Deploy from already-running EC2 to WikiOracle
  make remote-retrieve         Retrieve artifacts from EC2 to local, terminate
  make remote-ssh              SSH into running EC2 instance
  make remote-status           Check EC2 instance state and training progress
  make remote-logs             Tail training log on EC2

  make all / all-gpu           Full local pipeline (CPU / GPU)
  make some / some-gpu         Smoke test (10 iterations)

CONFIGURABLE VARIABLES (Makefile)
---------------------------------
  EC2_INSTANCE_TYPE   p4d.24xlarge (default)
  EC2_TARGET          Makefile target to run on EC2 (default: all-gpu)
  NPROC               GPUs per node (default: 8)
  GPU_DEPTH           Model depth (default: 26)
  GPU_BATCH           Batch size per device (default: 4)
  WO_KEY_FILE         ~/.ssh/wikiOracle.pem
  WO_USER             bitnami
  WO_HOST             wikiOracle.org
  WO_DEST             /opt/bitnami/wordpress/files/wikiOracle.org/nanochat

REMOTE.PY SUBCOMMANDS
---------------------
  launch    Launch EC2, clone repo, start training. Polls for completion.
            --deploy flag: auto-deploy to WikiOracle instead of local retrieve.
  retrieve  Pull artifacts to local machine, generate summary, terminate EC2.
  deploy    Deploy from EC2 to WikiOracle, generate local summary, terminate EC2.
  ssh       Interactive SSH to EC2.
  logs      Tail training log.
  status    Check instance state and detect training stage.

REMOTE.PY KEY FUNCTIONS
-----------------------
  validate_wo_connection()  — Pre-flight check: PEM exists, SSH works, can write
                              to destination directory on WikiOracle.
  deploy_to_wikioracle()    — Copies EC2 key to WikiOracle, writes deploy.sh,
                              executes rsync (WikiOracle pulls from EC2).
  cleanup_wo_deploy()       — Removes /tmp/ec2.pem and deploy.sh from WikiOracle.
  generate_run_summary()    — Computes timing/cost, writes summary.md.
                              Shared between cmd_retrieve and cmd_deploy.
  cmd_launch()              — Full EC2 launch + training + polling.
                              Calls cmd_deploy or cmd_retrieve on completion.
  cmd_deploy()              — Standalone deploy (for use after Ctrl-C detach).
  cmd_retrieve()            — Standalone retrieve to local machine.

LIGHTSAIL INSTANCE DETAILS
---------------------------
  Host:      wikiOracle.org (also accessible at 34.220.176.137)
  Platform:  Bitnami WordPress on Amazon Lightsail
  User:      bitnami
  Key:       ~/.ssh/wikiOracle.pem
  Deploy to: /opt/bitnami/wordpress/files/wikiOracle.org/nanochat

CTRL-C BEHAVIOR
---------------
If you Ctrl-C during the polling loop in `make remote-deploy-launch`:
  - EC2 instance keeps running
  - Use `make remote-status` to check progress
  - Use `make remote-deploy` to deploy and terminate when ready
  - Use `make remote-logs` to tail the training log

STATE FILES (.ec2/)
-------------------
  instance-id     EC2 instance ID (e.g., i-0abc123...)
  instance-ip     Public IP of the running instance
  run-meta.json   Launch parameters, timing, instance details

RSYNC EXCLUSIONS FOR DEPLOY
----------------------------
The following are excluded when deploying to WikiOracle:
  .venv/  __pycache__/  *.pyc  base_data/  dev/  dev-ignore/
  wandb/  .env  eval_bundle/  identity_conversations.jsonl
  words_alpha.txt  .git  uv.lock  pyproject.toml
