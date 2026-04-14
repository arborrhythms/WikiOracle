#!/usr/bin/env python3
"""Launch a remote GPU instance, clone the repo, and run NanoChat training.

Supports Lambda Labs (default) and AWS EC2 as cloud providers.
Clones from GitHub, then rsyncs any local modifications on top.
After training completes, retrieve artifacts with the 'retrieve' subcommand.

Usage:
    python bin/remote.py launch [--provider=lambda] [--instance-type=gpu_1x_h100_sxm5] ...
    python bin/remote.py launch --provider=ec2 [--instance-type=p4d.24xlarge] ...
    python bin/remote.py retrieve   # Pull artifacts, generate summary, terminate
    python bin/remote.py ssh
    python bin/remote.py logs
    python bin/remote.py status
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).parent / ".remote"  # Local metadata/cache for the active run.
_LEGACY_STATE_DIR = Path(__file__).parent / ".ec2"
if not STATE_DIR.exists() and _LEGACY_STATE_DIR.exists():
    STATE_DIR = _LEGACY_STATE_DIR
OUTPUT_DIR = Path(__file__).parent / "output"  # Retrieved artifacts and generated run summaries.

# Remote instances are ephemeral — new host key each launch, IPs get recycled.
# Strict host-key checking would break every run; PEM auth is the real security.
REMOTE_SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=10",
]
EC2_SSH_OPTS = REMOTE_SSH_OPTS  # backward compat alias

# WikiOracle is a long-lived server — use normal host-key checking.
WO_SSH_OPTS = [
    "-o", "ConnectTimeout=10",
]

# WikiOracle (Lightsail) deployment defaults
WO_KEY_FILE_DEFAULT = "~/.ssh/wikiOracle.pem"
WO_USER_DEFAULT = "bitnami"
WO_HOST_DEFAULT = "wikiOracle.org"
WO_DEST_DEFAULT = "/opt/bitnami/wordpress/files/WikiOracle.org/client"
WO_DEPLOY_SCRIPT = "/opt/bitnami/wordpress/files/WikiOracle.org/deploy.sh"
WO_EC2_TMP_KEY = "/tmp/ec2.pem"

DEPLOY_RSYNC_EXCLUDES = [
    ".venv/", "__pycache__/", "*.pyc", "base_data/", "dev/",
    "dev-ignore/", "wandb/", ".env", "eval_bundle/",
    "identity_conversations.jsonl", "words_alpha.txt",
    ".git",
]

# Hourly on-demand pricing (USD) — EC2 (static), Lambda (fallback if API unreachable)
EC2_PRICING = {
    "p4d.24xlarge": 32.77,
    "p4de.24xlarge": 40.97,
    "p5.4xlarge": 6.88,
    "p5.48xlarge": 98.32,
    "g5.xlarge": 1.006,
    "g5.48xlarge": 16.288,
}
INSTANCE_PRICING = EC2_PRICING  # backward compat alias

LAMBDA_PRICING_FALLBACK = {
    "gpu_1x_a10": 1.29,
    "gpu_1x_a100_sxm4": 1.99,
    "gpu_1x_gh200": 2.29,
    "gpu_1x_h100_pcie": 3.29,
    "gpu_1x_h100_sxm5": 4.29,
    "gpu_1x_b200_sxm6": 6.99,
    "gpu_8x_a100": 15.92,
    "gpu_8x_a100_80gb_sxm4": 22.32,
    "gpu_8x_h100_sxm5": 31.92,
    "gpu_8x_b200_sxm6": 53.52,
}

LAMBDA_API_BASE = "https://cloud.lambdalabs.com/api/v1"


# --- Lambda Labs API client ---------------------------------------------------

def lambda_api_key():
    """Return the Lambda API key from environment, or exit with a message."""
    key = os.environ.get("LAMBDA_API_KEY")
    if not key:
        sys.exit("Error: LAMBDA_API_KEY not set. Export your Lambda Labs API key.")
    return key


def lambda_api(method, endpoint, json_data=None):
    """Call the Lambda Labs API. Returns parsed JSON response."""
    url = f"{LAMBDA_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {lambda_api_key()}",
        "Content-Type": "application/json",
    }
    body = json.dumps(json_data).encode() if json_data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        try:
            err_data = json.loads(err_body)
            msg = err_data.get("error", {}).get("message", err_body)
        except (json.JSONDecodeError, AttributeError):
            msg = err_body
        sys.exit(f"Lambda API error ({e.code}): {msg}")


def lambda_get_instance_types():
    """GET /instance-types — returns {name: {instance_type, regions_with_capacity_available}}."""
    return lambda_api("GET", "/instance-types").get("data", {})


def lambda_launch(instance_type, region, ssh_key_names):
    """POST /instance-operations/launch — returns list of instance IDs."""
    data = {
        "region_name": region,
        "instance_type_name": instance_type,
        "ssh_key_names": ssh_key_names,
        "quantity": 1,
    }
    resp = lambda_api("POST", "/instance-operations/launch", data)
    return resp.get("data", {}).get("instance_ids", [])


def lambda_get_instance(instance_id):
    """GET /instances/{id} — returns instance dict with status, ip, etc."""
    return lambda_api("GET", f"/instances/{instance_id}").get("data", {})


def lambda_terminate(instance_ids):
    """POST /instance-operations/terminate — terminate instance(s)."""
    return lambda_api("POST", "/instance-operations/terminate",
                      {"instance_ids": instance_ids})


def lambda_list_ssh_keys():
    """GET /ssh-keys — returns list of {id, name, public_key} dicts."""
    return lambda_api("GET", "/ssh-keys").get("data", [])


# --- Provider operations ------------------------------------------------------
# Each provider implements: ensure_ssh_key, launch_instance, terminate_instance,
# get_instance_state, setup_monitoring, cleanup_monitoring, get_pricing.


def lambda_ensure_ssh_key(args):
    """Verify the Lambda PEM key file exists. Return expanded path."""
    key_file = os.path.expanduser(args.key_file)
    if not os.path.exists(key_file):
        sys.exit(f"Error: Lambda key file not found: {key_file}")
    # Verify at least one SSH key is registered with Lambda
    keys = lambda_list_ssh_keys()
    if not keys:
        sys.exit("Error: No SSH keys registered with Lambda Labs. "
                 "Add one at https://cloud.lambdalabs.com/ssh-keys")
    print(f"Key: {key_file} (Lambda SSH keys: {', '.join(k['name'] for k in keys)})")
    return key_file, [k["name"] for k in keys]


def lambda_launch_instance(args, ssh_key_names):
    """Launch a Lambda instance. Returns (instance_id, ip)."""
    instance_type = args.instance_type
    region = args.region

    # Check availability before launching
    types = lambda_get_instance_types()
    type_info = types.get(instance_type)
    if not type_info:
        available = ", ".join(sorted(types.keys()))
        sys.exit(f"Error: Unknown instance type '{instance_type}'. Available: {available}")

    avail_regions = type_info.get("regions_with_capacity_available", [])
    region_names = [r["name"] for r in avail_regions]

    if region and region not in region_names:
        if region_names:
            print(f"Warning: {instance_type} not available in {region}. "
                  f"Available in: {', '.join(region_names)}")
            region = region_names[0]
            print(f"  Using {region} instead.")
        else:
            sys.exit(f"Error: {instance_type} has no capacity in any region. "
                     f"Retry with REMOTE_PROVIDER=ec2.")

    if not region:
        if region_names:
            region = region_names[0]
            print(f"  Auto-selected region: {region}")
        else:
            sys.exit(f"Error: {instance_type} has no capacity. Retry with REMOTE_PROVIDER=ec2.")

    print(f"Launching {instance_type} in {region}...")
    instance_ids = lambda_launch(instance_type, region, ssh_key_names)
    if not instance_ids:
        sys.exit("Error: Lambda launch returned no instance IDs.")
    instance_id = instance_ids[0]
    print(f"Instance: {instance_id}")

    # Poll until active
    print("Waiting for instance to become active...")
    for _ in range(60):
        info = lambda_get_instance(instance_id)
        status = info.get("status")
        ip = info.get("ip")
        if status == "active" and ip:
            print(f"  Instance active. IP: {ip}")
            return instance_id, ip, region
        if status in ("terminated", "error"):
            sys.exit(f"Error: Instance entered '{status}' state.")
        time.sleep(10)
    sys.exit("Error: Instance did not become active within 10 minutes.")


def lambda_terminate_instance(args, instance_id, region):
    """Terminate a Lambda instance."""
    print(f"Terminating Lambda instance {instance_id}...")
    lambda_terminate([instance_id])


def lambda_get_instance_state(args, instance_id):
    """Get Lambda instance status string."""
    try:
        info = lambda_get_instance(instance_id)
        return info.get("status", "unknown")
    except SystemExit:
        return "terminated"


def lambda_setup_monitoring(args, instance_id, region):
    """Lambda has no CloudWatch equivalent — no-op."""
    print("Note: Lambda Labs does not support idle alarms. Polling loop will track costs.")


def lambda_cleanup_monitoring(args, instance_id, region):
    """No-op for Lambda."""
    pass


def lambda_get_pricing(args):
    """Get hourly rate for a Lambda instance type."""
    try:
        types = lambda_get_instance_types()
        type_info = types.get(args.instance_type, {})
        cents = type_info.get("instance_type", {}).get("price_cents_per_hour", 0)
        if cents:
            return cents / 100
    except SystemExit:
        pass
    return LAMBDA_PRICING_FALLBACK.get(args.instance_type, 0)


def ec2_ensure_ssh_key(args):
    """Create EC2 key pair if PEM file doesn't exist. Return expanded path."""
    key_file = os.path.expanduser(args.key_file)
    region = args.region
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
    return key_file, None  # EC2 doesn't need ssh_key_names


