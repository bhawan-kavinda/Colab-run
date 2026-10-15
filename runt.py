#!/usr/bin/env python3
"""
Termux -> OpenSSH + Cloudflare quick tunnel.
Usage (in Termux):
    python runt.py
"""

import getpass
import os
import re
import shutil
import subprocess
import sys
import time

# Termux has no /tmp, so use $PREFIX/tmp instead
PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
TMP_DIR = os.path.join(PREFIX, "tmp")
LOG_FILE = os.path.join(TMP_DIR, "cloudflared.log")

# Fallback binary (only used if `pkg install cloudflared` fails)
CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-arm64"
)
FALLBACK_BIN = os.path.expanduser("~/.local/bin/cloudflared")


def run(cmd, check=True):
    """Run a shell command silently."""
    return subprocess.run(
        cmd,
        shell=True,
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def find_cloudflared():
    """Return path to a usable cloudflared binary, or None."""
    path = shutil.which("cloudflared")
    if path:
        return path
    if os.path.exists(FALLBACK_BIN):
        return FALLBACK_BIN
    return None


def install_packages():
    print("[1/4] Checking and installing packages in Termux...")
    os.makedirs(TMP_DIR, exist_ok=True)
    subprocess.run("pkg update -y && pkg install -y openssh termux-services", shell=True)

    if find_cloudflared():
        print("[2/4] cloudflared already installed.")
        return

    print("[2/4] Installing cloudflared for Termux...")
    # Preferred: Termux's own package (works properly with Android DNS)
    subprocess.run("pkg install -y cloudflared", shell=True)
    if find_cloudflared():
        return

    # Fallback: download the official arm64 binary
    os.makedirs(os.path.dirname(FALLBACK_BIN), exist_ok=True)
    subprocess.run(f"curl -fsSL -o {FALLBACK_BIN} {CLOUDFLARED_URL}", shell=True)
    subprocess.run(f"chmod +x {FALLBACK_BIN}", shell=True)
    if not find_cloudflared():
        print("Could not install cloudflared.")
        sys.exit(1)


def set_password():
    """Ask the user to set the Termux login password (interactive)."""
    print("\nSet a password for SSH login (typing is hidden).")
    while True:
        result = subprocess.run(["passwd"])  # uses the terminal directly
        if result.returncode == 0:
            print("Password set.\n")
            return
        retry = input("Password was not set. Try again? [Y/n]: ").strip().lower()
        if retry == "n":
            print("Continuing without changing the password.\n")
            return


def configure_ssh():
    print("[3/4] Configuring SSH for Termux...")
    set_password()

    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    run(f"chmod 700 {ssh_dir}")

    # Kill any existing sshd
    run("pkill sshd", check=False)

    # Termux sshd listens on port 8022 by default
    print("Starting SSH server on Termux...")
    subprocess.Popen(["sshd"])
    time.sleep(1)


def start_tunnel():
    print("[4/4] Starting Cloudflare tunnel...")
    binary = find_cloudflared()
    os.makedirs(TMP_DIR, exist_ok=True)
    log = open(LOG_FILE, "w")
    proc = subprocess.Popen(
        [binary, "tunnel", "--url", "ssh://localhost:8022", "--no-autoupdate"],
        stdout=log,
        stderr=log,
    )

    pattern = re.compile(r"https://([a-z0-9-]+\.trycloudflare\.com)")
    for _ in range(60):
        time.sleep(1)
        if proc.poll() is not None:
            print("cloudflared exited unexpectedly. Log:")
            with open(LOG_FILE) as f:
                print(f.read())
            sys.exit(1)
        with open(LOG_FILE) as f:
            match = pattern.search(f.read())
        if match:
            return proc, match.group(1)

    print("Timed out waiting for tunnel URL.")
    proc.terminate()
    sys.exit(1)


def main():
    install_packages()
    configure_ssh()
    proc, host = start_tunnel()

    user = getpass.getuser()
    line = "=" * 56
    print(f"\n{line}")
    print(" READY - Connect from another device/PC")
    print(line)
    print("\n# Connect command:")
    print(
        f'ssh -p 8022 -o ProxyCommand="cloudflared access ssh --hostname {host}" '
        f"{user}@localhost"
    )
    print(f"\nHostname : {host}")
    print(f"Username : {user}")
    print("Password : the one you just entered")
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
