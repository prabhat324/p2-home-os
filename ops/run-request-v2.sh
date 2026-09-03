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

case "${operation}" in
  pre-relocation-backup-audit)
    [[ "${target}" == "all" ]] || { echo "pre-relocation-backup-audit is restricted to all" >&2; exit 2; }
    playbook="playbooks/pre-relocation-backup-audit.yml"
    ;;
  photo-storage-direct-audit)
    [[ "${target}" == "compute-01" ]] || { echo "photo-storage-direct-audit is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/photo-storage-direct-audit.yml"
    ;;
  photo-storage-mount-readiness)
    [[ "${target}" == "compute-01" ]] || { echo "photo-storage-mount-readiness is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/photo-storage-mount-readiness.yml"
    ;;
  photo-storage-readonly-verify)
    [[ "${target}" == "compute-01" ]] || { echo "photo-storage-readonly-verify is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/photo-storage-readonly-verify.yml"
    ;;
  pre-relocation-compute04-shutdown)
    [[ "${target}" == "compute-04" ]] || { echo "pre-relocation-compute04-shutdown is restricted to compute-04" >&2; exit 2; }
    playbook="playbooks/pre-relocation-compute04-shutdown.yml"
    ;;
  infrastructure-persistence-audit)
    [[ "${target}" == "all" ]] || { echo "infrastructure-persistence-audit is restricted to all" >&2; exit 2; }
    playbook="playbooks/infrastructure-persistence-audit.yml"
    ;;
  core-identity-fix)
    [[ "${target}" == "core-01" ]] || { echo "core-identity-fix is restricted to core-01" >&2; exit 2; }
    playbook="playbooks/core-identity-fix.yml"
    ;;
  compute01-network-reboot-verify)
    [[ "${target}" == "compute-01" ]] || { echo "compute01-network-reboot-verify is restricted to compute-01" >&2; exit 2; }
    playbook="playbooks/compute01-network-reboot-verify.yml"
    ;;
  reviewmuse-readiness)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-readiness is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-readiness.yml"
    ;;
  reviewmuse-source-audit)
    [[ "${target}" == "compute-04" ]] || { echo "reviewmuse-source-audit is restricted to compute-04" >&2; exit 2; }
    playbook="playbooks/reviewmuse-source-audit.yml"
    ;;
  reviewmuse-bootstrap)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-bootstrap is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-bootstrap.yml"
    ;;
  reviewmuse-stage-migration)
    [[ "${target}" == "all" ]] || { echo "reviewmuse-stage-migration is restricted to all" >&2; exit 2; }
    playbook="playbooks/reviewmuse-stage-migration.yml"
    ;;
  reviewmuse-migration-verify)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-migration-verify is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-migration-verify.yml"
    ;;
  reviewmuse-v1-deploy)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-v1-deploy is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-v1-deploy.yml"
    ;;
  reviewmuse-prod-harden)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-prod-harden is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-prod-finalize.yml"
    ;;
  reviewmuse-db-role-diagnose)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-db-role-diagnose is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-db-role-diagnose.yml"
    ;;
  sentinelx-install-diagnose)
    [[ "${target}" == "compute-03" ]] || { echo "sentinelx-install-diagnose is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/sentinelx-install-diagnose.yml"
    ;;
  reviewmuse-v2-deploy)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-v2-deploy is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-v2-deploy.yml"
    ;;
  reviewmuse-v2-schema-grant)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-v2-schema-grant is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-v2-schema-grant.yml"
    ;;
  reviewmuse-v2-schema-revoke)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-v2-schema-revoke is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-v2-schema-revoke.yml"
    ;;
  reviewmuse-v2-db-hardening)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-v2-db-hardening is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-v2-db-hardening.yml"
    ;;
  reviewmuse-v2-refresh)
    [[ "${target}" == "compute-03" ]] || { echo "reviewmuse-v2-refresh is restricted to compute-03" >&2; exit 2; }
    playbook="playbooks/reviewmuse-v2-refresh.yml"
    ;;
  psquare-node-watchdog-deploy)
    [[ "${target}" == "core-01" ]] || { echo "psquare-node-watchdog-deploy is restricted to core-01" >&2; exit 2; }
    playbook="playbooks/psquare-node-watchdog-deploy.yml"
    ;;
  compute04-power-event-diagnose)
    [[ "${target}" == "compute-04" ]] || { echo "compute04-power-event-diagnose is restricted to compute-04" >&2; exit 2; }
    playbook="playbooks/compute04-power-event-diagnose.yml"
    ;;
  g50-01-adopt)
    [[ "${target}" == "core-01" ]] || { echo "g50-01-adopt is restricted to core-01" >&2; exit 2; }
    playbook="playbooks/g50-01-adopt.yml"
    ;;
  g50-02-provision)
    [[ "${target}" == "core-01" ]] || { echo "g50-02-provision is restricted to core-01" >&2; exit 2; }
    playbook="playbooks/g50-02-provision.yml"
    ;;
  dashboard-predeploy-backup-inspect)
    [[ "${target}" == "compute-02" ]] || { echo "dashboard-predeploy-backup-inspect is restricted to compute-02" >&2; exit 2; }
    playbook="playbooks/dashboard-predeploy-backup-inspect.yml"
    ;;
  *)
    exec bash "${ROOT_DIR}/ops/run-request.sh" "${REQUEST_FILE}"
    ;;
esac

echo "P2_HOME_OS_REQUEST=${request_id}"
echo "P2_HOME_OS_OPERATION=${operation}"
echo "P2_HOME_OS_TARGET=${target}"

cd "${ROOT_DIR}/ansible"
exec ansible-playbook "${playbook}" --limit "${target}"
