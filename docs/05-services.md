# Services

## Service placement

P² Home OS deliberately splits lightweight infrastructure from GPU-heavy workloads.

| Service / workload | Host | Status / port |
|---|---|---|
| Jellyfin | compute-01 | Production, `8096/tcp`, NVIDIA transcoding |
| Ollama | compute-01 | Active local LLM service |
| Open WebUI | compute-01 | Active, `3000/tcp` |
| Wyoming Whisper | compute-01 | Reachable on `10300/tcp` |
| Immich | compute-01 | Active photo-management stack; primary library mounted read-only |
| Project Osho autopilot | compute-01 | `osho-autopilot.service` |
| Project Osho dashboard | compute-02 | `/srv/compose/osho-dashboard`, `8787/tcp` |
| Wyoming Piper | compute-02 | `10200/tcp`, `en_US-lessac-medium` |
| Project Osho worker API | compute-03 | Uvicorn, `8800/tcp` |
| Ollama / qwen3:8b | compute-03 | Secondary AI workload |
| NFS/Samba media storage | core-01 | Exposes `/mnt/media` |
| Tailscale | core-01 + compute nodes as installed | Remote access |
| Home Assistant / lightweight infrastructure | core-01 | Always-on role |

## Jellyfin

Production Jellyfin was migrated from the Raspberry Pi to compute-01 so the Quadro RTX 3000 can handle hardware transcoding.

Media remains physically on core-01 and is mounted read-only on compute-01 over NFSv4.2.

Checks:

```bash
curl -I http://compute-01:8096
nvidia-smi
findmnt /mnt/media
```

## Immich

Immich indexes the private photo library through:

```text
/mnt/photos-primary
```

The external library is mounted read-only inside Immich. This protects originals from application-side deletion and is an intentional design choice.

## Ollama and Open WebUI

compute-01 is the primary local AI node. compute-03 also runs Ollama for Osho/worker experiments. On 6 GB GPUs, model residency and VRAM contention must be monitored.

## Voice stack

Confirmed network checks:

```text
Whisper: compute-01:10300
Piper:   compute-02:10200
```

Piper container/service uses the Wyoming protocol with voice `en_US-lessac-medium`.

## Project Osho

See the dedicated [Project Osho documentation](12-project-osho/index.md).

Key placement:

```text
compute-01 -> primary processing/autopilot
compute-02 -> dashboard/controller
compute-03 -> secondary GPU worker
```

## Storage services

core-01 remains the physical media-storage node and should provide stable NFS/Samba service without taking on GPU-heavy application workloads.

## Security

Do not commit application passwords, API tokens, OAuth secrets, Tailscale auth keys, YouTube tokens, or private SSH keys. Use environment files or secret stores outside Git and commit only sanitized examples.
