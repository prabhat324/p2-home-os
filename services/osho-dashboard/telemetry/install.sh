#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_BASE="${OSHO_DASHBOARD_BASE:-http://192.168.0.88:8787}"

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as psquare; it will call sudo where needed." >&2
    exit 1
fi

command -v python3 >/dev/null
command -v sudo >/dev/null

sudo install -d -m 0755 /usr/local/lib/project-osho
sudo install -m 0755 \
    "$SCRIPT_DIR/osho-dashboard-heartbeat.py" \
    /usr/local/lib/project-osho/osho-dashboard-heartbeat.py
sudo install -m 0644 \
    "$SCRIPT_DIR/osho-dashboard-heartbeat.service" \
    /etc/systemd/system/osho-dashboard-heartbeat.service

sudo systemctl daemon-reload
sudo systemctl enable osho-dashboard-heartbeat.service >/dev/null
sudo systemctl restart osho-dashboard-heartbeat.service

sleep 2
sudo systemctl --no-pager --full status osho-dashboard-heartbeat.service || true

echo
echo "Dashboard registration check:"
curl -fsS "$DASHBOARD_BASE/api/dashboard" \
    | python3 -m json.tool \
    | sed -n '/"workers"/,/"control_plane"/p' || true
