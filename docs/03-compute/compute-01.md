# compute-01

## Role

High-performance compute node for media processing and AI workloads.

## Hardware

- HP ZBook Fury 17 G7
- Intel Core i9-10885H
- 8 cores / 16 threads
- 64 GB DDR4 RAM
- NVIDIA Quadro RTX 3000
- 6 GB GDDR6 VRAM
- 512 GB SK hynix NVMe
- 1 TB KIOXIA NVMe
- Intel 1 GbE Ethernet
- Intel Wi-Fi 6 AX201

## Firmware Status

- UEFI enabled
- Secure Boot disabled
- Intel VT-x enabled
- Intel VT-d enabled
- Wake-on-LAN enabled
- Video memory left at 64 MB

## Planned Operating System

Ubuntu Server 24.04 LTS

## Planned Responsibilities

- Jellyfin
- NVIDIA hardware transcoding
- Ollama
- Open WebUI
- Immich machine learning
- Whisper
- Frigate AI
- ComfyUI
- Development workloads

## Planned Storage Layout

### 512 GB NVMe

- Ubuntu Server
- Boot
- System files
- Core configuration

### 1 TB NVMe

- Docker application data
- AI models
- Jellyfin cache
- Jellyfin transcodes
- Immich cache
- Temporary processing data
