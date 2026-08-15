# Troubleshooting

## Start with the dependency chain

For a service that appears down, check in this order:

```text
hostname resolution -> network -> listener/process -> storage -> GPU/resources -> application logs
```

This avoids changing application configuration when the real problem is DNS, a missing mount, or resource contention.

## Hostname does not resolve

Symptoms:

```text
Could not resolve host: compute-02
Could not resolve hostname compute-02
```

Checks:

```bash
getent hosts compute-02
cat /etc/hosts
ping -c 2 compute-02
```

Keep host entries consistent across cluster nodes until local DNS fully owns these names.

## SSH alias fails but IP works

If:

```bash
ssh -p 8022 user@IP
```

works but an alias does not, inspect the local `~/.ssh/config` HostName/Port/User values and confirm the alias is not pointing to `127.0.0.1` or a stale address.

## Jellyfin cannot see media

On compute-01:

```bash
findmnt /mnt/media
ls -la /mnt/media | head
df -h /mnt/media
```

Then validate NFS on core-01. The production compute-01 mount is intentionally read-only.

## Immich cannot see photos

Inside the Immich environment verify:

```bash
findmnt /mnt/photos-primary
ls -la /mnt/photos-primary | head
```

The primary photo library is intentionally read-only in Immich. A delete action inside Immich should therefore not be assumed to remove the original filesystem object unless the mount/design changes.

## Osho appears stuck

```bash
pgrep -af 'osho_autopilot|hook_ranker_v5|retention_qa|uvicorn|ollama'
sudo journalctl -u osho-autopilot.service -n 100 --no-pager
nvidia-smi
```

Messages such as `NO SAFE V5 CANDIDATES` and `0 GENUINE APPROVALS — SKIPPED` are valid pipeline decisions, not crashes.

## GPU shows high utilization at low clocks/power

Check the whole GPU state rather than utilization alone:

```bash
nvidia-smi --query-gpu=pstate,utilization.gpu,power.draw,temperature.gpu,clocks.gr,clocks.sm,clocks.mem --format=csv
nvidia-smi -q -d POWER
nvidia-smi -q -d TEMPERATURE
```

compute-01's Quadro RTX 3000 has a verified 80 W power limit. Temperature/power/process context is more useful than one utilization percentage.

## Ollama is slow or partly CPU-bound

On 6 GB GPUs, models such as `qwen3:8b` may not fit fully in VRAM with the requested context. `ollama ps` may therefore show a CPU/GPU split. Reduce competing VRAM workloads or use a smaller model/context before assuming the GPU is malfunctioning.

## compute-03 worker copy fails

If remote `sudo` reports:

```text
A terminal is required to authenticate
```

create the privileged destination directory interactively first and give the deployment user correct ownership. An `rsync` following a failed directory creation will fail with `No such file or directory`.

## Voice service check

```bash
nc -vz compute-01 10300
nc -vz compute-02 10200
```

If both ports are reachable, troubleshoot Home Assistant voice-pipeline configuration rather than the network services.

## Storage write problems over Samba

Check filesystem mount options, effective ownership, Samba share permissions, and parent-directory permissions. A working SMB authentication does not guarantee the underlying mounted filesystem is writable by the Samba user.
