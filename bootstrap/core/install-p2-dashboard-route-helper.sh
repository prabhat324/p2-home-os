#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPER_SRC="$REPO_ROOT/scripts/p2ops-p2-dashboard-route"
HELPER_DST="/usr/local/sbin/p2ops-p2-dashboard-route"
SUDOERS_FILE="/etc/sudoers.d/p2runner-p2-dashboard-route"
AUTOMATION_USER="p2runner"

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this installer as the normal administrative user; it will use sudo." >&2
  exit 1
fi

case "$(hostname -s)" in
  media-server|core-01) ;;
  *) echo "This installer is restricted to core-01/media-server." >&2; exit 2 ;;
esac

[[ -f "$HELPER_SRC" ]] || { echo "Helper source not found: $HELPER_SRC" >&2; exit 2; }
id "$AUTOMATION_USER" >/dev/null 2>&1 || { echo "Required automation account $AUTOMATION_USER does not exist." >&2; exit 2; }
command -v sudo >/dev/null
command -v visudo >/dev/null

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<'EOF'
# P2 Home OS - narrowly scoped dashboard routing permissions on core-01.
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-p2-dashboard-route status
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-p2-dashboard-route activate-custom
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-p2-dashboard-route restore-homepage
EOF
sudo visudo -cf "$TMP"
sudo install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"
sudo install -o root -g root -m 0440 "$TMP" "$SUDOERS_FILE"
sudo visudo -cf "$SUDOERS_FILE"
sudo -u "$AUTOMATION_USER" sudo -n "$HELPER_DST" status

echo "Scoped P2 dashboard route helper installed."
echo "$AUTOMATION_USER still has no general sudo, Docker, shell, or arbitrary Caddy access."
