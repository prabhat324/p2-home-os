#!/usr/bin/env bash
set -euo pipefail

HOST="$(hostname -s)"
case "$HOST" in
  compute-02|compute-03) ;;
  *) echo "This installer is restricted to compute-02/compute-03; current host: $HOST" >&2; exit 2 ;;
esac

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as the normal administrative user; it will use sudo." >&2
  exit 2
fi

id p2ops >/dev/null 2>&1 || { echo "p2ops account is missing" >&2; exit 2; }
command -v sudo >/dev/null
command -v visudo >/dev/null
command -v curl >/dev/null

HELPER_DST="/usr/local/sbin/p2ops-network-static"
SUDOERS_DST="/etc/sudoers.d/p2ops-network-static"
RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/ops-control/scripts/p2ops-network-static"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "${RAW}?cb=$(date +%s)" -o "$TMP/helper"
chmod 0755 "$TMP/helper"

cat > "$TMP/sudoers" <<'EOF'
# P2 Home OS - narrowly scoped persistent LAN address management.
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-network-static status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-network-static apply
EOF

sudo visudo -cf "$TMP/sudoers"
sudo install -o root -g root -m 0755 "$TMP/helper" "$HELPER_DST"
sudo install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"
sudo -u p2ops sudo -n "$HELPER_DST" status

echo "Scoped persistent network helper installed for $HOST."
echo "p2ops can only inspect/apply the documented IP for this host; no general sudo was granted."
