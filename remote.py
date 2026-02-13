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
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
]

# Hourly on-demand pricing (USD) for common GPU instance types
INSTANCE_PRICING = {
    "p4d.24xlarge": 32.77,
    "p4de.24xlarge": 40.97,
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


def ssh_cmd(key_file, user, ip):
    """Build base SSH command list."""
    return ["ssh", "-i", key_file] + SSH_OPTS + [f"{user}@{ip}"]


def scp_cmd(key_file):
    """Build base SCP command prefix."""
    return ["scp", "-i", key_file] + SSH_OPTS


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


def cmd_launch(args):
    key_file = os.path.expanduser(args.key_file)
    region = args.region

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
                "-e", " ".join(["ssh", "-i", key_file] + SSH_OPTS),
                str(repo_dir) + "/", f"{args.user}@{ip}:~/WikiOracle/",
            ])
        finally:
            os.unlink(filelist)

    # --- Capture system info ---
    print("\nCapturing system info...")
    subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [
            "{"
            " echo '=== uname ===' && uname -a;"
            " echo '=== nvidia-smi ===' && nvidia-smi;"
            " echo '=== GPU topology ===' && nvidia-smi topo -m;"
            " echo '=== CPU ===' && lscpu | head -20;"
            " echo '=== Memory ===' && free -h;"
            "} > ~/sysinfo.txt 2>&1"
        ],
        check=False,
    )

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
            r = subprocess.run(
                ssh_cmd(key_file, args.user, ip) + ["cat ~/done.json 2>/dev/null || echo ''"],
                capture_output=True, text=True,
            )
            done_json = r.stdout.strip()

            if done_json:
                done_data = json.loads(done_json)
                code = done_data.get("exit_code", "?")
                status = "SUCCESS" if code == 0 else f"FAILED (exit {code})"
                print(f"\n=== Training finished: {status} ({elapsed_min} min, ~${cost_so_far:.2f}) ===")
                print("Retrieving artifacts...")
                cmd_retrieve(args)
                return
            else:
                print(f"  [{elapsed_min} min, ~${cost_so_far:.2f}] still running...")
    except KeyboardInterrupt:
        print(f"\n\nDetached. Instance {instance_id} ({ip}) still running.")
        print("  make remote-status        # Check if done")
        print("  make remote-retrieve      # Pull artifacts and terminate")
        print("  make remote-logs          # Tail training log")


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

    # --- SCP artifacts ---
    scp_base = scp_cmd(key_file)
    remote = f"{args.user}@{ip}"
    nanochat_base = "~/WikiOracle/nanochat"

    artifacts = [
        ("train.log",           f"{remote}:~/train.log",                          False),
        ("sysinfo.txt",         f"{remote}:~/sysinfo.txt",                        False),
        ("report.md",           f"{remote}:{nanochat_base}/report/report.md",     False),
        ("report/",             f"{remote}:{nanochat_base}/report/",              True),
        ("base_checkpoints/",   f"{remote}:{nanochat_base}/base_checkpoints/",    True),
        ("chatsft_checkpoints/",f"{remote}:{nanochat_base}/chatsft_checkpoints/", True),
        ("base_eval/",          f"{remote}:{nanochat_base}/base_eval/",           True),
        ("tokenizer/",          f"{remote}:{nanochat_base}/tokenizer/",           True),
    ]
    for name, src, is_dir in artifacts:
        print(f"Retrieving {name}...")
        flags = ["-r"] if is_dir else []
        run(scp_base + flags + [src, str(run_dir / name)], check=False)

    # --- Compute timing and cost ---
    end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

    # Total duration: launch to end (includes setup, data download, training)
    total_duration = end_time - launch_time
    total_min = total_duration.total_seconds() / 60
    total_hr = total_duration.total_seconds() / 3600

    # Training wall clock: from when make started to when it finished
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
    # EC2 bills per-second, minimum 60s
    cost = max(total_duration.total_seconds(), 60) / 3600 * hourly_rate

    status = "SUCCESS" if exit_code == 0 else "FAILED"

    # --- Read system info ---
    sysinfo_path = run_dir / "sysinfo.txt"
    sysinfo = sysinfo_path.read_text() if sysinfo_path.exists() else "not captured"

    # --- Generate summary.md ---
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
    # List what we actually retrieved
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

    # --- Terminate instance ---
    print(f"\nTerminating instance {instance_id}...")
    aws(
        "ec2", "terminate-instances",
        "--region", meta.get("region", args.region),
        "--instance-ids", instance_id,
        capture=False,
    )
    print(f"\n=== Done. Artifacts saved to {run_dir} ===")


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

    sub.add_parser("retrieve", help="Pull artifacts, generate summary, terminate instance")
    sub.add_parser("ssh", help="SSH into running instance")
    sub.add_parser("logs", help="Tail training log")
    sub.add_parser("status", help="Check instance state")

    args = parser.parse_args()

    commands = {
        "launch": cmd_launch,
        "retrieve": cmd_retrieve,
        "ssh": cmd_ssh,
        "logs": cmd_logs,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
