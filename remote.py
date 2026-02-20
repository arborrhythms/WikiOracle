#!/usr/bin/env python3
"""Launch an EC2 instance, clone the repo, and run NanoChat GPU training.

Clones from GitHub, then rsyncs any local modifications on top.
After training completes, retrieve artifacts with the 'retrieve' subcommand.

Usage:
    python remote.py launch [--instance-type=p4d.24xlarge] [--region=us-west-2] ...
    python remote.py retrieve   # Pull artifacts, generate summary, terminate
    python remote.py ssh
    python remote.py logs
    python remote.py status
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).parent / ".ec2"
OUTPUT_DIR = Path(__file__).parent / "output"

# EC2 instances are ephemeral — new host key each launch, IPs get recycled.
# Strict host-key checking would break every run; PEM auth is the real security.
EC2_SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=10",
]

# WikiOracle is a long-lived server — use normal host-key checking.
WO_SSH_OPTS = [
    "-o", "ConnectTimeout=10",
]

# WikiOracle (Lightsail) deployment defaults
WO_KEY_FILE_DEFAULT = "~/.ssh/wikiOracle.pem"
WO_USER_DEFAULT = "bitnami"
WO_HOST_DEFAULT = "wikiOracle.org"
WO_DEST_DEFAULT = "/opt/bitnami/wordpress/files/wikiOracle.org/chat"
WO_DEPLOY_SCRIPT = "/opt/bitnami/wordpress/files/wikiOracle.org/deploy.sh"
WO_EC2_TMP_KEY = "/tmp/ec2.pem"

DEPLOY_RSYNC_EXCLUDES = [
    ".venv/", "__pycache__/", "*.pyc", "base_data/", "dev/",
    "dev-ignore/", "wandb/", ".env", "eval_bundle/",
    "identity_conversations.jsonl", "words_alpha.txt",
    ".git",
]

# Hourly on-demand pricing (USD) for common GPU instance types
INSTANCE_PRICING = {
    "p4d.24xlarge": 32.77,
    "p4de.24xlarge": 40.97,
    "p5.4xlarge": 6.88,
    "p5.48xlarge": 98.32,
    "g5.xlarge": 1.006,
    "g5.48xlarge": 16.288,
}


def run(cmd, check=True, capture=False):
    """Run a shell command, printing it first."""
    print(f"  $ {' '.join(cmd)}")
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 and check:
            sys.exit(f"Error (exit {r.returncode}): {r.stderr.strip()}")
        return r.stdout.strip()
    subprocess.run(cmd, check=check)


def aws(*args, capture=True):
    """Run an AWS CLI command and return stdout."""
    cmd = ["aws"] + list(args)
    return run(cmd, capture=capture)


def ssh_cmd(key_file, user, ip, ssh_opts=None):
    """Build base SSH command list."""
    opts = ssh_opts if ssh_opts is not None else EC2_SSH_OPTS
    return ["ssh", "-i", key_file] + opts + [f"{user}@{ip}"]


def scp_cmd(key_file, ssh_opts=None):
    """Build base SCP command prefix."""
    opts = ssh_opts if ssh_opts is not None else EC2_SSH_OPTS
    return ["scp", "-i", key_file] + opts


def read_state(name):
    """Read a value from the state directory."""
    path = STATE_DIR / name
    if not path.exists():
        print(f"Error: {path} not found. Run 'python remote.py launch' first.")
        sys.exit(1)
    return path.read_text().strip()


def read_run_meta():
    """Read run metadata from state directory."""
    path = STATE_DIR / "run-meta.json"
    if not path.exists():
        print(f"Error: {path} not found. Run 'python remote.py launch' first.")
        sys.exit(1)
    return json.loads(path.read_text())


def write_state(name, value):
    """Write a value to the state directory."""
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / name).write_text(value + "\n")


def write_run_meta(meta):
    """Write run metadata to state directory."""
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / "run-meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def wait_for_ssh(key_file, user, ip, attempts=30, delay=10):
    """Poll until SSH is available."""
    print("Waiting for SSH...")
    for i in range(attempts):
        r = subprocess.run(
            ssh_cmd(key_file, user, ip) + ["true"],
            capture_output=True,
        )
        if r.returncode == 0:
            print("  SSH is ready.")
            return
        time.sleep(delay)
    print("Error: SSH did not become available.")
    sys.exit(1)


def validate_wo_connection(wo_key_file, wo_user, wo_host, wo_dest):
    """Validate WikiOracle PEM, write access, rsync, and return its public IP.

    Returns (expanded_key_file, wikioracle_public_ip).
    """
    wo_key_file = os.path.expanduser(wo_key_file)

    if not os.path.exists(wo_key_file):
        print(f"Error: WikiOracle key file not found: {wo_key_file}")
        print("Copy your key and set permissions:")
        print(f"  cp /bits/cloud/bin/arssh.pem {wo_key_file}")
        print(f"  chmod 600 {wo_key_file}")
        sys.exit(1)

    print(f"Testing write access to {wo_user}@{wo_host}:{wo_dest}...")
    r = subprocess.run(
        ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + [
            f"mkdir -p {wo_dest} && "
            f"echo test > {wo_dest}/.deploy-test && "
            f"rm -f {wo_dest}/.deploy-test"
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"Error: Cannot write to {wo_user}@{wo_host}:{wo_dest}")
        print(f"  {r.stderr.strip()}")
        sys.exit(1)
    print("  WikiOracle connectivity and write access OK.")

    # Check rsync is available on WikiOracle
    r = subprocess.run(
        ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + ["which rsync"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"Error: rsync not installed on {wo_host}")
        print(f"  Install it:  ssh {wo_user}@{wo_host} 'sudo apt-get install -y rsync'")
        sys.exit(1)
    print("  rsync available on WikiOracle.")

    # Get WikiOracle's public IP (needed for EC2 security group)
    wo_ip = subprocess.run(
        ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + ["curl -s https://checkip.amazonaws.com"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not wo_ip:
        print("Error: Could not determine WikiOracle's public IP.")
        sys.exit(1)
    print(f"  WikiOracle public IP: {wo_ip}")

    return wo_key_file, wo_ip


def cleanup_wo_deploy(wo_key_file, wo_user, wo_host):
    """Remove temporary EC2 key and deploy script from WikiOracle."""
    print("Cleaning up deploy artifacts on WikiOracle...")
    subprocess.run(
        ssh_cmd(os.path.expanduser(wo_key_file), wo_user, wo_host, WO_SSH_OPTS) + [
            f"rm -f {WO_EC2_TMP_KEY} {WO_DEPLOY_SCRIPT}"
        ],
        capture_output=True, text=True,
    )


def deploy_to_wikioracle(args, ec2_key_file, ec2_user, ec2_ip):
    """Have WikiOracle pull nanochat artifacts from EC2 via rsync.

    Stops the NanoChat service before rsync to avoid serving stale/partial
    model files, then restarts it after the transfer completes.
    """
    wo_key_file = os.path.expanduser(args.wo_key_file)
    wo_user = args.wo_user
    wo_host = args.wo_host
    wo_dest = args.wo_dest

    print(f"\n=== Deploying: WikiOracle pulling from EC2 ({ec2_ip}) ===")

    # 0. Stop NanoChat service before overwriting files
    print("Stopping NanoChat service on WikiOracle...")
    run(ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + [
        "sudo systemctl stop nanochat || true"
    ])

    # 1. Copy EC2 key to WikiOracle (temporary)
    print("Copying EC2 key to WikiOracle...")
    run(scp_cmd(wo_key_file, WO_SSH_OPTS) + [
        ec2_key_file,
        f"{wo_user}@{wo_host}:{WO_EC2_TMP_KEY}",
    ])
    run(ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + [
        f"chmod 600 {WO_EC2_TMP_KEY}"
    ])

    # 2. Write deploy script on WikiOracle
    # The deploy script SSHes from WikiOracle→EC2 (ephemeral), so it uses EC2_SSH_OPTS
    excludes = " ".join(f"--exclude='{e}'" for e in DEPLOY_RSYNC_EXCLUDES)
    ec2_ssh_opts_str = " ".join(EC2_SSH_OPTS)
    script = (
        "#!/bin/bash\n"
        "set -e\n"
        f"mkdir -p {wo_dest}\n"
        f"rsync -avz --delete {excludes} "
        f"-e 'ssh -i {WO_EC2_TMP_KEY} {ec2_ssh_opts_str}' "
        f"{ec2_user}@{ec2_ip}:~/WikiOracle/nanochat/ {wo_dest}/\n"
    )
    # Write script via heredoc over SSH
    run(ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + [
        f"cat > {WO_DEPLOY_SCRIPT} << 'DEPLOY_EOF'\n{script}DEPLOY_EOF\n"
        f"chmod +x {WO_DEPLOY_SCRIPT}"
    ])

    # 3. Execute deploy script
    print("Pulling artifacts from EC2 to WikiOracle...")
    run(ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + [WO_DEPLOY_SCRIPT])
    print("  Transfer complete.")

    # 4. Restart NanoChat service with the new model
    print("Restarting NanoChat service on WikiOracle...")
    run(ssh_cmd(wo_key_file, wo_user, wo_host, WO_SSH_OPTS) + [
        "sudo systemctl start nanochat"
    ])
    print("  NanoChat service started (model loading may take ~30-60s).")


def cmd_launch(args):
    key_file = os.path.expanduser(args.key_file)
    region = args.region

    # Pre-flight: validate WikiOracle connection before spending EC2 money
    wo_ip = None
    if getattr(args, "deploy", False):
        _, wo_ip = validate_wo_connection(args.wo_key_file, args.wo_user, args.wo_host, args.wo_dest)

    repo_dir = Path(__file__).parent
    launch_time = datetime.now(timezone.utc)

    print(f"=== Launching EC2 {args.instance_type} in {region} ===")

    # --- Key pair ---
    if not os.path.exists(key_file):
        print(f"Creating key pair '{args.key_name}'...")
        material = aws(
            "ec2", "create-key-pair",
            "--region", region,
            "--key-name", args.key_name,
            "--query", "KeyMaterial", "--output", "text",
        )
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        Path(key_file).write_text(material)
        os.chmod(key_file, 0o600)
    print(f"Key: {key_file}")

    # --- Security group (ensure current IP is allowed) ---
    sg_id = aws(
        "ec2", "describe-security-groups",
        "--region", region,
        "--filters", "Name=group-name,Values=nanochat-sg",
        "--query", "SecurityGroups[0].GroupId", "--output", "text",
    )
    if sg_id in ("None", ""):
        print("Creating security group 'nanochat-sg'...")
        sg_id = aws(
            "ec2", "create-security-group",
            "--region", region,
            "--group-name", "nanochat-sg",
            "--description", "NanoChat training SSH access",
            "--query", "GroupId", "--output", "text",
        )
    my_ip = run(["curl", "-s", "https://checkip.amazonaws.com"], capture=True)
    my_cidr = f"{my_ip}/32"
    # Check if current IP is already in the security group
    existing = aws(
        "ec2", "describe-security-groups",
        "--region", region,
        "--group-ids", sg_id,
        "--query", "SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp",
        "--output", "text",
    )
    if my_cidr not in existing.split():
        print(f"Adding current IP {my_ip} to security group...")
        aws(
            "ec2", "authorize-security-group-ingress",
            "--region", region,
            "--group-id", sg_id,
            "--protocol", "tcp", "--port", "22",
            "--cidr", my_cidr,
            capture=False,
        )
    print(f"Security group: {sg_id} (SSH from {my_ip})")

    # If deploying, also allow WikiOracle to SSH into EC2 for rsync
    if wo_ip:
        wo_cidr = f"{wo_ip}/32"
        if wo_cidr not in existing.split():
            print(f"Adding WikiOracle IP {wo_ip} to security group...")
            aws(
                "ec2", "authorize-security-group-ingress",
                "--region", region,
                "--group-id", sg_id,
                "--protocol", "tcp", "--port", "22",
                "--cidr", wo_cidr,
                capture=False,
            )
            print(f"  WikiOracle ({wo_ip}) allowed to SSH into EC2.")

    # --- AMI (AWS Deep Learning AMI with NVIDIA drivers + CUDA + PyTorch) ---
    ami_id = aws(
        "ec2", "describe-images",
        "--region", region,
        "--owners", "amazon",
        "--filters",
        "Name=name,Values=Deep Learning OSS Nvidia Driver AMI GPU PyTorch * (Ubuntu 22.04)*",
        "Name=state,Values=available",
        "--query", "sort_by(Images,&CreationDate)[-1].ImageId",
        "--output", "text",
    )
    print(f"AMI: {ami_id}")

    # --- Launch ---
    instance_id = aws(
        "ec2", "run-instances",
        "--region", region,
        "--image-id", ami_id,
        "--instance-type", args.instance_type,
        "--key-name", args.key_name,
        "--security-group-ids", sg_id,
        "--block-device-mappings",
        f"DeviceName=/dev/sda1,Ebs={{VolumeSize={args.disk_size},VolumeType=gp3}}",
        "--tag-specifications",
        "ResourceType=instance,Tags=[{Key=Name,Value=nanochat-training}]",
        "--query", "Instances[0].InstanceId", "--output", "text",
    )
    print(f"Instance: {instance_id}")
    write_state("instance-id", instance_id)

    # --- Wait for running ---
    print("Waiting for instance to start...")
    aws(
        "ec2", "wait", "instance-running",
        "--region", region,
        "--instance-ids", instance_id,
        capture=False,
    )
    ip = aws(
        "ec2", "describe-instances",
        "--region", region,
        "--instance-ids", instance_id,
        "--query", "Reservations[0].Instances[0].PublicIpAddress",
        "--output", "text",
    )
    write_state("instance-ip", ip)
    print(f"Public IP: {ip}")

    # --- Save run metadata ---
    meta = {
        "instance_id": instance_id,
        "instance_type": args.instance_type,
        "region": region,
        "ip": ip,
        "ami_id": ami_id,
        "launch_time": launch_time.isoformat(),
        "target": args.target,
        "nproc": args.nproc,
        "data_shards": args.data_shards,
        "disk_size_gb": args.disk_size,
    }
    write_run_meta(meta)

    # --- CloudWatch idle alarm (safety net if polling loop dies) ---
    if getattr(args, "alert_email", None):
        print("Setting up CloudWatch idle alarm...")
        aws("sns", "create-topic", "--name", "nanochat-idle",
            "--region", region, capture=False)
        topic_arn = aws(
            "sns", "list-topics", "--region", region,
            "--query", "Topics[?ends_with(TopicArn,'nanochat-idle')].TopicArn | [0]",
            "--output", "text",
        )
        aws("sns", "subscribe", "--topic-arn", topic_arn,
            "--protocol", "email", "--notification-endpoint", args.alert_email,
            "--region", region, capture=False)
        aws("cloudwatch", "put-metric-alarm",
            "--alarm-name", f"nanochat-idle-{instance_id}",
            "--namespace", "AWS/EC2",
            "--metric-name", "CPUUtilization",
            "--dimensions", f"Name=InstanceId,Value={instance_id}",
            "--statistic", "Average",
            "--period", "300",
            "--evaluation-periods", "6",
            "--threshold", "5",
            "--comparison-operator", "LessThanThreshold",
            "--alarm-actions", topic_arn,
            "--region", region,
            capture=False)
        print(f"  Alarm will email {args.alert_email} if CPU < 5% for 30 min.")

    # --- Wait for SSH ---
    wait_for_ssh(key_file, args.user, ip)

    # --- Clone repo ---
    print("\nCloning repository on remote...")
    subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [
            f"git clone --recursive {args.repo} ~/WikiOracle"
        ],
        check=True,
    )

    # --- Overlay local modifications ---
    # Find files that differ from HEAD (staged + unstaged + untracked)
    dirty_files = []
    # Modified/staged files
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    dirty_files.extend(r.stdout.strip().splitlines())
    # Staged but not yet in HEAD
    r = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    dirty_files.extend(r.stdout.strip().splitlines())
    # Untracked files (excluding .venv, __pycache__, .ec2)
    r = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    dirty_files.extend(r.stdout.strip().splitlines())
    # Deduplicate
    dirty_files = sorted(set(f for f in dirty_files if f))

    if dirty_files:
        print(f"\nOverlaying {len(dirty_files)} local modification(s)...")
        for f in dirty_files:
            print(f"  {f}")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write("\n".join(dirty_files) + "\n")
            filelist = tmp.name
        try:
            run([
                "rsync", "-avz", "--files-from", filelist,
                "-e", " ".join(["ssh", "-i", key_file] + EC2_SSH_OPTS),
                str(repo_dir) + "/", f"{args.user}@{ip}:~/WikiOracle/",
            ])
        finally:
            os.unlink(filelist)

    # --- Capture system info ---
    print("\nCapturing system info...")
    r = subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [
            "("
            " echo '=== uname ===' ; uname -a ;"
            " echo '=== nvidia-smi ===' ; nvidia-smi 2>/dev/null || echo 'not available' ;"
            " echo '=== GPU topology ===' ; nvidia-smi topo -m 2>/dev/null || echo 'not available' ;"
            " echo '=== CPU ===' ; lscpu | head -20 ;"
            " echo '=== Memory ===' ; free -h"
            ") > ~/sysinfo.txt 2>&1"
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  Warning: sysinfo capture returned exit {r.returncode}")

    # --- Start training ---
    # Records training start/end times and exit code into done.json.
    # The instance stays running so artifacts can be retrieved.
    print("\nStarting training in screen session...")
    make_cmd = (
        f"make {args.target}"
        f" NPROC={args.nproc}"
        f" WANDB_RUN={args.wandb_run}"
        f" DATA_SHARDS_FULL={args.data_shards}"
    )
    screen_cmd = (
        f"screen -dmS train bash -c '"
        f"set -o pipefail; "
        f"TRAIN_START=$(date -u +%Y-%m-%dT%H:%M:%SZ); "
        f"cd ~/WikiOracle && {make_cmd} 2>&1 | tee ~/train.log; "
        f"EXIT=$?; "
        f"echo \"{{\\\"exit_code\\\": $EXIT, "
        f"\\\"train_start\\\": \\\"$TRAIN_START\\\", "
        f"\\\"end_time\\\": \\\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\\\"}}\" > ~/done.json"
        f"'"
    )
    subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [screen_cmd],
        check=True,
    )

    print(f"""
