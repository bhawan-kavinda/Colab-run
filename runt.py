#!/usr/bin/env python3
"""
Termux -> OpenSSH + Cloudflare quick tunnel.
Usage (in Termux):
    python run.py
"""

import argparse
import os
import re
import secrets
import subprocess
import sys
import time

LOG_FILE = "/tmp/cloudflared.log"
# Termux uses aarch64 (ARM64) architecture typically
CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-arm64"
)
CLOUDFLARED_BIN = os.path.expanduser("~/.local/bin/cloudflared")


def run(cmd, check=True):
    """Run a shell command silently."""
    return subprocess.run(
        cmd,
        shell=True,
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install_packages():
    print("[1/4] Checking and installing packages in Termux...")
    # Update and install openssh and cloudflared via Termux pkg
    subprocess.run("pkg update -y && pkg install -y openssh termux-services", shell=True)
    
    os.makedirs(os.path.dirname(CLOUDFLARED_BIN), exist_ok=True)
    if not os.path.exists(CLOUDFLARED_BIN):
        print("[2/4] Installing cloudflared for Termux...")
        subprocess.run(f"curl -fsSL -o {CLOUDFLARED_BIN} {CLOUDFLARED_URL}", shell=True)
        subprocess.run(f"chmod +x {CLOUDFLARED_BIN}", shell=True)
    else:
        print("[2/4] cloudflared already installed.")


def configure_ssh(pubkey):
    print("[3/4] Configuring SSH for Termux...")
    password = secrets.token_urlsafe(12)

    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    run(f"chmod 700 {ssh_dir}")

    # Set password for current Termux user
    run(f"echo 'u0_a...:{password}' | passwd", check=False) # Termux handles user password differently, or we can use standard passwd
    
    # Kill any existing sshd
    run("pkill sshd", check=False)
    
    # Start Termux sshd (Termux openssh runs on port 8022 by default)
    print("Starting SSH server on Termux...")
    subprocess.Popen(["sshd"])
    
    return password


def start_tunnel():
    print("[4/4] Starting Cloudflare tunnel...")
    log = open(LOG_FILE, "w")
    # Termux sshd runs on port 8022 by default
    proc = subprocess.Popen(
        [CLOUDFLARED_BIN, "tunnel", "--url", "ssh://localhost:8022", "--no-autoupdate"],
        stdout=log,
        stderr=log,
    )

    pattern = re.compile(r"https://([a-z0-9-]+\.trycloudflare\.com)")
    for _ in range(60):
        time.sleep(1)
        if proc.poll() is not None:
            print("cloudflared exited unexpectedly. Log:")
            print(open(LOG_FILE).read())
            sys.exit(1)
        match = pattern.search(open(LOG_FILE).read())
        if match:
            return proc, match.group(1)

    print("Timed out waiting for tunnel URL.")
    proc.terminate()
    sys.exit(1)


def main():
    install_packages()
    password = configure_ssh("")
    proc, host = start_tunnel()

    line = "=" * 56
    print(f"\n{line}")
    print(" READY - Connect from another device/PC")
    print(line)
    print(f"\n# Connect command:")
    print(f'ssh -p 8022 -o ProxyCommand="cloudflared access ssh --hostname {host}" localhost')
    print(f"\nHostname : {host}")
    print(f"{line}\n")
    print("Keep this script running.")

    try:
        while True:
            time.sleep(30)
            if proc.poll() is not None:
                print("Tunnel stopped.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        run("pkill sshd", check=False)


if __name__ == "__main__":
    main()
