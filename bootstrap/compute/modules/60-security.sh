#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ufw fail2ban unattended-upgrades

sudo systemctl enable --now fail2ban

sudo mkdir -p /etc/ssh/sshd_config.d

cat <<'EOF_SSH' | sudo tee /etc/ssh/sshd_config.d/20-p2-baseline.conf >/dev/null
PermitRootLogin no
PubkeyAuthentication yes
PermitEmptyPasswords no
X11Forwarding no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
EOF_SSH

sudo sshd -t
sudo systemctl restart ssh

echo "Security packages and basic SSH hardening applied."
echo "UFW is installed but intentionally not enabled by this module."
echo "PasswordAuthentication is not disabled automatically."
