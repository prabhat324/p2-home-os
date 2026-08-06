# core-01

## Role

Primary always-on infrastructure node for P² Home OS.

## Hardware

- Raspberry Pi 5
- 8 GB RAM
- Raspberry Pi OS Lite / Debian 13
- Hostname currently: `media-server`
- Planned logical name: `core-01`

## Core Services

- Jellyfin — temporary; planned migration to compute-01
- Samba
- Homepage
- Home Assistant
- AdGuard Home
- Caddy
- Navidrome
- Scrypted
- go2rtc
- Tailscale
- P² storage health API
- P² CLI

## Storage

- `/mnt/media` — 8 TB Seagate media drive
- `/mnt/family` — planned 3 TB family-photo primary
- `/mnt/backup` — planned 2 TB family-photo backup

## Responsibilities

- Always-on infrastructure
- Storage hosting
- Home automation
- DNS
- Reverse proxy
- Monitoring
- Backup orchestration
- Health checks
