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
  compute-02|compute-03|compute-04) targets=("$target") ;;
  compute_nodes) targets=(compute-02 compute-03 compute-04) ;;
  *) echo "network-static-fix is restricted to compute-02, compute-03, compute-04, or compute_nodes" >&2; exit 2 ;;
esac

echo "P2_HOME_OS_REQUEST=$request_id"
echo "P2_HOME_OS_OPERATION=$operation"
echo "P2_HOME_OS_TARGET=$target"

install -d -m 700 "$HOME/.ssh"
touch "$HOME/.ssh/known_hosts"
chmod 600 "$HOME/.ssh/known_hosts"
SSH_KEY="$HOME/.ssh/id_ed25519_p2homeos"

candidate_ips() {
  case "$1" in
    compute-02) echo "192.168.0.88 192.168.0.84" ;;
    compute-03) echo "192.168.0.158 192.168.0.157" ;;
    compute-04) echo "192.168.0.177 192.168.0.176" ;;
  esac
}

resolve_target_ip() {
  local host="$1" ip seen
  for ip in $(candidate_ips "$host"); do
    ssh-keyscan -H "$ip" >> "$HOME/.ssh/known_hosts" 2>/dev/null || true
    sort -u "$HOME/.ssh/known_hosts" -o "$HOME/.ssh/known_hosts"
    seen="$(ssh \
      -i "$SSH_KEY" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=yes \
      -o ConnectTimeout=4 \
      "p2ops@$ip" hostname -s 2>/dev/null || true)"
    if [[ "$seen" == "$host" ]]; then
      echo "$ip"
      return 0
    fi
  done
  return 1
}

cd "$ROOT_DIR/ansible"
failures=0
for host in "${targets[@]}"; do
  current_ip="$(resolve_target_ip "$host" || true)"
  if [[ -z "$current_ip" ]]; then
    echo "ERROR: could not securely identify $host at any documented current/production address" >&2
    failures=$((failures + 1))
    continue
  fi

  echo "P2_HOME_OS_HOST=$host"
  echo "P2_HOME_OS_CURRENT_IP=$current_ip"

  if ! ansible-playbook playbooks/network-static-fix.yml \
      --limit "$host" \
      -e "ansible_host=$current_ip"; then
    failures=$((failures + 1))
  fi
done

if (( failures > 0 )); then
  echo "network-static-fix completed with $failures failure(s)" >&2
  exit 1
fi

echo "network-static-fix completed successfully for ${targets[*]}"
