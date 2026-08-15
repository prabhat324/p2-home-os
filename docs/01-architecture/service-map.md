# Service Map

## core-01 / media-server

Primary function: always-on storage and infrastructure.

```text
/mnt/media                 8 TB media storage
NFS / Samba                media/file sharing
Home Assistant             smart-home control
Tailscale                  remote access
p2-health-api              storage health/status
```

Production Jellyfin no longer belongs on this node.

## compute-01

Primary function: heavy GPU/application workloads.

```text
Jellyfin            :8096   production media server / NVIDIA transcoding
Open WebUI          :3000   local AI interface
Ollama                       local LLM backend
Wyoming Whisper     :10300  speech-to-text
Immich                       private photo-management workload
Project Osho                 primary worker/autopilot
```

Durable/application data belongs primarily under `/srv`.

## compute-02

Primary function: lightweight orchestration.

```text
Project Osho dashboard/controller  :8787
Wyoming Piper                       :10200
```

compute-02 should remain responsive even when GPU workers are saturated.

## compute-03

Primary function: secondary GPU worker.

```text
Project Osho worker API     :8800
Ollama / qwen3:8b
RTX 2060 6 GB
```

## Dependency relationships

```text
Jellyfin -> compute-01 -> NFS -> core-01:/mnt/media
Immich -> compute-01 -> read-only /mnt/photos-primary
Home Assistant voice -> Whisper(compute-01) + Piper(compute-02)
Osho controller(compute-02) -> workers(compute-01, compute-03)
Osho publisher -> durable /srv/osho/youtube/receipts
```

## Security boundary

Configuration can be version controlled; secrets cannot. OAuth tokens, API keys, passwords, private keys, cookies, and Tailscale/YouTube credentials remain outside Git.
