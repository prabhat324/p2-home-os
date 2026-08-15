#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/prabhat324/p2-home-os"
REPO_GIT="${REPO_URL}.git"
RUNNER_USER="p2runner"
REMOTE_OPS_USER="p2ops"
RUNNER_HOME="/home/${RUNNER_USER}"
CHECKOUT_DIR="${RUNNER_HOME}/p2-home-os"
RUNNER_DIR="${RUNNER_HOME}/actions-runner"
RUNNER_NAME="core-01"
RUNNER_LABELS="core-01,control-plane"
ADMIN_SSH_USER="psquare"
SSH_KEY="${RUNNER_HOME}/.ssh/id_ed25519_p2homeos"
TARGETS=(
  "compute-01:192.168.0.31"
  "compute-02:192.168.0.88"
  "compute-03:192.168.0.158"
)

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this script as your normal user, not as root. It will use sudo when required." >&2
  exit 1
fi

command -v sudo >/dev/null || { echo "sudo is required" >&2; exit 1; }

echo "== Installing control-plane packages =="
sudo apt-get update
sudo apt-get install -y ansible git jq curl ca-certificates openssh-client

echo "== Creating unprivileged runner account =="
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
  sudo useradd --create-home --shell /bin/bash "${RUNNER_USER}"
fi
sudo install -d -m 700 -o "${RUNNER_USER}" -g "${RUNNER_USER}" "${RUNNER_HOME}/.ssh"

if [[ ! -f "${SSH_KEY}" ]]; then
  sudo -u "${RUNNER_USER}" -H ssh-keygen -q -t ed25519 -f "${SSH_KEY}" -N '' -C 'p2-home-os-control@core-01'
fi
sudo chmod 600 "${SSH_KEY}"
sudo chmod 644 "${SSH_KEY}.pub"
PUBLIC_KEY="$(sudo cat "${SSH_KEY}.pub")"

echo "== Preparing known-hosts trust =="
install -d -m 700 "${HOME}/.ssh"
touch "${HOME}/.ssh/known_hosts"
chmod 600 "${HOME}/.ssh/known_hosts"
sudo -u "${RUNNER_USER}" -H touch "${RUNNER_HOME}/.ssh/known_hosts"
sudo chmod 600 "${RUNNER_HOME}/.ssh/known_hosts"

for entry in "${TARGETS[@]}"; do
  name="${entry%%:*}"
  host="${entry##*:}"
  echo "== Provisioning ${REMOTE_OPS_USER} on ${name} (${host}) =="

  ssh-keyscan -H "${host}" >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
  ssh-keyscan -H "${host}" | sudo tee -a "${RUNNER_HOME}/.ssh/known_hosts" >/dev/null 2>&1 || true

  if sudo -u "${RUNNER_USER}" -H ssh \
      -o BatchMode=yes -o ConnectTimeout=5 \
      -i "${SSH_KEY}" "${REMOTE_OPS_USER}@${host}" true 2>/dev/null; then
    echo "Dedicated control access already works for ${name}."
    continue
  fi

  echo "One-time SSH/sudo authentication may be requested for ${name}."
  printf -v remote_cmd \
    'sudo sh -c '\''id -u %s >/dev/null 2>&1 || useradd --create-home --shell /bin/bash %s; install -d -m 700 -o %s -g %s /home/%s/.ssh; printf "%%s\\n" "%s" > /home/%s/.ssh/authorized_keys; chown %s:%s /home/%s/.ssh/authorized_keys; chmod 600 /home/%s/.ssh/authorized_keys'\'' ' \
    "${REMOTE_OPS_USER}" "${REMOTE_OPS_USER}" \
    "${REMOTE_OPS_USER}" "${REMOTE_OPS_USER}" "${REMOTE_OPS_USER}" \
    "${PUBLIC_KEY}" "${REMOTE_OPS_USER}" \
    "${REMOTE_OPS_USER}" "${REMOTE_OPS_USER}" "${REMOTE_OPS_USER}" "${REMOTE_OPS_USER}"

  ssh -t "${ADMIN_SSH_USER}@${host}" "${remote_cmd}"
done

sort -u "${HOME}/.ssh/known_hosts" -o "${HOME}/.ssh/known_hosts"
sudo sh -c "sort -u '${RUNNER_HOME}/.ssh/known_hosts' -o '${RUNNER_HOME}/.ssh/known_hosts'"
sudo chown -R "${RUNNER_USER}:${RUNNER_USER}" "${RUNNER_HOME}/.ssh"

echo "== Preparing repository checkout for runner =="
if [[ -d "${CHECKOUT_DIR}/.git" ]]; then
  sudo -u "${RUNNER_USER}" -H git -C "${CHECKOUT_DIR}" fetch origin
  sudo -u "${RUNNER_USER}" -H git -C "${CHECKOUT_DIR}" checkout master
  sudo -u "${RUNNER_USER}" -H git -C "${CHECKOUT_DIR}" pull --ff-only origin master
else
  sudo -u "${RUNNER_USER}" -H git clone "${REPO_GIT}" "${CHECKOUT_DIR}"
fi

echo "== Validating Ansible connectivity =="
sudo -u "${RUNNER_USER}" -H bash -lc "cd '${CHECKOUT_DIR}/ansible' && ansible-inventory --graph && ansible all -m ping"

echo "== Installing GitHub Actions self-hosted runner =="
sudo install -d -m 755 -o "${RUNNER_USER}" -g "${RUNNER_USER}" "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

if [[ ! -f .runner ]]; then
  runner_version="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r '.tag_name' | sed 's/^v//')"
  archive="actions-runner-linux-arm64-${runner_version}.tar.gz"
  sudo -u "${RUNNER_USER}" -H curl -fL -o "${archive}" "https://github.com/actions/runner/releases/download/v${runner_version}/${archive}"
  sudo -u "${RUNNER_USER}" -H tar xzf "${archive}"
  sudo -u "${RUNNER_USER}" -H rm -f "${archive}"

  echo
  echo "Open GitHub -> p2-home-os -> Settings -> Actions -> Runners -> New self-hosted runner."
  echo "Choose Linux / ARM64 and copy only the temporary registration token."
  read -r -s -p "Runner registration token: " RUNNER_TOKEN
  echo
  sudo -u "${RUNNER_USER}" -H ./config.sh \
    --url "${REPO_URL}" \
    --token "${RUNNER_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --unattended \
    --replace
else
  echo "Runner is already configured; keeping the existing registration."
fi

sudo ./svc.sh install "${RUNNER_USER}" 2>/dev/null || true
sudo ./svc.sh start
sudo ./svc.sh status || true

echo
echo "Control-plane bootstrap complete."
echo "Runner user: ${RUNNER_USER} (no sudo privileges added)"
echo "Remote user: ${REMOTE_OPS_USER} (no sudo privileges added)"
echo "Runner: ${RUNNER_NAME}"
echo "Next: verify the runner shows Online in GitHub Actions settings."
