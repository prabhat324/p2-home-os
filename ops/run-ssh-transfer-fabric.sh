#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUEST_FILE="${1:-${ROOT_DIR}/ops/request.json}"
request_id="$(jq -er '.request_id' "${REQUEST_FILE}")"
operation="$(jq -er '.operation' "${REQUEST_FILE}")"
target="$(jq -er '.target' "${REQUEST_FILE}")"
[[ "${operation}" == "ssh-transfer-fabric" ]] || { echo "Wrong operation: ${operation}" >&2; exit 2; }
[[ "${target}" == "all" ]] || { echo "ssh-transfer-fabric is restricted to target=all" >&2; exit 2; }
[[ "${request_id}" =~ ^[A-Za-z0-9._-]{1,80}$ ]] || { echo "Invalid request_id" >&2; exit 2; }
echo "P2_HOME_OS_REQUEST=${request_id}"
echo "P2_HOME_OS_OPERATION=${operation}"
echo "P2_HOME_OS_TARGET=${target}"
cd "${ROOT_DIR}/ansible"
exec ansible-playbook playbooks/ssh-transfer-fabric.yml --limit 'control_nodes:compute_nodes'
