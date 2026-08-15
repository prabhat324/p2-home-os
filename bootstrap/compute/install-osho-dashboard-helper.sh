#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/master"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd || true)"
LOCAL_HELPER="${ROOT_DIR:+$ROOT_DIR/scripts/p2ops-osho-dashboard}"
HELPER_DST="/usr/local/sbin/p2ops-osho-dashboard"
SUDOERS_DST="/etc/sudoers.d/p2ops-osho-dashboard"
DEPLOY_NOW="${OSHO_DASHBOARD_DEPLOY_NOW:-0}"

if [[ "$(hostname -s)" != "compute-02" ]]; then
    echo "This installer must be run on compute-02." >&2
    exit 2
fi

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as psquare; it will call sudo where needed." >&2
    exit 2
fi

id p2ops >/dev/null 2>&1 || { echo "p2ops account is missing" >&2; exit 2; }
command -v visudo >/dev/null 2>&1 || { echo "visudo is required" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
HELPER_SRC="$work/p2ops-osho-dashboard"

if [[ -n "$LOCAL_HELPER" && -f "$LOCAL_HELPER" ]]; then
    cp "$LOCAL_HELPER" "$HELPER_SRC"
else
    echo "Local repo helper not found; downloading fixed helper from master."
    curl -fsSL "$REPO_RAW/scripts/p2ops-osho-dashboard" -o "$HELPER_SRC"
fi

chmod 0755 "$HELPER_SRC"
sudo install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"

sudoers_tmp="$work/sudoers"
cat > "$sudoers_tmp" <<'EOF'
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-dashboard status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-dashboard deploy-master
EOF

sudo visudo -cf "$sudoers_tmp"
sudo install -o root -g root -m 0440 "$sudoers_tmp" "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"

echo "Installed helper: $HELPER_DST"
echo "Installed sudoers: $SUDOERS_DST"

echo
echo "=== TEST AS p2ops ==="
sudo -u p2ops sudo -n "$HELPER_DST" status

echo
echo "=== ALLOWED SUDO ==="
sudo -u p2ops sudo -n -l

if [[ "$DEPLOY_NOW" == "1" ]]; then
    echo
    echo "=== FIRST SCOPED DASHBOARD DEPLOY ==="
    sudo -u p2ops sudo -n "$HELPER_DST" deploy-master
fi

echo
echo "Scoped dashboard helper installation complete."
echo "p2ops still has no general sudo or direct Docker access."
