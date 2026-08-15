#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPER_SRC="$REPO_ROOT/ops/privileged/p2ops-osho-maintenance"
HELPER_DST="/usr/local/sbin/p2ops-osho-maintenance"
SUDOERS_FILE="/etc/sudoers.d/p2ops-osho-maintenance"

if [[ ${EUID} -eq 0 ]]; then
    echo "Run this installer as the normal administrative user; it will use sudo." >&2
    exit 1
fi

if [[ ! -f "$HELPER_SRC" ]]; then
    echo "Helper source not found: $HELPER_SRC" >&2
    exit 2
fi

if ! id p2ops >/dev/null 2>&1; then
    echo "Required automation account p2ops does not exist on this host." >&2
    exit 2
fi

command -v sudo >/dev/null
command -v visudo >/dev/null

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

cat > "$TMP" <<'EOF'
# P2 Home OS - narrowly scoped Project Osho maintenance permissions.
# No shells, editors, package managers, arbitrary systemctl, or arbitrary arguments.
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-maintenance status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-maintenance restart-dashboard-telemetry
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-maintenance fix-whisper-cache
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-maintenance apply-safe-fixes
EOF

sudo visudo -cf "$TMP"
sudo install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"
sudo install -o root -g root -m 0440 "$TMP" "$SUDOERS_FILE"
sudo visudo -cf "$SUDOERS_FILE"

echo "Installed helper: $HELPER_DST"
echo "Installed sudoers: $SUDOERS_FILE"

echo
echo "=== TEST AS p2ops ==="
sudo -u p2ops sudo -n "$HELPER_DST" status

echo
echo "Scoped helper installation complete."
echo "p2ops still has no general sudo access."