=== Training launched on {instance_id} ({ip}) ===
Polling every 30s. Ctrl-C to detach (instance stays running).
If detached, use 'make remote-retrieve' to pull artifacts and terminate.
""")

    # --- Poll for completion, then auto-retrieve ---
    poll_interval = 30  # seconds — Nyquist on per-second billing
    try:
        while True:
            time.sleep(poll_interval)
            elapsed = datetime.now(timezone.utc) - launch_time
            elapsed_min = int(elapsed.total_seconds() / 60)
            cost_so_far = elapsed.total_seconds() / 3600 * INSTANCE_PRICING.get(args.instance_type, 0)

            # Quiet SSH check — no command echo
            try:
                r = subprocess.run(
                    ssh_cmd(key_file, args.user, ip) + ["cat ~/done.json 2>/dev/null || echo ''"],
                    capture_output=True, text=True,
                    timeout=60,
                )
                done_json = r.stdout.strip()
            except subprocess.TimeoutExpired:
                print(f"  [{elapsed_min} min, ~${cost_so_far:.2f}] SSH poll timed out, retrying...")
                continue

            if done_json:
                done_data = json.loads(done_json)
                code = done_data.get("exit_code", "?")
                status = "SUCCESS" if code == 0 else f"FAILED (exit {code})"
                print(f"\n=== Training finished: {status} ({elapsed_min} min, ~${cost_so_far:.2f}) ===")
                if getattr(args, "deploy", False):
                    print("Deploying to WikiOracle...")
                    cmd_deploy(args)
                else:
                    print("Retrieving artifacts...")
                    cmd_retrieve(args)
                return
            else:
                print(f"  [{elapsed_min} min, ~${cost_so_far:.2f}] still running...")
    except KeyboardInterrupt:
        print(f"\n\nDetached. Instance {instance_id} ({ip}) still running.")
        print("  make remote-status        # Check if done")
        if getattr(args, "deploy", False):
            print("  make remote-deploy        # Deploy to WikiOracle and terminate")
        else:
            print("  make remote-retrieve      # Pull artifacts and terminate")
        print("  make remote-logs          # Tail training log")


def generate_run_summary(meta, done_data, run_dir):
    """Compute timing/cost and write summary.md to run_dir."""
    exit_code = done_data.get("exit_code", -1)
    end_time_str = done_data.get("end_time", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    launch_time = datetime.fromisoformat(meta["launch_time"])

    end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

    total_duration = end_time - launch_time
    total_min = total_duration.total_seconds() / 60
    total_hr = total_duration.total_seconds() / 3600

    train_start_str = done_data.get("train_start")
    if train_start_str:
        train_start = datetime.fromisoformat(train_start_str.replace("Z", "+00:00"))
        train_duration = end_time - train_start
        train_min = train_duration.total_seconds() / 60
        train_hr = train_duration.total_seconds() / 3600
        train_time_str = f"{int(train_min)} min ({train_hr:.2f} hr)"
    else:
        train_time_str = "unknown"

    instance_type = meta.get("instance_type", "unknown")
    hourly_rate = INSTANCE_PRICING.get(instance_type, 0)
    cost = max(total_duration.total_seconds(), 60) / 3600 * hourly_rate

    status = "SUCCESS" if exit_code == 0 else "FAILED"

    sysinfo_path = run_dir / "sysinfo.txt"
    sysinfo = sysinfo_path.read_text() if sysinfo_path.exists() else "not captured"

    summary = f"""# Run Summary

