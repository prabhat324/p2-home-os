#!/usr/bin/env bash
set -euo pipefail

case "$(hostname -s)" in
  compute-01) ;;
  *) echo "This installer must run on compute-01." >&2; exit 2 ;;
esac

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this installer as psquare; it will use sudo where required." >&2
  exit 2
fi

id p2ops >/dev/null 2>&1 || { echo "p2ops account is missing" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }
command -v visudo >/dev/null 2>&1 || { echo "visudo is required" >&2; exit 2; }

HELPER_DST="/usr/local/sbin/p2ops-osho-buffer"
SUDOERS_DST="/etc/sudoers.d/p2ops-osho-buffer"
RAW="https://raw.githubusercontent.com/prabhat324/p2-home-os/master/scripts/p2ops-osho-buffer"
APPLY_NOW="${OSHO_BUFFER_APPLY_NOW:-0}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

curl -fsSL "${RAW}?cb=$(date +%s)" -o "$work/helper"
chmod 0755 "$work/helper"

sudo install -o root -g root -m 0755 "$work/helper" "$HELPER_DST"

cat > "$work/sudoers" <<'EOF'
# Project Osho rolling-buffer control only. No arbitrary shell/systemctl/arguments.
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-buffer status
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-buffer apply
p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-osho-buffer refill-now
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
  echo "=== ENABLE CONTINUOUS OSHO BUFFER ==="
  sudo -u p2ops sudo -n "$HELPER_DST" apply
fi

echo
echo "Scoped Osho buffer helper installation complete."
echo "It may only inspect/apply the fixed rolling buffer and request its dedicated refill service."
echo "The refill service runs as psquare, targets 25 ready source audios, and never bypasses Osho ranking, QA, receipts, or publishing safeguards."
