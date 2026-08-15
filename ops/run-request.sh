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
  ollama-status)
    [[ "${target}" == "compute-01" ]] || { echo "ollama-status is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/ollama-status.yml" ;;
  ollama-lan-audit)
    [[ "${target}" == "all" ]] || { echo "ollama-lan-audit is restricted to all" >&2; exit 2; }
    playbook="playbooks/ollama-lan-audit.yml" ;;
  ollama-lan-fix)
    [[ "${target}" == "all" ]] || { echo "ollama-lan-fix is restricted to all" >&2; exit 2; }
    playbook="playbooks/ollama-lan-fix.yml" ;;
  home-dashboard-inventory)
    [[ "${target}" == "all" ]] || { echo "home-dashboard-inventory is restricted to all" >&2; exit 2; }
    playbook="playbooks/home-dashboard-inventory.yml" ;;
  mavrick-inventory)
    [[ "${target}" == "compute-02" ]] || { echo "mavrick-inventory is restricted to compute-02" >&2; exit 2; }
    playbook="playbooks/mavrick-inventory.yml" ;;
  home-dashboard-deploy)
    [[ "${target}" == "core-01" ]] || { echo "home-dashboard-deploy is restricted to core-01" >&2; exit 2; }
    playbook="playbooks/home-dashboard-deploy.yml" ;;
  p2-dashboard-route)
    [[ "${target}" == "core-01" ]] || { echo "p2-dashboard-route is restricted to core-01" >&2; exit 2; }
    playbook="playbooks/p2-dashboard-route.yml" ;;
  compute-monitoring-bootstrap)
    [[ "${target}" == "compute-03" ]] || { echo "compute-monitoring-bootstrap is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/compute-monitoring-bootstrap.yml" ;;
  dashboard-diagnose)
    [[ "${target}" == "compute-02" ]] || { echo "dashboard-diagnose is restricted to compute-02" >&2; exit 2; }
    playbook="playbooks/dashboard-diagnose.yml" ;;
  dashboard-deploy)
    [[ "${target}" == "compute-02" ]] || { echo "dashboard-deploy is restricted to compute-02" >&2; exit 2; }
    playbook="playbooks/dashboard-deploy.yml" ;;
  osho-maintenance)
    [[ "${target}" == "compute-01" ]] || { echo "osho-maintenance is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-maintenance.yml" ;;
  osho-buffer)
    [[ "${target}" == "compute-01" ]] || { echo "osho-buffer is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-buffer.yml" ;;
  osho-publish-audit)
    [[ "${target}" == "compute-01" ]] || { echo "osho-publish-audit is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-publish-audit.yml" ;;
  osho-ranker-diagnose)
    [[ "${target}" == "compute-01" ]] || { echo "osho-ranker-diagnose is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-ranker-diagnose.yml" ;;
  osho-publisher-diagnose)
    [[ "${target}" == "compute-01" ]] || { echo "osho-publisher-diagnose is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-publisher-diagnose.yml" ;;
  osho-notifications-diagnose)
    [[ "${target}" == "compute-01" ]] || { echo "osho-notifications-diagnose is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-notifications-diagnose.yml" ;;
  osho-discord-deploy)
    [[ "${target}" == "compute-01" ]] || { echo "osho-discord-deploy is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-discord-deploy.yml" ;;
  osho-discord-snapshot)
    [[ "${target}" == "compute-01" ]] || { echo "osho-discord-snapshot is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-discord-snapshot.yml" ;;
  osho-publisher-fix)
    [[ "${target}" == "compute-01" ]] || { echo "osho-publisher-fix is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-publisher-fix.yml" ;;
  osho-qa-fix)
    [[ "${target}" == "compute-01" ]] || { echo "osho-qa-fix is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/osho-qa-fix.yml" ;;
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
