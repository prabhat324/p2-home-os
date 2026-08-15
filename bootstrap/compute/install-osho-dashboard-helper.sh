#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER_SRC="$ROOT_DIR/scripts/p2ops-osho-dashboard"
HELPER_DST="/usr/local/sbin/p2ops-osho-dashboard"
SUDOERS_DST="/etc/sudoers.d/p2ops-osho-dashboard"

if [[ "$(hostname -s)" != "compute-02" ]]; then
    echo "This installer must be run on compute-02." >&2
    exit 2
fi

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as psquare; it will call sudo where needed." >&2
    exit 2
fi

[[ -f "$HELPER_SRC" ]]
id p2ops >/dev/null 2>&1 || { echo "p2ops account is missing" >&2; exit 2; }
command -v visudo >/dev/null 2>&1 || { echo "visudo is required" >&2; exit 2; }

sudo install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp" <<'EOF'
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-dashboard status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-dashboard deploy-master
EOF

sudo visudo -cf "$tmp"
sudo install -o root -g root -m 0440 "$tmp" "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"

echo "Installed helper: $HELPER_DST"
echo "Installed sudoers: $SUDOERS_DST"

echo
echo "=== TEST AS p2ops ==="
sudo -u p2ops sudo -n "$HELPER_DST" status

echo
echo "Scoped dashboard helper installation complete."
echo "p2ops still has no general sudo or Docker access."
