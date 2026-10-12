#!/usr/bin/env python3
"""
Colab -> OpenSSH + Cloudflare quick tunnel.
Usage (in Colab):
    !git clone https://github.com/YOUR_USER/YOUR_REPO.git
    %cd YOUR_REPO
    !python run.py
Optional: add your public key for key-based login:
    !python run.py --pubkey "ssh-ed25519 AAAA... you@termux"
"""

import argparse
import os
import re
import secrets
import subprocess
import sys
import time

LOG_FILE = "/tmp/cloudflared.log"
CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64"
)
CLOUDFLARED_BIN = "/usr/local/bin/cloudflared"


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
    print("[1/4] Installing OpenSSH server...")
    run("apt-get update -y", check=False)
    run("DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server")

    if not os.path.exists(CLOUDFLARED_BIN):
        print("[2/4] Installing cloudflared...")
        run(f"curl -fsSL -o {CLOUDFLARED_BIN} {CLOUDFLARED_URL}")
        run(f"chmod +x {CLOUDFLARED_BIN}")
    else:
        print("[2/4] cloudflared already installed.")


def configure_ssh(pubkey):
    print("[3/4] Configuring SSH...")
    password = secrets.token_urlsafe(12)

    run("mkdir -p /run/sshd /root/.ssh")
    run("chmod 700 /root/.ssh")
    run(f"echo 'root:{password}' | chpasswd")

    config = (
        "Port 22\n"
        "ListenAddress 127.0.0.1\n"  # only reachable through the tunnel
        "PermitRootLogin yes\n"
        "PasswordAuthentication yes\n"
        "PubkeyAuthentication yes\n"
        "UsePAM yes\n"
        "ClientAliveInterval 60\n"
        "ClientAliveCountMax 5\n"
    )
    # Appended to the main config so it overrides defaults on any distro
    with open("/etc/ssh/sshd_config", "a") as f:
        f.write("\n" + config)

    if pubkey:
        with open("/root/.ssh/authorized_keys", "a") as f:
            f.write(pubkey.strip() + "\n")
        run("chmod 600 /root/.ssh/authorized_keys")

    run("pkill sshd", check=False)
    run("/usr/sbin/sshd")
    return password


def start_tunnel():
    print("[4/4] Starting Cloudflare tunnel...")
    log = open(LOG_FILE, "w")
    proc = subprocess.Popen(
        [CLOUDFLARED_BIN, "tunnel", "--url", "ssh://localhost:22", "--no-autoupdate"],
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--pubkey", default=os.environ.get("SSH_PUBKEY", ""))
    args = parser.parse_args()

    install_packages()
    password = configure_ssh(args.pubkey)
    proc, host = start_tunnel()

    line = "=" * 56
    print(f"\n{line}")
    print(" READY - run these in Termux")
    print(line)
    print("\n# One-time setup:")
    print("pkg update -y && pkg install -y openssh cloudflared")
    print("\n# Connect:")
    print(f'ssh -o ProxyCommand="cloudflared access ssh --hostname {host}" root@{host}')
    print(f"\nUser     : root")
    print(f"Password : {password}")
    print(f"Hostname : {host}")
    print(f"{line}\n")
    print("Keep this cell running. Press Stop to shut down.")

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
