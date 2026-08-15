#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPER_SRC="$REPO_ROOT/scripts/p2ops-ollama-lan-firewall"
HELPER_DST="/usr/local/sbin/p2ops-ollama-lan-firewall"
SUDOERS_FILE="/etc/sudoers.d/p2ops-ollama-lan-firewall"

if [[ ${EUID} -eq 0 ]]; then
    echo "Run this installer as the normal administrative user; it will use sudo." >&2
    exit 1
fi

[[ "$(hostname -s)" == "compute-01" ]] || { echo "This installer is restricted to compute-01." >&2; exit 2; }
[[ -f "$HELPER_SRC" ]] || { echo "Helper source not found: $HELPER_SRC" >&2; exit 2; }
id p2ops >/dev/null 2>&1 || { echo "Required automation account p2ops does not exist." >&2; exit 2; }

command -v sudo >/dev/null
command -v visudo >/dev/null

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

cat > "$TMP" <<'EOF'
# P2 Home OS - narrowly scoped Ollama LAN firewall permissions on compute-01.
# No arbitrary ufw, nft, iptables, shells, editors, or package-manager access.
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-ollama-lan-firewall status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-ollama-lan-firewall allow-lan
EOF

sudo visudo -cf "$TMP"
sudo install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"
sudo install -o root -g root -m 0440 "$TMP" "$SUDOERS_FILE"
sudo visudo -cf "$SUDOERS_FILE"

sudo -u p2ops sudo -n "$HELPER_DST" status

echo "Scoped Ollama LAN firewall helper installed."
echo "p2ops still has no general sudo or arbitrary firewall access."
