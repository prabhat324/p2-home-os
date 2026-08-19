#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as the normal administrative user; it will use sudo." >&2
  exit 2
fi

id p2runner >/dev/null 2>&1 || { echo "p2runner account is missing" >&2; exit 2; }
command -v sudo >/dev/null
command -v visudo >/dev/null
command -v curl >/dev/null

HELPER_DST="/usr/local/sbin/p2ops-core-identity"
SUDOERS_DST="/etc/sudoers.d/p2ops-core-identity"
RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/ops-control/scripts/p2ops-core-identity"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "${RAW}?cb=$(date +%s)" -o "$TMP/helper"
chmod 0755 "$TMP/helper"

cat > "$TMP/sudoers" <<'EOF'
# P2 Home OS - narrowly scoped core hostname identity management.
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-core-identity status
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-core-identity apply
EOF

sudo visudo -cf "$TMP/sudoers"
sudo install -o root -g root -m 0755 "$TMP/helper" "$HELPER_DST"
sudo install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"
sudo -u p2runner sudo -n "$HELPER_DST" status

echo "Scoped core identity helper installed."
echo "p2runner can only inspect/apply the documented core-01 hostname; no general sudo was granted."
