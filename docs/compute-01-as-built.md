# P² Home OS — `compute-01` As-Built Runbook

**Version:** 1.3  
**Status:** Operational  
**Updated:** 14 August 2026

This runbook records the current verified role of `compute-01`. It supersedes older statements that described Jellyfin, Ollama, Open WebUI, Immich/Whisper, or Project Osho as merely planned.

## Role

`compute-01` is the primary GPU/application node. Storage and lightweight infrastructure remain separated onto other nodes.

```text
core-01 / media-server                 compute-01
Raspberry Pi 5                         HP ZBook Fury 17 G7
storage + infrastructure  --NFS ro-->  GPU + applications
                                          |
                                          +-- Jellyfin
                                          +-- Ollama / Open WebUI
                                          +-- Immich workload
                                          +-- Whisper
                                          +-- Project Osho
```

## Verified hardware and OS

| Component | State |
|---|---|
| System | HP ZBook Fury 17 G7 Mobile Workstation |
| CPU | Intel Core i9-10885H |
| Memory | ~61 GiB usable / 64 GB installed |
| GPU | NVIDIA Quadro RTX 3000, 6144 MiB |
| GPU power limit | 80 W |
| OS | Ubuntu 26.04 LTS |
| Kernel observed | `7.0.0-29-generic` |
| BIOS | S92 Ver. 01.24.02, 2026-05-07 |
| Power adapter | HP 200 W |

## Network

- Hostname: `compute-01`
- Ethernet: `192.168.0.31`
- Tailscale: `100.65.64.4`
- Production path: wired Ethernet
- Wi-Fi: not used for production traffic

Verify:

```bash
ip -br addr
ip route
tailscale status
getent hosts media-server compute-02 compute-03
```

## Storage

### Local

- OS NVMe: ~512 GB
- `/srv` application NVMe: ~1 TB, XFS
- Application/compose data belongs under `/srv`

### Media

Source:

```text
192.168.0.203:/mnt/media
```

Client mount:

```text
/mnt/media
```

The NFSv4.2 mount is read-only and is used by Jellyfin.

### Photos

Immich sees the primary private photo library at:

```text
/mnt/photos-primary
```

The library is mounted read-only inside Immich to protect originals.

## Core services

### Jellyfin

- Production host: compute-01
- Port: `8096/tcp`
- NVIDIA transcoding verified
- Media mapping is read-only

### Ollama / Open WebUI

- Ollama: local LLM backend
- Open WebUI: `3000/tcp`
- GPU memory is shared with other compute workloads

### Whisper

Wyoming Whisper is reachable on:

```text
10300/tcp
```

and is used by the Home Assistant voice stack.

### Project Osho

Application path:

```text
/srv/compose/osho-worker
```

Autopilot:

```text
/srv/compose/osho-worker/osho_autopilot.py
osho-autopilot.service
```

compute-01 performs the primary heavy Osho stages while compute-02 handles dashboard/control-plane duties and compute-03 provides secondary GPU capacity.

## GPU operations

```bash
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv
```

Ollama and Python/Osho processes may run concurrently. High utilization must be interpreted together with clocks, power, temperature, and VRAM pressure.

## Backups

Local application/config backups exist under:

```text
/srv/backups/compute-01
```

They protect against configuration mistakes and aid rebuilds but are not sufficient protection against total node/disk loss. Important state must also have off-host copies.

## Security and Git

- SSH key authentication is preferred.
- Root SSH login should remain disabled.
- Docker/application secrets must stay outside Git.
- The GitHub repository is the source of truth for non-secret documentation/configuration.
- Never commit OAuth tokens, API keys, passwords, private keys, or runtime secret files.

## Health check

```bash
hostname
uptime
systemctl --failed
findmnt /mnt/media
findmnt /mnt/photos-primary || true
docker ps
nvidia-smi
systemctl status osho-autopilot.service --no-pager || true
```

## Current design rule

Do not move control-plane responsibilities onto compute-01 merely because it has the most horsepower. Keep compute-01 focused on heavy GPU/application work so long-running Osho, Jellyfin, Immich, and AI workloads do not compete with scheduling/dashboard availability.
