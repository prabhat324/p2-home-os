#!/usr/bin/env bash
# Run locally with sudo after reviewing. Does not grant remote sudo or alter GPU limits.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y lm-sensors iperf3
# Wait only for a usable routable connection; unplugged Wi-Fi must not block boot.
install -d /etc/systemd/system/systemd-networkd-wait-online.service.d
cat >/etc/systemd/system/systemd-networkd-wait-online.service.d/media01.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --any --operational-state=routable --timeout=30
UNIT
systemctl daemon-reload
systemctl restart systemd-networkd-wait-online.service
smartctl -a /dev/nvme0n1 > /srv/media-production/logs/nvme-health-admin.txt
nvme smart-log /dev/nvme0 > /srv/media-production/logs/nvme-smart-admin.txt
sensors > /srv/media-production/logs/sensors-admin.txt
# No daemon/listening port required for iperf3; use a bounded one-shot test when peer is ready.
echo 'Administrator prerequisites completed. GPU power limit unchanged.'