def ec2_launch_instance(args, _ssh_key_names):
    """Launch an EC2 instance. Returns (instance_id, ip, region)."""
    key_file = os.path.expanduser(args.key_file)
    region = args.region

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
    wo_ip = getattr(args, "_wo_ip", None)
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

    # --- AMI ---
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
    print(f"Public IP: {ip}")
    return instance_id, ip, region


def ec2_terminate_instance(args, instance_id, region):
    """Terminate an EC2 instance."""
    print(f"Terminating instance {instance_id}...")
    aws(
        "ec2", "terminate-instances",
        "--region", region,
        "--instance-ids", instance_id,
        capture=False,
    )


def ec2_get_instance_state(args, instance_id):
    """Get EC2 instance state string."""
    r = subprocess.run(
        ["aws", "ec2", "describe-instances",
         "--region", args.region,
         "--instance-ids", instance_id,
         "--query", "Reservations[0].Instances[0].State.Name",
         "--output", "text"],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def ec2_setup_monitoring(args, instance_id, region):
    """Set up CloudWatch idle alarm for EC2."""
    if not getattr(args, "alert_email", None):
        return
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


def ec2_cleanup_monitoring(args, instance_id, region):
    """Delete CloudWatch idle alarm for EC2."""
    aws("cloudwatch", "delete-alarms",
        "--alarm-names", f"nanochat-idle-{instance_id}",
        "--region", region,
        capture=False)


def ec2_get_pricing(args):
    """Get hourly rate for an EC2 instance type."""
    return EC2_PRICING.get(args.instance_type, 0)


# --- Provider dispatch --------------------------------------------------------

PROVIDERS = {
    "lambda": {
        "ensure_ssh_key": lambda_ensure_ssh_key,
        "launch_instance": lambda_launch_instance,
        "terminate_instance": lambda_terminate_instance,
        "get_instance_state": lambda_get_instance_state,
        "setup_monitoring": lambda_setup_monitoring,
        "cleanup_monitoring": lambda_cleanup_monitoring,
        "get_pricing": lambda_get_pricing,
    },
    "ec2": {
        "ensure_ssh_key": ec2_ensure_ssh_key,
        "launch_instance": ec2_launch_instance,
        "terminate_instance": ec2_terminate_instance,
        "get_instance_state": ec2_get_instance_state,
        "setup_monitoring": ec2_setup_monitoring,
        "cleanup_monitoring": ec2_cleanup_monitoring,
        "get_pricing": ec2_get_pricing,
    },
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
        print(f"Error: {path} not found. Run 'python bin/remote.py launch' first.")
        sys.exit(1)
    return path.read_text().strip()


def read_run_meta():
    """Read run metadata from state directory."""
    path = STATE_DIR / "run-meta.json"
    if not path.exists():
        print(f"Error: {path} not found. Run 'python bin/remote.py launch' first.")
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
    """Launch remote training, monitor progress, then retrieve/deploy artifacts."""
    provider = PROVIDERS[args.provider]

    # Pre-flight: validate WikiOracle connection before spending money
    wo_ip = None
    if getattr(args, "deploy", False):
        _, wo_ip = validate_wo_connection(args.wo_key_file, args.wo_user, args.wo_host, args.wo_dest)
        args._wo_ip = wo_ip  # pass to ec2_launch_instance for security group

    repo_dir = Path(__file__).parent
    launch_time = datetime.now(timezone.utc)

    print(f"=== Launching {args.provider} {args.instance_type} ===")

    # --- Provider-specific: SSH key ---
    key_file, ssh_key_names = provider["ensure_ssh_key"](args)

    # --- Provider-specific: Launch instance ---
    instance_id, ip, region = provider["launch_instance"](args, ssh_key_names)

    # --- Save state ---
    write_state("instance-id", instance_id)
    write_state("instance-ip", ip)

    hourly_rate = provider["get_pricing"](args)
    meta = {
        "provider": args.provider,
        "instance_id": instance_id,
        "instance_type": args.instance_type,
        "region": region,
        "ip": ip,
        "launch_time": launch_time.isoformat(),
        "target": args.target,
        "nproc": args.nproc,
        "data_shards": args.data_shards,
        "hourly_rate": hourly_rate,
    }
    if args.provider == "ec2":
        meta["disk_size_gb"] = args.disk_size
    write_run_meta(meta)

    # --- Provider-specific: monitoring ---
    provider["setup_monitoring"](args, instance_id, region)

    # --- Wait for SSH ---
    wait_for_ssh(key_file, args.user, ip)

    # --- Ensure screen is installed (Lambda images may lack it) ---
    subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [
            "which screen > /dev/null 2>&1 || sudo apt-get install -y screen"
        ],
        capture_output=True,
    )

    # --- Clone repo ---
    print("\nCloning repository on remote...")
    subprocess.run(
        ssh_cmd(key_file, args.user, ip) + [
            f"git clone --recursive {args.repo} ~/WikiOracle"
        ],
        check=True,
    )

    # --- Overlay local modifications ---
    dirty_files = []
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    dirty_files.extend(r.stdout.strip().splitlines())
    r = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    dirty_files.extend(r.stdout.strip().splitlines())
    r = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=repo_dir,
    )
    dirty_files.extend(r.stdout.strip().splitlines())
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
                "-e", " ".join(["ssh", "-i", key_file] + REMOTE_SSH_OPTS),
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
If detached, use 'make train_retrieve' to pull artifacts and terminate.
""")

    # --- Poll for completion, then auto-retrieve ---
    poll_interval = 30
    try:
        while True:
            time.sleep(poll_interval)
            elapsed = datetime.now(timezone.utc) - launch_time
            elapsed_min = int(elapsed.total_seconds() / 60)
            cost_so_far = elapsed.total_seconds() / 3600 * hourly_rate

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
        print("  make train_status         # Check if done")
        if getattr(args, "deploy", False):
            print("  make train_deploy         # Deploy to WikiOracle and terminate")
        else:
            print("  make train_retrieve       # Pull artifacts and terminate")
        print("  make train_logs           # Tail training log")


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
    hourly_rate = meta.get("hourly_rate", EC2_PRICING.get(instance_type, 0))
    cost = max(total_duration.total_seconds(), 60) / 3600 * hourly_rate
    prov_name = meta.get("provider", "ec2")

    status = "SUCCESS" if exit_code == 0 else "FAILED"

    sysinfo_path = run_dir / "sysinfo.txt"
    sysinfo = sysinfo_path.read_text() if sysinfo_path.exists() else "not captured"

    # Provider-aware instance info
    instance_rows = (
        f"| Provider | `{prov_name}` |\n"
        f"| Instance ID | `{meta.get('instance_id', 'unknown')}` |\n"
        f"| Instance Type | `{instance_type}` |\n"
        f"| Region | `{meta.get('region', 'unknown')}` |\n"
    )
    if prov_name == "ec2":
        instance_rows += f"| AMI | `{meta.get('ami_id', 'unknown')}` |\n"
        instance_rows += f"| Disk | {meta.get('disk_size_gb', '?')} GB |\n"

    summary = f"""# Run Summary

