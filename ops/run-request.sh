#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUEST_FILE="${1:-${ROOT_DIR}/ops/request.json}"

if [[ ! -f "${REQUEST_FILE}" ]]; then
  echo "Request file not found: ${REQUEST_FILE}" >&2
  exit 2
fi

request_id="$(jq -er '.request_id' "${REQUEST_FILE}")"
operation="$(jq -er '.operation' "${REQUEST_FILE}")"
target="$(jq -er '.target' "${REQUEST_FILE}")"

if [[ ! "${request_id}" =~ ^[A-Za-z0-9._-]{1,80}$ ]]; then
  echo "Invalid request_id" >&2
  exit 2
fi

case "${target}" in
  all|core-01|compute-01|compute-02|compute-03|control_nodes|compute_nodes|gpu_nodes|osho_nodes) ;;
  *) echo "Target is not allowed: ${target}" >&2; exit 2 ;;
esac

case "${operation}" in
  ping) playbook="playbooks/ping.yml" ;;
  status) playbook="playbooks/status.yml" ;;
  gpu-status) playbook="playbooks/gpu-status.yml" ;;
  osho-status) playbook="playbooks/osho-status.yml" ;;
  dashboard-diagnose)
    [[ "${target}" == "compute-02" ]] || { echo "dashboard-diagnose is restricted to compute-02" >&2; exit 2; }
    playbook="playbooks/dashboard-diagnose.yml" ;;
  dashboard-deploy)
    [[ "${target}" == "compute-02" ]] || { echo "dashboard-deploy is restricted to compute-02" >&2; exit 2; }
    playbook="playbooks/dashboard-deploy.yml" ;;
  osho-maintenance)
    [[ "${target}" == "compute-01" ]] || { echo "osho-maintenance is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-maintenance.yml" ;;
  osho-publish-audit)
    [[ "${target}" == "compute-01" ]] || { echo "osho-publish-audit is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-publish-audit.yml" ;;
  youtube-analytics-diagnose)
    [[ "${target}" == "osho_nodes" ]] || { echo "youtube-analytics-diagnose is restricted to osho_nodes" >&2; exit 2; }
    playbook="playbooks/youtube-analytics-diagnose.yml" ;;
  youtube-analytics-runtime)
    [[ "${target}" == "compute-01" ]] || { echo "youtube-analytics-runtime is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/youtube-analytics-runtime.yml" ;;
  *) echo "Operation is not allowed: ${operation}" >&2; exit 2 ;;
esac

echo "P2_HOME_OS_REQUEST=${request_id}"
echo "P2_HOME_OS_OPERATION=${operation}"
echo "P2_HOME_OS_TARGET=${target}"

cd "${ROOT_DIR}/ansible"
exec ansible-playbook "${playbook}" --limit "${target}"
