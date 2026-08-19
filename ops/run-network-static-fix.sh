#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUEST_FILE="${1:-${ROOT_DIR}/ops/request.json}"

request_id="$(jq -er '.request_id' "$REQUEST_FILE")"
operation="$(jq -er '.operation' "$REQUEST_FILE")"
target="$(jq -er '.target' "$REQUEST_FILE")"

[[ "$request_id" =~ ^[A-Za-z0-9._-]{1,80}$ ]] || { echo "Invalid request_id" >&2; exit 2; }
[[ "$operation" == "network-static-fix" ]] || { echo "Invalid operation for network dispatcher" >&2; exit 2; }
case "$target" in
  compute-02|compute-03) ;;
  *) echo "network-static-fix is restricted to compute-02 or compute-03" >&2; exit 2 ;;
esac

echo "P2_HOME_OS_REQUEST=$request_id"
echo "P2_HOME_OS_OPERATION=$operation"
echo "P2_HOME_OS_TARGET=$target"

cd "$ROOT_DIR/ansible"
exec ansible-playbook playbooks/network-static-fix.yml --limit "$target"
