# System Overview

## Purpose

P² Home OS is a distributed self-hosted platform for:

- home media streaming;
- private photo management;
- AI/LLM workloads;
- Project Osho automated video production;
- smart-home control;
- storage and file sharing;
- monitoring and health checks;
- remote access;
- voice-assistant services.

## Current architecture

```text
Internet / home LAN
        |
        +-- core-01 / media-server (Raspberry Pi 5)
        |     storage + always-on infrastructure
        |
        +-- compute-01 (HP ZBook Fury 17 G7)
        |     primary GPU/application node
        |
        +-- compute-02
        |     lightweight control plane / dashboard / Piper
        |
        +-- compute-03
              secondary GPU worker
```

## Nodes

### core-01 / media-server

- Raspberry Pi 5, 8 GB
- LAN `192.168.0.203`
- Tailscale `100.67.245.78`
- physically hosts the 8 TB Seagate media drive at `/mnt/media`
- exports media to compute-01 using NFSv4.2
- retains lightweight infrastructure/storage responsibilities
- production Jellyfin is no longer hosted here

### compute-01

- HP ZBook Fury 17 G7
- Ubuntu 26.04 LTS
- LAN `192.168.0.31`
- Tailscale `100.65.64.4`
- Quadro RTX 3000 6 GB
- 64 GB RAM
- production Jellyfin with NVIDIA transcoding
- Ollama / Open WebUI
- Immich-related services
- Whisper
- Project Osho primary worker/autopilot

### compute-02

- LAN `192.168.0.88`
- Project Osho dashboard/control plane on TCP `8787`
- Wyoming Piper TTS on TCP `10200`
- intentionally kept lightweight

### compute-03

- preferred wired LAN `192.168.0.158`
- RTX 2060 6 GB
- Project Osho worker API on TCP `8800`
- Ollama with `qwen3:8b`
- secondary GPU capacity

## Storage

### Media

The 8 TB Seagate remains attached to core-01 at:

```text
/mnt/media
```

compute-01 consumes it read-only via NFSv4.2:

```text
192.168.0.203:/mnt/media -> /mnt/media
```

### Photos

The 3 TB private photo library is used as the primary photo source and is exposed to Immich at `/mnt/photos-primary` read-only inside the Immich environment.

### Backup

The 2 TB drive remains designated for private-photo backup. Treat it as planned/unverified until its current mount and scheduled-backup state are explicitly validated.

## Remote access

Tailscale is the preferred remote-access layer. Internal services should not be exposed directly to the public internet unless a specific authenticated design requires it.

## Operating principle

Heavy GPU/media work belongs on compute-01 and compute-03. Always-on storage/infrastructure belongs on core-01. Lightweight orchestration belongs on compute-02. This separation reduces contention and makes failures easier to isolate.
