#!/usr/bin/env python3
"""Launch an EC2 instance, clone the repo, and run NanoChat GPU training.

The remote instance clones from GitHub, so commit and push before launching.

Usage:
    python remote.py launch [--instance-type=p4d.24xlarge] [--region=us-west-2] ...
    python remote.py ssh
    python remote.py logs
    python remote.py status
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE_DIR = Path(__file__).parent / ".ec2"
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
]


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


def read_state(name):
    """Read a value from the state directory."""
    path = STATE_DIR / name
    if not path.exists():
        print(f"Error: {path} not found. Run 'python remote.py launch' first.")
        sys.exit(1)
    return path.read_text().strip()


def write_state(name, value):
    """Write a value to the state directory."""
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / name).write_text(value + "\n")


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

    # --- Check for uncommitted changes ---
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True,
        cwd=Path(__file__).parent,
    )
    dirty = [l for l in r.stdout.strip().splitlines() if not l.startswith("??")]
    if dirty:
        print("Warning: uncommitted changes won't be on the remote instance.")
        print("  (Remote clones from GitHub — commit and push first.)")
        print()

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

    # --- Security group ---
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
        aws(
            "ec2", "authorize-security-group-ingress",
            "--region", region,
            "--group-id", sg_id,
            "--protocol", "tcp", "--port", "22",
            "--cidr", f"{my_ip}/32",
            capture=False,
        )
    print(f"Security group: {sg_id}")

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
        "--instance-initiated-shutdown-behavior", "terminate",
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

    # --- Start training ---
    print("\nStarting training in screen session...")
    make_cmd = (
        f"make {args.target}"
        f" NPROC={args.nproc}"
        f" WANDB_RUN={args.wandb_run}"
        f" DATA_SHARDS_FULL={args.data_shards}"
    )
    screen_cmd = (
        f"screen -dmS train bash -c "
        f"'cd ~/WikiOracle && {make_cmd} 2>&1 | tee ~/train.log; sudo shutdown -h now'"
    )
    subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [screen_cmd],
        check=True,
    )

    print(f"""
=== Training launched on {instance_id} ({ip}) ===
Instance will auto-terminate when training completes.

Monitor:
  python remote.py ssh          # SSH into instance
  python remote.py logs         # Tail training log
  python remote.py status       # Check instance state

  -- or via make --
  make remote-ssh
  make remote-logs
  make remote-status
""")


def cmd_ssh(args):
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    os.execvp("ssh", ssh_cmd(key_file, args.user, ip))


def cmd_logs(args):
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    os.execvp("ssh", ssh_cmd(key_file, args.user, ip) + ["tail", "-f", "~/train.log"])


def cmd_status(args):
    instance_id = read_state("instance-id")
    aws(
        "ec2", "describe-instances",
        "--region", args.region,
        "--instance-ids", instance_id,
        "--query", "Reservations[0].Instances[0].[InstanceId,State.Name,PublicIpAddress]",
        "--output", "table",
        capture=False,
    )


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

    sub.add_parser("ssh", help="SSH into running instance")
    sub.add_parser("logs", help="Tail training log")
    sub.add_parser("status", help="Check instance state")

    args = parser.parse_args()

    commands = {
        "launch": cmd_launch,
        "ssh": cmd_ssh,
        "logs": cmd_logs,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
