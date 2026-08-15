# P² Home OS

P² Home OS is a self-hosted home infrastructure and compute platform spanning storage, media, AI, smart-home services, and Project Osho automation.

## Current nodes

### core-01 / media-server

- Raspberry Pi 5, 8 GB
- Debian/Raspberry Pi OS family
- LAN `192.168.0.203`
- 8 TB Seagate media storage at `/mnt/media`
- NFS/Samba and lightweight always-on infrastructure
- Home Assistant / dashboard / DNS / monitoring roles
- Tailscale remote access
- Production Jellyfin has been migrated off this node to compute-01

### compute-01

- HP ZBook Fury 17 G7
- Ubuntu 26.04 LTS
- LAN `192.168.0.31`
- Quadro RTX 3000 6 GB
- 64 GB RAM
- Production Jellyfin + NVIDIA transcoding
- Ollama / Open WebUI
- Immich-related GPU/application workload
- Whisper
- Project Osho primary worker/autopilot

### compute-02

- LAN `192.168.0.88`
- Lightweight orchestration/control-plane node
- Project Osho dashboard/controller (`8787/tcp`)
- Wyoming Piper TTS (`10200/tcp`)

### compute-03

- Wired LAN `192.168.0.158`
- RTX 2060 6 GB
- Project Osho worker API (`8800/tcp`)
- Ollama / `qwen3:8b`
- Additional GPU capacity for distributed workloads

## Storage model

- 8 TB media library remains physically attached to core-01 and is exported read-only to compute-01 over NFSv4.2.
- 3 TB private photo library is used as the primary Immich external library and is mounted read-only inside Immich.
- 2 TB backup drive remains part of the private-photo backup plan; only document it as active after mount/backup verification.

## Principles

- Documentation first
- Version controlled
- Reproducible
- Secure by default
- Observable
- Recoverable
- Separate control plane from heavy compute
- Never commit credentials or secrets

## Documentation

The MkDocs site under `docs/` is the operating manual. Project Osho has a dedicated section under `docs/12-project-osho/`.
