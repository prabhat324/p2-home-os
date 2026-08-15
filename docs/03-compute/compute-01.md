# compute-01

## Role

Primary GPU/application node for media processing, AI workloads, Project Osho, Immich-related processing, and production Jellyfin.

## Hardware

- HP ZBook Fury 17 G7 Mobile Workstation
- Intel Core i9-10885H
- 8 cores / 16 threads
- approximately 61 GiB usable RAM (64 GB installed)
- NVIDIA Quadro RTX 3000
- 6 GB GDDR6 VRAM
- NVIDIA power limit: 80 W
- 512 GB system NVMe
- 1 TB application/data NVMe
- Intel 1 GbE Ethernet
- Intel Wi-Fi 6 AX201
- HP 200 W power adapter

## Operating system

- Ubuntu 26.04 LTS
- production network uses wired Ethernet
- Wi-Fi is not used for the production path

## Network

- Hostname: `compute-01`
- LAN: `192.168.0.31`
- Tailscale: `100.65.64.4`
- Ethernet is the preferred/default route

## Storage

- `/srv` is hosted on the 1 TB XFS NVMe and is the primary application/compose area.
- Media is consumed from the Raspberry Pi storage node over NFSv4.2:

```text
192.168.0.203:/mnt/media -> /mnt/media
```

- The media mount is read-only on compute-01.
- The private photo library is exposed to Immich at `/mnt/photos-primary`; inside Immich it is mounted read-only.

## Confirmed responsibilities

- Production Jellyfin server
- NVIDIA hardware transcoding
- Ollama
- Open WebUI
- Project Osho primary worker/autopilot
- GPU-assisted AI/video processing
- Immich application/ML workload
- Whisper service used by the home voice stack
- local application/config backups

## Project Osho

Known service/process path:

```text
/srv/compose/osho-worker
/srv/compose/osho-worker/osho_autopilot.py
```

Known systemd unit:

```text
osho-autopilot.service
```

See [Project Osho](../12-project-osho/index.md) for the full pipeline documentation.

## GPU monitoring

```bash
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv
```

The GPU is shared by Ollama and Osho/other Python workloads, so VRAM pressure must be considered when troubleshooting latency.

## Operational notes

- The system has successfully run long Osho jobs overnight.
- Current/default/requested NVIDIA power limit has been verified at 80 W.
- HP BIOS was updated to S92 Ver. 01.24.02 (2026-05-07).
- Avoid unnecessary reboots while a long-running Osho stage is active; verify service health first.
