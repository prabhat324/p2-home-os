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
  infrastructure-persistence-audit)
    [[ "${target}" == "all" ]] || { echo "infrastructure-persistence-audit is restricted to all" >&2; exit 2; }
    playbook="playbooks/infrastructure-persistence-audit.yml"
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
  *)
    exec bash "${ROOT_DIR}/ops/run-request.sh" "${REQUEST_FILE}"
    ;;
esac

echo "P2_HOME_OS_REQUEST=${request_id}"
echo "P2_HOME_OS_OPERATION=${operation}"
echo "P2_HOME_OS_TARGET=${target}"

cd "${ROOT_DIR}/ansible"
exec ansible-playbook "${playbook}" --limit "${target}"
