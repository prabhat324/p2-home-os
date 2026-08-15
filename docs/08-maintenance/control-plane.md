# Homelab Control Plane

## Purpose

`core-01` is the always-on execution gateway for routine P² Home OS operations. GitHub carries a small, version-controlled request to `core-01`; Ansible then performs a predefined operation against the requested node or group.

The goal is to remove repetitive terminal copy/paste while keeping direct Internet SSH access disabled.

## Architecture

```text
ChatGPT / GitHub connector
        |
        | updates ops/request.json
        v
GitHub branch: ops-control
        |
        | push event
        v
GitHub self-hosted runner on core-01
        |
        | restricted dispatcher
        v
Ansible
   |       |       |
compute-01 compute-02 compute-03
```

## Security model

This repository is public, so the control path is intentionally constrained.

- The self-hosted runner runs as the dedicated local account `p2runner`.
- `p2runner` is not granted sudo privileges by the bootstrap.
- Remote Ansible sessions use the dedicated account `p2ops`.
- `p2ops` is not granted sudo privileges by the bootstrap.
- No SSH port is exposed to the Internet for ChatGPT.
- No credentials, private keys, registration tokens, or command results are committed to the repository.
- The workflow only triggers when `ops/request.json` changes on the `ops-control` branch.
- The dispatcher rejects arbitrary shell commands and unknown targets.
- Phase 1 operations are read-only.

GitHub Actions logs for this public repository can reveal the output of the approved status checks. Keep approved operations limited to non-sensitive operational data. A future private operations repository or MCP service is preferred before enabling broader or privileged actions.

## Phase 1 approved operations

| Operation | Purpose |
| --- | --- |
| `ping` | Verify Ansible/SSH connectivity |
| `status` | Show uptime, load, memory and root filesystem usage |
| `gpu-status` | Show NVIDIA GPU utilization, memory, power and temperature |
| `osho-status` | Show safe Project Osho process/service/port state |

Approved targets are restricted to known nodes and inventory groups.

## One-time bootstrap

After the control-plane changes are merged to `master`, run this on `core-01` as the normal administrative user:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/prabhat324/p2-home-os/master/bootstrap/core/bootstrap.sh)
```

The bootstrap will:

1. install Ansible, Git, `jq`, `curl`, and SSH client tools;
2. create the unprivileged `p2runner` account on `core-01`;
3. create a dedicated ED25519 automation key;
4. create the unprivileged `p2ops` account on compute nodes and install that public key;
5. verify Ansible connectivity;
6. install the latest Linux ARM64 GitHub Actions runner; and
7. register it as `core-01` with the custom labels `core-01` and `control-plane`.

The bootstrap may request one-time SSH/sudo authentication for each compute node. It will also request the temporary GitHub self-hosted-runner registration token. The token is not saved in the repository.

## Request format

`ops/request.json` contains exactly one approved request:

```json
{
  "request_id": "example-001",
  "operation": "gpu-status",
  "target": "compute-03"
}
```

Every request ID must contain only letters, numbers, periods, underscores, or hyphens.

## Privileged actions

Do not give `p2runner` or `p2ops` broad passwordless sudo access.

When write actions are added, expose them through narrowly scoped root-owned helper commands and explicit sudoers entries. Examples may include restarting only a named Osho service or performing a specific deployment action. Each privileged action should have its own validation, logging, and rollback behavior.