## Status: {status}

## Instance
| Field | Value |
|-------|-------|
{instance_rows}

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
            print("Training is still running. Use 'make train_logs HOST=build' to monitor.")
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

    # --- Clean up monitoring + terminate (provider-specific) ---
    prov_name = meta.get("provider", "ec2")
    provider = PROVIDERS[prov_name]
    region = meta.get("region", getattr(args, "region", ""))
    provider["cleanup_monitoring"](args, instance_id, region)
    provider["terminate_instance"](args, instance_id, region)
    print(f"\n=== Done. Artifacts saved to {run_dir} ===")


def cmd_deploy(args):
    """Deploy nanochat artifacts from remote to WikiOracle, then terminate."""
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
            print("Training is still running. Use 'make train_logs HOST=build' to monitor.")
            print("Run 'make sync HOST=build' again after training completes.")
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

    # --- Terminate + cleanup (provider-specific) ---
    prov_name = meta.get("provider", "ec2")
    provider = PROVIDERS[prov_name]
    region = meta.get("region", getattr(args, "region", ""))
    provider["terminate_instance"](args, instance_id, region)
    provider["cleanup_monitoring"](args, instance_id, region)

    # --- Cleanup WikiOracle ---
    cleanup_wo_deploy(args.wo_key_file, args.wo_user, args.wo_host)

    print(f"\n=== Done. Deployed to {args.wo_host}:{args.wo_dest} ===")
    print(f"Summary saved to {run_dir / 'summary.md'}")


