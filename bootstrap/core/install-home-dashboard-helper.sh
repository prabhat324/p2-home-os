#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/master"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd || true)"
LOCAL_HELPER="${ROOT_DIR:+$ROOT_DIR/scripts/p2ops-home-dashboard}"
HELPER_DST="/usr/local/sbin/p2ops-home-dashboard"
SUDOERS_DST="/etc/sudoers.d/p2ops-home-dashboard"
DEPLOY_NOW="${HOME_DASHBOARD_DEPLOY_NOW:-0}"

case "$(hostname -s)" in
    media-server|core-01) ;;
    *) echo "This installer must be run on core-01/media-server." >&2; exit 2 ;;
esac

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as psquare; it will call sudo where needed." >&2
    exit 2
fi

id p2runner >/dev/null 2>&1 || { echo "p2runner account is missing" >&2; exit 2; }
command -v visudo >/dev/null 2>&1 || { echo "visudo is required" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
HELPER_SRC="$work/p2ops-home-dashboard"

if [[ -n "$LOCAL_HELPER" && -f "$LOCAL_HELPER" ]]; then
    cp "$LOCAL_HELPER" "$HELPER_SRC"
else
    curl -fsSL "$REPO_RAW/scripts/p2ops-home-dashboard" -o "$HELPER_SRC"
fi

chmod 0755 "$HELPER_SRC"
sudo install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER_DST"

sudoers_tmp="$work/sudoers"
cat > "$sudoers_tmp" <<'EOF'
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-home-dashboard status
p2runner ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-home-dashboard deploy-master
EOF

sudo visudo -cf "$sudoers_tmp"
sudo install -o root -g root -m 0440 "$sudoers_tmp" "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"

echo "Installed helper: $HELPER_DST"
echo "Installed sudoers: $SUDOERS_DST"

echo
echo "=== TEST AS p2runner ==="
sudo -u p2runner sudo -n "$HELPER_DST" status

if [[ "$DEPLOY_NOW" == "1" ]]; then
    echo
echo "=== FIRST SCOPED HOMEPAGE DEPLOY ==="
    sudo -u p2runner sudo -n "$HELPER_DST" deploy-master
fi

echo
echo "Scoped Homepage helper installation complete."
echo "p2runner still has no general sudo or unrestricted Docker access."
