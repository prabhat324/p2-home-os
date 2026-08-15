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

HELPER_DST="/usr/local/sbin/p2ops-osho-managed-patch"
SUDOERS_DST="/etc/sudoers.d/p2ops-osho-managed-patch"
RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/master/scripts/p2ops-osho-managed-patch"
APPLY_NOW="${OSHO_MANAGED_PATCH_APPLY_NOW:-0}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

curl -fsSL "${RAW}?cb=$(date +%s)" -o "$work/helper"
chmod 0755 "$work/helper"

sudo install -o root -g root -m 0755 "$work/helper" "$HELPER_DST"

cat > "$work/sudoers" <<'EOF'
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-managed-patch status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-managed-patch apply
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
    echo "=== APPLY CURRENT MANAGED OSHO PATCHES ==="
    sudo -u p2ops sudo -n "$HELPER_DST" apply
fi

echo
echo "Scoped Osho managed-patch helper installation complete."
echo "The helper can only edit six allowlisted Project Osho ranking/QA Python files."
echo "It cannot run arbitrary shell commands or modify system configuration."
