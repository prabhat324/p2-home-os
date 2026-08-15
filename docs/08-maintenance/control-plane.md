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
- `p2ops` is not granted broad sudo privileges.
- No SSH port is exposed to the Internet for ChatGPT.
- No credentials, private keys, registration tokens, or command results are committed to the repository.
- The workflow only triggers when `ops/request.json` changes on the `ops-control` branch.
- The dispatcher rejects arbitrary shell commands and unknown targets.
- Privileged operations are exposed only through root-owned fixed-action helpers and exact sudoers entries.

GitHub Actions logs for this public repository can reveal the output of approved checks. Keep operations limited to non-sensitive operational data.

## Approved read-only operations

| Operation | Purpose |
| --- | --- |
| `ping` | Verify Ansible/SSH connectivity |
| `status` | Show uptime, load, memory and root filesystem usage |
| `gpu-status` | Show NVIDIA GPU utilization, memory, power and temperature |
| `osho-status` | Show safe Project Osho process/service/port state |
| `dashboard-diagnose` | Check compute-02 dashboard routes, backups and deployment capability |
| `osho-publish-audit` | Compare Autopilot source-state counts with durable YouTube receipt identities |

Approved targets are restricted to known nodes and inventory groups.

## Approved scoped write operations

### compute-01: `osho-maintenance`

The Git operation invokes only:

```text
/usr/local/sbin/p2ops-osho-maintenance apply-safe-fixes
```

The root-owned helper permits fixed actions for:

- status;
- restarting `osho-dashboard-heartbeat.service`;
- repairing the Faster-Whisper model-cache ownership/permissions;
- applying those two safe fixes together.

It does not expose arbitrary shell, general `systemctl`, Autopilot control, process killing, or general sudo.

### compute-02: `dashboard-deploy`

After the one-time compute-02 helper bootstrap, the Git operation invokes only:

```text
/usr/local/sbin/p2ops-osho-dashboard deploy-master
```

The helper downloads the fixed Project Osho dashboard files from `prabhat324/p2-home-os@master`, validates them, backs up the current deployed source, preserves the existing Compose file and runtime database, rebuilds the dashboard container, and checks `/health`.

It does not give `p2ops` general Docker or sudo access.

## One-time control-plane bootstrap

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

## One-time scoped helper bootstraps

### compute-01 Osho maintenance helper

Install locally on compute-01 as `psquare`:

```bash
cd ~/projects/p2-home-os
bash bootstrap/compute/install-osho-maintenance-helper.sh
```

### compute-02 dashboard deployment helper

Install locally on compute-02 as `psquare`:

```bash
curl -fsSL https://raw.githubusercontent.com/prabhat324/p2-home-os/master/bootstrap/compute/install-osho-dashboard-helper.sh \
  | bash
```

To install it and perform the first dashboard deploy in the same local bootstrap:

```bash
curl -fsSL https://raw.githubusercontent.com/prabhat324/p2-home-os/master/bootstrap/compute/install-osho-dashboard-helper.sh \
  | OSHO_DASHBOARD_DEPLOY_NOW=1 bash
```

After these one-time installs, the corresponding approved actions can be triggered through GitHub without interactive SSH administration.

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

## Privileged-action policy

Do not give `p2runner` or `p2ops` broad passwordless sudo access.

Every write action must use a narrowly scoped root-owned helper and explicit sudoers command entries. Each helper should:

1. accept only fixed action names;
2. reject arbitrary arguments;
3. operate only on predefined services/paths;
4. validate inputs and configuration before changes;
5. preserve or create rollback state where practical; and
6. emit enough non-sensitive output for GitHub Actions verification.
