# P² Home OS

Welcome to the operating manual for the P² Home OS self-hosted infrastructure and compute platform.

## Platform overview

The system is no longer a single Raspberry Pi server. It is a distributed platform with clear node roles:

- **core-01 / media-server** — always-on storage and lightweight infrastructure;
- **compute-01** — primary GPU/application node for Jellyfin, AI, Immich, Whisper, and Project Osho;
- **compute-02** — lightweight orchestration/control-plane node and Piper TTS;
- **compute-03** — secondary GPU worker for Project Osho and local AI.

## Key workloads

- Jellyfin media streaming with NVIDIA transcoding;
- private photo management with Immich;
- Ollama / Open WebUI local AI;
- Home Assistant voice services using Whisper and Piper;
- Tailscale remote access;
- NFS/Samba storage;
- Project Osho automated short-form video production and YouTube publishing workflow;
- monitoring, maintenance, backup, and recovery procedures.

## Important addresses

| Host/service | Address |
|---|---|
| core-01 / media-server | `192.168.0.203` |
| compute-01 | `192.168.0.31` |
| compute-02 | `192.168.0.88` |
| compute-03 wired | `192.168.0.158` |
| Jellyfin | `http://compute-01:8096` |
| Open WebUI | `http://compute-01:3000` |
| Osho dashboard | `http://compute-02:8787` |
| Osho worker | `http://compute-03:8800` |
| Wyoming Whisper | `compute-01:10300` |
| Wyoming Piper | `compute-02:10200` |

Friendly `.home.arpa` names may still exist for legacy/core services; host-specific documentation is authoritative when service placement has changed.

## Storage

| Path | Role |
|---|---|
| core-01 `/mnt/media` | 8 TB media library |
| compute-01 `/mnt/media` | read-only NFS view of the media library |
| Immich `/mnt/photos-primary` | read-only 3 TB private photo library |
| `/srv/osho` | durable Project Osho state |

The 2 TB private-photo backup target remains designated but its current mount/scheduled-backup state must be verified before being treated as active coverage.

## Security rule

Never store passwords, OAuth secrets, API keys, access/refresh tokens, recovery codes, private SSH keys, cookies, or other credentials in this repository.

## Start here

- [System Overview](01-system-overview.md)
- [Hardware Inventory](02-hardware-inventory.md)
- [Network](03-network.md)
- [Storage](04-storage.md)
- [Services](05-services.md)
- [Maintenance](08-maintenance.md)
- [Troubleshooting](10-troubleshooting.md)
- [Project Osho](12-project-osho/index.md)
