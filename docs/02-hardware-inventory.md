# Hardware Inventory

## Compute and infrastructure

| Node | Hardware | Primary role |
|---|---|---|
| `core-01` / `media-server` | Raspberry Pi 5, 8 GB | Always-on storage/infrastructure |
| `compute-01` | HP ZBook Fury 17 G7, i9-10885H, 64 GB RAM, Quadro RTX 3000 6 GB | Primary GPU/app node, Jellyfin, AI, Immich, Osho |
| `compute-02` | Compute node, no NVIDIA GPU currently required/documented | Osho control plane/dashboard, Piper TTS |
| `compute-03` | NVIDIA GeForce RTX 2060 6 GB | Secondary Osho/AI GPU worker |

## Storage

| Device | Current/design role |
|---|---|
| Seagate Expansion Desktop 8 TB | Media library; physically attached to core-01 at `/mnt/media` |
| WD 3 TB | Private primary photo library; exposed read-only to Immich as `/mnt/photos-primary` |
| WD 2 TB | Designated photo backup drive; verify current mount/schedule before treating as active |

## Networking

- Home LAN: `192.168.0.0/24`
- core-01: `192.168.0.203`
- compute-01: `192.168.0.31`
- compute-02: `192.168.0.88`
- compute-03 preferred wired address: `192.168.0.158`
- `switch-01`: Cisco SG350-10MP, existing active wired switch.
- `switch-02`: Juniper EX2300-C-12P, management IP `192.168.0.65`.
- Tailscale provides remote access.

## Smart-home / media clients

Known environment includes Apple TV 4K, NVIDIA Shield TV Pro, Samsung TVs, Aqara/Ring/Ecobee and other home devices. Device integrations should be documented as confirmed when actively connected to Home Assistant rather than inferred from ownership alone.
