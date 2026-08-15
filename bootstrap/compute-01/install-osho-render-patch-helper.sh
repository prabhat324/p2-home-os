#!/usr/bin/env bash
set -euo pipefail

case "$(hostname -s)" in
    compute-01) ;;
    *) echo "This installer must be run on compute-01." >&2; exit 2 ;;
esac

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this installer as psquare; it will call sudo where needed." >&2
    exit 2
fi

id p2ops >/dev/null 2>&1 || { echo "p2ops account is missing" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }
command -v visudo >/dev/null 2>&1 || { echo "visudo is required" >&2; exit 2; }

HELPER_DST="/usr/local/sbin/p2ops-osho-render-patch"
SUDOERS_DST="/etc/sudoers.d/p2ops-osho-render-patch"
RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/master/scripts/p2ops-osho-render-patch"
APPLY_NOW="${OSHO_RENDER_PATCH_APPLY_NOW:-0}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

curl -fsSL "${RAW}?cb=$(date +%s)" -o "$work/helper"
chmod 0755 "$work/helper"

sudo install -o root -g root -m 0755 "$work/helper" "$HELPER_DST"

cat > "$work/sudoers" <<'EOF'
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-render-patch status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-render-patch apply-if-idle
EOF

sudo visudo -cf "$work/sudoers"
sudo install -o root -g root -m 0440 "$work/sudoers" "$SUDOERS_DST"
sudo visudo -cf "$SUDOERS_DST"

echo "Installed helper: $HELPER_DST"
echo "Installed sudoers: $SUDOERS_DST"

echo
echo "=== TEST AS p2ops ==="
sudo -u p2ops sudo -n "$HELPER_DST" status

if [[ "$APPLY_NOW" == "1" ]]; then
    echo
    echo "=== APPLY GROWTH RENDER PATCH IF WORKER IS IDLE ==="
    sudo -u p2ops sudo -n "$HELPER_DST" apply-if-idle
fi

echo
echo "Scoped Osho growth-render helper installation complete."
echo "The helper can edit only app.py and production_renderer.py using the source-controlled render manifest."
echo "It restarts only the osho-worker container, and only when /jobs reports no active job."
echo "It cannot run arbitrary shell commands or restart the Osho autopilot."
