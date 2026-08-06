# P² Home OS System Overview

## Purpose

P² Home OS is a self-hosted home infrastructure platform built around two primary nodes:

- `core-01` — low-power, always-on infrastructure and storage
- `compute-01` — high-performance GPU compute and media processing

## Architecture

### core-01

Hardware:
- Raspberry Pi 5
- 8 GB RAM

Responsibilities:
- Home Assistant
- Homepage
- AdGuard Home
- Caddy
- Samba
- Tailscale
- Storage management
- Backups
- Monitoring
- Lightweight camera services

### compute-01

Hardware:
- HP ZBook Fury 17 G7
- Intel Core i9-10885H
- 64 GB RAM
- NVIDIA Quadro RTX 3000 6 GB
- 512 GB NVMe
- 1 TB NVMe

Planned operating system:
- Ubuntu Server 24.04 LTS

Responsibilities:
- Jellyfin
- GPU transcoding
- Ollama
- Open WebUI
- Immich machine learning
- Whisper
- Frigate AI
- Other GPU-intensive workloads

## Design Principles

- Documentation first
- Infrastructure as code
- Version controlled configuration
- Modular services
- Reproducible deployments
- Health monitoring
- Automated backups
- Recoverable nodes
