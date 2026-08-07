#!/usr/bin/env bash
set -euo pipefail

sudo mkdir -p /etc/systemd/logind.conf.d

cat <<'EOF_LOGIND' | \
  sudo tee /etc/systemd/logind.conf.d/20-p2-server.conf >/dev/null
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
LidSwitchIgnoreInhibited=yes
EOF_LOGIND

sudo systemctl mask \
  sleep.target \
  suspend.target \
  hibernate.target \
  hybrid-sleep.target

echo "Laptop lid and sleep behavior configured for server operation."
echo "A reboot is recommended after the complete bootstrap."