## Status: {status}

## Instance
| Field | Value |
|-------|-------|
| Instance ID | `{meta.get('instance_id', 'unknown')}` |
| Instance Type | `{instance_type}` |
| Region | `{meta.get('region', 'unknown')}` |
| AMI | `{meta.get('ami_id', 'unknown')}` |
| Disk | {meta.get('disk_size_gb', '?')} GB |

## Run
| Field | Value |
|-------|-------|
| Target | `{meta.get('target', 'unknown')}` |
| GPUs (nproc) | {meta.get('nproc', '?')} |
| Data shards | {meta.get('data_shards', '?')} |
| Exit code | {exit_code} |

## Timing
| Field | Value |
|-------|-------|
| Instance launch | {launch_time.strftime('%Y-%m-%d %H:%M:%S UTC')} |
| Training start | {train_start_str or 'unknown'} |
| Training end | {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')} |
| Training wall clock | {train_time_str} |
| Total duration (incl. setup) | {int(total_min)} min ({total_hr:.2f} hr) |

## Cost
| Field | Value |
|-------|-------|
| Hourly rate | ${hourly_rate:.2f}/hr |
| Estimated cost | ${cost:.2f} |

## System Info
```
{sysinfo}
```

## Artifacts
"""
    for item in sorted(run_dir.iterdir()):
        if item.name == "summary.md":
            continue
        if item.is_dir():
            file_count = sum(1 for _ in item.rglob("*") if _.is_file())
            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            summary += f"- `{item.name}/` — {file_count} files, {dir_size / 1024 / 1024:.1f} MB\n"
        else:
            size = item.stat().st_size
            summary += f"- `{item.name}` — {size / 1024:.1f} KB\n"

    (run_dir / "summary.md").write_text(summary)
    print(f"\nSummary written to {run_dir / 'summary.md'}")


def cmd_retrieve(args):
    """Pull artifacts from remote, generate summary, terminate instance."""
    key_file = os.path.expanduser(args.key_file)
    ip = read_state("instance-ip")
    instance_id = read_state("instance-id")
    meta = read_run_meta()

    print(f"=== Retrieving artifacts from {instance_id} ({ip}) ===")

    # --- Check if training is done ---
    done_json = run(
        ssh_cmd(key_file, args.user, ip) + ["cat ~/done.json 2>/dev/null || echo ''"],
        capture=True, check=False,
    )

    if not done_json:
        # Check if screen session is still running
        screen_check = run(
            ssh_cmd(key_file, args.user, ip) + ["screen -ls train 2>/dev/null || true"],
            capture=True, check=False,
        )
        if "train" in screen_check:
            print("Training is still running. Use 'make remote-logs' to monitor.")
            print("Run 'make remote-retrieve' again after training completes.")
            sys.exit(1)
        else:
            print("Warning: No done.json found and no screen session running.")
            print("Training may have crashed. Retrieving what's available...")
            done_data = {"exit_code": -1, "end_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    else:
        done_data = json.loads(done_json)

    exit_code = done_data.get("exit_code", -1)
    end_time_str = done_data.get("end_time", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    # --- Create output directory ---
    launch_time = datetime.fromisoformat(meta["launch_time"])
    run_dir_name = launch_time.strftime("%Y-%m-%d-%H%M")
    run_dir = OUTPUT_DIR / run_dir_name

    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {run_dir}")

    # --- Check remote artifact sizes ---
    scp_base = scp_cmd(key_file)
    remote = f"{args.user}@{ip}"
    nanochat_base = "~/WikiOracle/nanochat"

    artifacts = [
        ("train.log",           "~/train.log",                          False),
        ("sysinfo.txt",         "~/sysinfo.txt",                        False),
        ("report.md",           f"{nanochat_base}/report/report.md",    False),
        ("report/",             f"{nanochat_base}/report/",             True),
        ("base_checkpoints/",   f"{nanochat_base}/base_checkpoints/",   True),
        ("chatsft_checkpoints/",f"{nanochat_base}/chatsft_checkpoints/",True),
        ("base_eval/",          f"{nanochat_base}/base_eval/",          True),
        ("tokenizer/",          f"{nanochat_base}/tokenizer/",          True),
    ]

    # Get sizes so we can warn about large transfers
    size_cmd = " ; ".join(
        f"du -sb {path.rstrip('/')} 2>/dev/null || echo '0 {path}'"
        for _, path, _ in artifacts
    )
    r = subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [size_cmd],
        capture_output=True, text=True,
    )
    remote_sizes = {}
    for line in r.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            remote_sizes[parts[1]] = int(parts[0])

    # --- SCP artifacts (skip >1GB with notice) ---
    skip_threshold = 1_000_000_000  # 1 GB
    for name, path, is_dir in artifacts:
        size = remote_sizes.get(path.rstrip("/"), 0)
        size_mb = size / 1024 / 1024
        if size > skip_threshold:
            print(f"Skipping {name} ({size_mb:.0f} MB) — use 'make remote-ssh' to retrieve manually")
            continue
        print(f"Retrieving {name} ({size_mb:.1f} MB)...")
        flags = ["-r"] if is_dir else []
        run(scp_base + flags + [f"{remote}:{path}", str(run_dir / name)], check=False)

    generate_run_summary(meta, done_data, run_dir)

    # --- Clean up CloudWatch alarm ---
    aws("cloudwatch", "delete-alarms",
        "--alarm-names", f"nanochat-idle-{instance_id}",
        "--region", meta.get("region", args.region),
        capture=False)

    # --- Terminate instance ---
    print(f"\nTerminating instance {instance_id}...")
    aws(
        "ec2", "terminate-instances",
        "--region", meta.get("region", args.region),
        "--instance-ids", instance_id,
        capture=False,
    )
    print(f"\n=== Done. Artifacts saved to {run_dir} ===")


def cmd_deploy(args):
    """Deploy nanochat artifacts from EC2 to WikiOracle, then terminate."""
    key_file = os.path.expanduser(args.key_file)
    ip = read_state("instance-ip")
    instance_id = read_state("instance-id")
    meta = read_run_meta()

    print(f"=== Deploying from {instance_id} ({ip}) to WikiOracle ===")

    # --- Check if training is done ---
    done_json = run(
        ssh_cmd(key_file, args.user, ip) + ["cat ~/done.json 2>/dev/null || echo ''"],
        capture=True, check=False,
    )

    if not done_json:
        screen_check = run(
            ssh_cmd(key_file, args.user, ip) + ["screen -ls train 2>/dev/null || true"],
            capture=True, check=False,
        )
        if "train" in screen_check:
            print("Training is still running. Use 'make remote-logs' to monitor.")
            print("Run 'make remote-deploy' again after training completes.")
            sys.exit(1)
        else:
            print("Warning: No done.json found and no screen session running.")
            print("Training may have crashed. Deploying what's available...")
            done_data = {"exit_code": -1, "end_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    else:
        done_data = json.loads(done_json)

    exit_code = done_data.get("exit_code", -1)
    if exit_code != 0:
        print(f"Warning: Training exited with code {exit_code}. Deploying anyway...")

    # --- Deploy: WikiOracle pulls from EC2 ---
    deploy_to_wikioracle(args, key_file, args.user, ip)

    # --- Retrieve logs and sysinfo before terminating ---
    launch_time = datetime.fromisoformat(meta["launch_time"])
    run_dir_name = launch_time.strftime("%Y-%m-%d-%H%M")
    run_dir = OUTPUT_DIR / run_dir_name
    run_dir.mkdir(parents=True, exist_ok=True)

    scp_base = scp_cmd(key_file)
    remote = f"{args.user}@{ip}"
    for name, path in [("train.log", "~/train.log"), ("sysinfo.txt", "~/sysinfo.txt")]:
        print(f"Retrieving {name}...")
        r = subprocess.run(
            scp_base + [f"{remote}:{path}", str(run_dir / name)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  Warning: could not retrieve {name}: {r.stderr.strip()}")

    generate_run_summary(meta, done_data, run_dir)

    # --- Terminate instance ---
    print(f"\nTerminating instance {instance_id}...")
    aws(
        "ec2", "terminate-instances",
        "--region", meta.get("region", args.region),
        "--instance-ids", instance_id,
        capture=False,
    )

    # --- Clean up CloudWatch alarm ---
    aws("cloudwatch", "delete-alarms",
        "--alarm-names", f"nanochat-idle-{instance_id}",
        "--region", meta.get("region", args.region),
        capture=False)

    # --- Cleanup WikiOracle (after EC2 is terminated) ---
    cleanup_wo_deploy(args.wo_key_file, args.wo_user, args.wo_host)

    print(f"\n=== Done. Deployed to {args.wo_host}:{args.wo_dest} ===")
    print(f"Summary saved to {run_dir / 'summary.md'}")


def cmd_ssh(args):
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    os.execvp("ssh", ssh_cmd(key_file, args.user, ip))


def cmd_logs(args):
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    os.execvp("ssh", ssh_cmd(key_file, args.user, ip) + ["tail", "-f", "~/train.log"])


STAGE_MARKERS = [
    ("scripts.base_eval",      "eval-base",  6),
    ("scripts.chat_eval",      "eval-chat",  7),
    ("scripts.chat_sft",       "sft",        5),
    ("scripts.base_train",     "pretrain",   4),
    ("tok_train",              "tokenizer",  3),
    ("nanochat.dataset",       "data",       2),
    ("nanochat.report",        "report",     8),
    ("uv sync",               "setup",      1),
]
TOTAL_STAGES = 8


def detect_stage(key_file, user, ip):
    """Detect the current training stage from the log file.

    Finds the last stage marker in the log (highest line number) to determine
    which stage is currently executing.
    """
    r = subprocess.run(
        ssh_cmd(key_file, user, ip) + [
            "grep -n 'scripts\\.base_eval\\|scripts\\.chat_eval\\|scripts\\.chat_sft\\|"
            "scripts\\.base_train\\|tok_train\\|nanochat\\.dataset\\|nanochat\\.report\\|"
            "uv sync' ~/train.log 2>/dev/null | tail -1"
        ],
        capture_output=True, text=True,
    )
    last_match = r.stdout.strip()
    if not last_match:
        return None, None

    # Match against known stage markers
    for marker_text, stage_name, stage_num in STAGE_MARKERS:
        if marker_text in last_match:
            return stage_name, stage_num

    return None, None


def cmd_status(args):
    instance_id = read_state("instance-id")
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    meta = read_run_meta()

    # Instance state (quiet — no command echo)
    r = subprocess.run(
        ["aws", "ec2", "describe-instances",
         "--region", args.region,
         "--instance-ids", instance_id,
         "--query", "Reservations[0].Instances[0].State.Name",
         "--output", "text"],
        capture_output=True, text=True,
    )
    state = r.stdout.strip()

    # Compute elapsed time and cost
    launch_time = datetime.fromisoformat(meta["launch_time"])
    elapsed = datetime.now(timezone.utc) - launch_time
    elapsed_min = int(elapsed.total_seconds() / 60)
    hourly_rate = INSTANCE_PRICING.get(meta.get("instance_type", ""), 0)
    cost = elapsed.total_seconds() / 3600 * hourly_rate

    print(f"Instance {instance_id}: {state}  [{elapsed_min} min, ~${cost:.2f}]")

    if state != "running":
        return

    # Check if training is done (quiet)
    r = subprocess.run(
        ssh_cmd(key_file, args.user, ip) +
        ["cat ~/done.json 2>/dev/null || echo ''"],
        capture_output=True, text=True,
    )
    done_json = r.stdout.strip()

    if done_json:
        done_data = json.loads(done_json)
        code = done_data.get("exit_code", "?")
        end = done_data.get("end_time", "?")
        status = "SUCCESS" if code == 0 else f"FAILED (exit {code})"
        print(f"Training: {status} at {end}")
        print("Run 'make remote-retrieve' to pull artifacts and terminate.")
    else:
        r = subprocess.run(
            ssh_cmd(key_file, args.user, ip) +
            ["screen -ls train 2>/dev/null || true"],
            capture_output=True, text=True,
        )
        if "train" in r.stdout:
            stage_name, stage_num = detect_stage(key_file, args.user, ip)
            if stage_name:
                print(f"Training: IN PROGRESS — stage {stage_num}/{TOTAL_STAGES} ({stage_name})")
            else:
                print("Training: IN PROGRESS")

            # Show last meaningful line (handle \r-overwritten lines)
            r = subprocess.run(
                ssh_cmd(key_file, args.user, ip) + [
                    "tail -3 ~/train.log 2>/dev/null | tr '\\r' '\\n' | grep -v '^$' | tail -10"
                ],
                capture_output=True, text=True,
            )
            tail_lines = r.stdout.strip().splitlines()
            if tail_lines:
                # Check if output is rank progress lines (e.g. "[KRank 2 | 0/76 (0.00%)")
                rank_pattern = re.compile(r'\[?K?Rank\s+\d+\s*\|\s*(\d+)/(\d+)')
                rank_matches = []
                for line in tail_lines:
                    m = rank_pattern.search(line)
                    if m:
                        rank_matches.append((int(m.group(1)), int(m.group(2))))

                if rank_matches:
                    # Summarize rank progress: show max progress across GPUs
                    max_total = max(t for _, t in rank_matches)
                    max_correct = max(c for c, _ in rank_matches)
                    print(f"  eval progress: ~{max_total} questions scored ({max_correct} correct)")
                else:
                    last_line = tail_lines[-1]
                    if len(last_line) > 120:
                        last_line = last_line[:117] + "..."
                    print(f"  {last_line}")
        else:
            print("Training: UNKNOWN (no screen session, no done.json)")


def _add_wo_args(parser):
    """Add WikiOracle deployment arguments to a parser."""
    parser.add_argument("--wo-key-file", default=WO_KEY_FILE_DEFAULT,
                        help="SSH key for WikiOracle (default: %(default)s)")
    parser.add_argument("--wo-user", default=WO_USER_DEFAULT,
                        help="WikiOracle SSH user (default: %(default)s)")
    parser.add_argument("--wo-host", default=WO_HOST_DEFAULT,
                        help="WikiOracle hostname (default: %(default)s)")
    parser.add_argument("--wo-dest", default=WO_DEST_DEFAULT,
                        help="WikiOracle destination path (default: %(default)s)")


def main():
    parser = argparse.ArgumentParser(description="EC2 remote training for NanoChat")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--key-name", default="nanochat-key")
    parser.add_argument("--key-file", default="~/.ssh/nanochat-key.pem")
    parser.add_argument("--user", default="ubuntu")

    sub = parser.add_subparsers(dest="command", required=True)

    p_launch = sub.add_parser("launch", help="Launch EC2 instance and start training")
    p_launch.add_argument("--instance-type", default="p4d.24xlarge")
    p_launch.add_argument("--disk-size", type=int, default=200)
    p_launch.add_argument("--nproc", type=int, default=8)
    p_launch.add_argument("--wandb-run", default="dummy")
    p_launch.add_argument("--data-shards", type=int, default=370)
    p_launch.add_argument("--target", default="all-gpu",
                          help="Makefile target to run on remote (default: all-gpu)")
    p_launch.add_argument("--repo",
                          default="https://github.com/arborrhythms/WikiOracle.git",
                          help="Git repo URL to clone on remote")
    p_launch.add_argument("--deploy", action="store_true",
                          help="Deploy to WikiOracle instead of retrieving locally")
    p_launch.add_argument("--alert-email", default=None,
                          help="Email for CloudWatch idle alarm (safety net if polling dies)")
    _add_wo_args(p_launch)

    sub.add_parser("retrieve", help="Pull artifacts, generate summary, terminate instance")

    p_deploy = sub.add_parser("deploy", help="Deploy artifacts from EC2 to WikiOracle, terminate")
    _add_wo_args(p_deploy)

    sub.add_parser("ssh", help="SSH into running instance")
    sub.add_parser("logs", help="Tail training log")
    sub.add_parser("status", help="Check instance state")

    args = parser.parse_args()

    commands = {
        "launch": cmd_launch,
        "retrieve": cmd_retrieve,
        "deploy": cmd_deploy,
        "ssh": cmd_ssh,
        "logs": cmd_logs,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
