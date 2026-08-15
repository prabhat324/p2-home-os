# Maintenance

## Routine checks

### All nodes

```bash
hostname
uptime
systemctl --failed
df -h
ip -br addr
```

### core-01

```bash
findmnt /mnt/media
df -h /mnt/media
systemctl status smbd --no-pager || true
systemctl status nfs-server --no-pager || true
tailscale status
```

### compute-01

```bash
findmnt /mnt/media
nvidia-smi
docker ps
systemctl status osho-autopilot.service --no-pager || true
tailscale status
```

### compute-02

```bash
ss -lntp | grep -E ':8787|:10200'
docker ps
```

### compute-03

```bash
nvidia-smi
ollama ps
ss -lntp | grep ':8800'
pgrep -af 'uvicorn|ollama|osho'
```

## GPU health

Useful compact query:

```bash
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv
```

On compute-01 the Quadro RTX 3000 operates with an 80 W power limit. Avoid rebooting simply because a long-running GPU job is active; first check temperatures, power, process state, and logs.

## Storage health API

A P² storage health API was installed on core-01 on 2026-08-06.

Known service:

```text
p2-health-api.service
```

Historically documented endpoint:

```text
http://192.168.0.203:8787/api/storage
```

Because compute-02 now also uses port 8787 for the Osho dashboard, always qualify the **host** when discussing port 8787.

Checks:

```bash
sudo systemctl status p2-health-api --no-pager
curl http://127.0.0.1:8787/api/storage
sudo journalctl -u p2-health-api --since today --no-pager
```

## Updates

- Apply OS and container updates deliberately, one node at a time.
- Preserve at least one working control/storage path while updating another node.
- Do not upgrade GPU drivers immediately before an important render/transcode run.
- Record significant firmware, driver, service-placement, and storage changes in the changelog.

## Name resolution

Cluster hostnames are operational dependencies. Verify periodically:

```bash
getent hosts media-server compute-01 compute-02 compute-03
```

Do not diagnose an application as failed until hostname resolution and TCP reachability are confirmed.