def cmd_ssh(args):
    """Replace current process with an interactive SSH session to the instance."""
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    os.execvp("ssh", ssh_cmd(key_file, args.user, ip))


def cmd_logs(args):
    """Replace current process with remote tail -f of the training log."""
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
    """Print current instance/training status and a coarse progress estimate."""
    instance_id = read_state("instance-id")
    ip = read_state("instance-ip")
    key_file = os.path.expanduser(args.key_file)
    meta = read_run_meta()

    # Instance state via provider dispatch
    prov_name = meta.get("provider", "ec2")
    provider = PROVIDERS[prov_name]
    state = provider["get_instance_state"](args, instance_id)

    # Compute elapsed time and cost
    launch_time = datetime.fromisoformat(meta["launch_time"])
    elapsed = datetime.now(timezone.utc) - launch_time
    elapsed_min = int(elapsed.total_seconds() / 60)
    hourly_rate = meta.get("hourly_rate", 0)
    cost = elapsed.total_seconds() / 3600 * hourly_rate

    # Normalize state for display (Lambda: "active", EC2: "running")
    running_states = ("running", "active")
    print(f"Instance {instance_id}: {state}  [{elapsed_min} min, ~${cost:.2f}]")

    if state not in running_states:
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
        print("Run 'make train_retrieve' to pull artifacts and terminate.")
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
                rank_pattern = re.compile(r'\[?K?Rank\s+\d+\s*\|\s*(\d+)/(\d+)')
                rank_matches = []
                for line in tail_lines:
                    m = rank_pattern.search(line)
                    if m:
                        rank_matches.append((int(m.group(1)), int(m.group(2))))

                if rank_matches:
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
    """Parse CLI args and dispatch to the selected remote workflow command."""
    parser = argparse.ArgumentParser(description="Remote GPU training for NanoChat")
    parser.add_argument("--provider", default="lambda", choices=["lambda", "ec2"],
                        help="Cloud provider (default: lambda)")
    parser.add_argument("--region", default="")
    parser.add_argument("--key-name", default="nanochat-key")
    parser.add_argument("--key-file", default="~/bin/lambda.pem")
    parser.add_argument("--user", default="ubuntu")

    sub = parser.add_subparsers(dest="command", required=True)

    p_launch = sub.add_parser("launch", help="Launch instance and start training")
    p_launch.add_argument("--instance-type", default="gpu_1x_h100_sxm5")
    p_launch.add_argument("--disk-size", type=int, default=200,
                          help="Disk size in GB (EC2 only)")
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
                          help="Email for CloudWatch idle alarm (EC2 only)")
    _add_wo_args(p_launch)

    sub.add_parser("retrieve", help="Pull artifacts, generate summary, terminate instance")

    p_deploy = sub.add_parser("deploy", help="Deploy artifacts to WikiOracle, terminate")
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
