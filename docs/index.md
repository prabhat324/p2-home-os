# P² Home OS

Welcome to the operations manual for the P² home server and smart-home platform.

## Platform Overview

The system runs on a Raspberry Pi 5 and currently provides:

- Jellyfin movie and television streaming
- Navidrome personal music streaming
- Home Assistant smart-home management
- Scrypted camera integration
- AdGuard Home network-wide DNS filtering
- Caddy internal reverse proxy
- Homepage central dashboard
- Samba network file sharing
- Tailscale remote access
- Docker application hosting
- Server and service monitoring

## Main Addresses

| Service | Address |
|---|---|
| Dashboard | `http://dashboard.home.arpa` |
| Jellyfin | `http://jellyfin.home.arpa` |
| Music | `http://music.home.arpa` |
| Home Assistant | `http://192.168.0.203:8123` |
| Cameras | `http://cameras.home.arpa` |
| AdGuard | `http://adguard.home.arpa` |
| Documentation | `http://docs.home.arpa` |

## Storage

| Mount | Purpose |
|---|---|
| `/mnt/media` | Movies, television, music and downloads |
| `/mnt/family` | Planned Family Vault |
| `/mnt/backup` | Planned Family Vault backup |

## Important Rule

Never store passwords, API keys, access tokens, recovery codes or Home Assistant secrets in this documentation repository.
