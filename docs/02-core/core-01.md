# core-01 / media-server

## Role

Primary always-on infrastructure and storage node for P² Home OS.

## Hardware

- Raspberry Pi 5
- 8 GB RAM
- Debian/Raspberry Pi OS family
- Current hostname: `media-server`
- Logical infrastructure role: `core-01`

## Network

- LAN: `192.168.0.203`
- Tailscale: `100.67.245.78`

## Current responsibilities

- physical host for the 8 TB Seagate media drive;
- NFS/Samba storage services;
- lightweight always-on infrastructure;
- Home Assistant / dashboard / DNS / monitoring roles where deployed;
- Tailscale remote access;
- storage/health checks.

## Jellyfin status

Production Jellyfin has been migrated to compute-01. core-01 remains the storage source for the media library rather than the primary playback/transcoding host.

## Storage

Primary media mount:

```text
/mnt/media
```

compute-01 consumes the media library read-only over NFSv4.2:

```text
192.168.0.203:/mnt/media -> /mnt/media
```

## Service-placement principle

Keep lightweight and always-on services here. Move GPU-heavy transcoding, AI inference, photo ML, and Project Osho processing to compute nodes.

## Health checks

```bash
findmnt /mnt/media
df -h /mnt/media
systemctl --failed
systemctl status nfs-server --no-pager || true
systemctl status smbd --no-pager || true
tailscale status
```
