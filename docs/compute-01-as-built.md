# P² Home OS — `compute-01` As-Built Operations Runbook

**Version:** 1.2  
**Status:** Compute node build complete and operational  
**As-built date:** 8 August 2026  
**Node:** `compute-01`  
**Repository:** `prabhat324/p2-home-os` (private GitHub)  
**Working copy:** `/home/psquare/projects/p2-home-os`

> This document records the verified state of `compute-01`. Planned or deferred work is explicitly marked as such. It supersedes earlier compute-node statements that described Wi-Fi as the primary network, the NFS media mount as read/write, Jellyfin as pending, or Ollama/Open WebUI as only planned.

## 1. Role and Architecture

`compute-01` is the GPU/application node in P² Home OS. It runs heavier application and AI workloads while media storage remains on the storage/infrastructure node.

```text
                         Private GitHub
                    prabhat324/p2-home-os
                              |
                +-------------+-------------+
                |                           |
        core-01 / media-server          compute-01
          Raspberry Pi 5             HP ZBook Fury 17 G7
                |                           |
        Infrastructure + Storage       GPU / Applications
                |                           |
        8 TB media storage          Docker + NVIDIA runtime
                |                           |
                +------ NFSv4.2 ---------->|
                       read-only
```

Current compute-node responsibilities:

- Docker application host.
- NVIDIA GPU compute/runtime host.
- Jellyfin application server and GPU transcoding.
- Ollama local model inference.
- Open WebUI AI front end.
- Read-only consumer of the shared media library over NFS.
- Local configuration/application-state backup generation.
- Tailscale and SSH administration endpoint.

Design rules:

- Persistent application data belongs under `/srv/appdata`.
- Compose definitions belong under `/srv/compose` and should be represented in Git where practical.
- Media mounted from the storage node is read-only on `compute-01`.
- Secrets, runtime databases, caches, downloaded models, and generated application data do not belong in Git.
- Changes follow: **implement → verify → document → commit**.
- Prefer rollback-safe, parallel migration over destructive in-place changes.

## 2. Hardware and Operating System

| Component | Verified state |
|---|---|
| System | HP ZBook Fury 17 G7 Mobile Workstation |
| Hardware SKU | `300L4UC#ABA` |
| Firmware | S92 Ver. 01.24.02 |
| Firmware date | 2026-05-07 |
| CPU | Intel Core i9-10885H |
| Memory | 61 GiB usable (~64 GB installed) |
| GPU | NVIDIA Quadro RTX 3000 Mobile / Max-Q |
| GPU VRAM | 6144 MiB |
| OS | Ubuntu 26.04 LTS |
| Kernel | `7.0.0-29-generic` |
| Architecture | x86-64 |

Firmware/build decisions:

- Secure Boot disabled for NVIDIA deployment.
- Intel VT-x and VT-d enabled.
- Always-on headless-server behavior configured.
- Lid-close sleep disabled.
- Suspend/hibernate behavior hardened for the server role.

## 3. Storage Layout

### OS NVMe

- Device: `/dev/nvme0n1`
- Model: SK hynix PC601
- Approximate raw capacity: 512 GB
- Root filesystem: ext4
- Mount: `/`
- SMART: **PASSED**
- Final audit utilization: about 29 GB of 468 GB (7%)

### Service NVMe

- Device: `/dev/nvme1n1`
- Model: KIOXIA KXG60ZNV1T02
- Approximate raw capacity: 1 TB
- Filesystem: XFS
- Label: `P2_SRV`
- Mount: `/srv`
- SMART: **PASSED**
- Final audit utilization: about 23 GB of 954 GB (3%)

### Standard `/srv` layout

```text
/srv/
├── appdata/
│   ├── jellyfin/
│   ├── ollama/
│   └── open-webui/
├── backups/
│   └── compute-01/
├── compose/
│   ├── jellyfin/
│   └── ai/
├── cache/
├── logs/
├── models/
├── scripts/
├── transcode/
└── downloads/
```

The rebuild/bootstrap design must never silently place service data on the OS filesystem if `/srv` is expected but not mounted.

## 4. Network State

### Wired Ethernet

- Interface: `enp0s31f6`
- LAN address: `192.168.0.31/24`
- Ethernet MAC: `6c:02:e0:c9:46:bc`
- Default gateway: `192.168.0.1`
- State: active and preferred

### Wi-Fi

- Interface: `wlp0s20f3`
- MAC: `04:6c:59:2b:45:a3`
- State: down / not used for production traffic

### Tailscale

- `compute-01`: `100.65.64.4`
- `media-server`: `100.67.245.78`
- Tailscale is enabled and survives reboot.

### DHCP reservation

**Pending:** reserve `192.168.0.31` in the router using Ethernet MAC `6c:02:e0:c9:46:bc`.

Until that reservation is made, treat `192.168.0.31` as the current verified address rather than a guaranteed permanent address.

## 5. NFS Media Mount

Source:

```text
192.168.0.203:/mnt/media
```

Client mount:

```text
/mnt/media
```

Verified state:

- NFS 4.2.
- Read-only on `compute-01`.
- Survives reboot.
- systemd automount enabled.
- Jellyfin consumes the media library through this mount.
- Final audit: about 7.3 TB total, 829 GB used, 6.5 TB available.

`/etc/fstab`:

```fstab
192.168.0.203:/mnt/media /mnt/media nfs4 ro,_netdev,nofail,x-systemd.automount,x-systemd.device-timeout=10,timeo=600,retrans=2 0 0
```

Storage-node export:

```exports
/mnt/media 192.168.0.31(ro,sync,no_subtree_check)
```

### rpcbind

`compute-01` is an NFSv4.2 client and does not require the legacy RPC portmapper for this mount.

Verified final state:

```text
rpcbind.service: disabled / inactive
rpcbind.socket:  disabled / inactive
TCP/UDP 111:     closed
NFSv4.2 mount:   operational
```

## 6. Docker Platform

Verified:

- Docker Engine operational.
- Docker Compose operational.
- NVIDIA Container Toolkit operational.
- GPU access from containers verified.
- Docker log driver changed from `json-file` to `local`.

`/etc/docker/daemon.json`:

```json
{
  "runtimes": {
    "nvidia": {
      "args": [],
      "path": "nvidia-container-runtime"
    }
  },
  "log-driver": "local"
}
```

Backup retained:

```text
/etc/docker/daemon.json.backup-2026-08-07
```

Current containers:

| Container | Purpose | Host exposure |
|---|---|---|
| `jellyfin` | Media server | TCP `8096` |
| `ollama` | Local LLM inference | internal only (`11434/tcp`) |
| `open-webui` | AI web interface | TCP `3000` |

Current Docker networks include `ai_default`, `jellyfin_default`, `p2-network`, plus standard Docker networks.

## 7. Jellyfin

Persistent paths:

```text
/srv/appdata/jellyfin/config
/srv/appdata/jellyfin/cache
/srv/compose/jellyfin/compose.yaml
/srv/compose/jellyfin/.env
```

Container state:

- Image: `jellyfin/jellyfin:latest`
- Host port: `8096`
- Media mapping: `/mnt/media:/media:ro`
- NVIDIA GPU reservation enabled
- UID/GID: `1000`
- `NVIDIA_VISIBLE_DEVICES=all`
- `NVIDIA_DRIVER_CAPABILITIES=compute,video,utility`

Access:

```text
LAN:       http://192.168.0.31:8096
Tailscale: http://100.65.64.4:8096
```

GPU/transcoding verification:

- CUDA hardware acceleration observed.
- NVIDIA decode path observed.
- CUDA scaling/filtering observed.
- `hevc_nvenc` encoding observed.
- Subtitle burn-in path exercised.
- FFmpeg process visible in `nvidia-smi`.

Validated source example: *Life of Pi (2012)*, HEVC Main 10, 3840×2160, 10-bit.

Hardware settings enabled where supported:

- H.264
- HEVC
- MPEG-2
- MPEG-4
- VC-1
- VP8
- VP9
- HEVC 10-bit
- VP9 10-bit
- Enhanced NVDEC
- Hardware encoding
- HEVC output
- Tone mapping

Not enabled:

- AV1 output/decode on this Turing-generation GPU
- HEVC RExt

**Deferred:** explicit HDR → SDR tone-mapping validation.

## 8. Local AI Stack

Persistent paths:

```text
/srv/appdata/ollama
/srv/appdata/open-webui
/srv/compose/ai/compose.yaml
```

### Ollama

- Image: `ollama/ollama:latest`
- Container port: `11434`
- Not published to LAN
- NVIDIA GPU reservation enabled
- Verified model: `qwen3.5:4b`

Observed under inference:

- ~3.1 GB model
- 100% GPU placement
- context 4096
- ~3.8 GB VRAM used
- ~88% GPU utilization

### Open WebUI

- Image: `ghcr.io/open-webui/open-webui:main`
- Host port: `3000`
- Container port: `8080`
- `OLLAMA_BASE_URL=http://ollama:11434`
- Verified to return model results successfully.

Access:

```text
http://192.168.0.31:3000
```

**Deferred hardening:** after DHCP reservation, review whether port `3000` should remain LAN-wide or become Tailscale/private-only.

## 9. NVIDIA Platform

Verified GPU:

```text
NVIDIA Quadro RTX 3000
VRAM: 6144 MiB
```

NVIDIA Container Toolkit is configured and Docker GPU access is proven.

Final health-audit idle state:

```text
GPU temperature: 39 C
GPU utilization: 0%
VRAM used:       1 MiB
VRAM total:      6144 MiB
Power draw:      ~5.9 W
```

Current GPU workloads:

- Jellyfin hardware transcoding
- Ollama inference

Potential later workloads include Immich ML, Whisper, Frigate/object detection, and other GPU-assisted services.

## 10. SSH and Administrative Access

Verified intended effective SSH policy:

```text
PermitRootLogin no
X11Forwarding no
MaxAuthTries 3
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
```

Hardening drop-ins:

```text
/etc/ssh/sshd_config.d/99-compute-hardening.conf
/etc/ssh/sshd_config.d/00-compute-auth.conf
```

### UFW

Current rules:

```text
22/tcp                     ALLOW IN    192.168.0.0/24   # SSH LAN
22/tcp on tailscale0       ALLOW IN    Anywhere         # SSH Tailscale
22/tcp (v6) on tailscale0  ALLOW IN    Anywhere (v6)    # SSH Tailscale
```

### Docker/UFW note

Docker-published ports should not be assumed to obey ordinary UFW INPUT behavior.

Current published application ports:

```text
3000/tcp  Open WebUI
8096/tcp  Jellyfin
```

Jellyfin LAN exposure is intentional. Open WebUI exposure should be reviewed after DHCP reservation.

## 11. Automatic Updates and Health Monitoring

- `unattended-upgrades` installed/enabled.
- apt timers active.
- `smartmontools`/`smartd` enabled.
- Both NVMe devices report SMART **PASSED**.
- No failed systemd units at final audit.

Final thermal baseline:

```text
CPU package: ~40 C
CPU cores:   ~38–40 C
NVMe:        ~32 C
PCH:         ~43 C
GPU:         39 C
```

## 12. Backup and Recovery

Local backup directory:

```text
/srv/backups/compute-01
```

Backup script:

```text
/usr/local/sbin/compute01-backup.sh
```

systemd units:

```text
/etc/systemd/system/compute01-backup.service
/etc/systemd/system/compute01-backup.timer
```

Schedule:

- Daily around 03:30 local time.
- `Persistent=true`.
- Randomized delay up to 300 seconds.
- Retention: remove backups older than 7 days.

A scheduled overnight execution was verified successfully on 8 August 2026.

Observed files:

```text
compute-01_2026-08-08_03-33-56.tar.gz
compute-01_2026-08-08_03-33-56.tar.gz.sha256
```

Service log verified:

```text
Verifying archive...
...tar.gz: OK
Backup complete
status=0/SUCCESS
```

Backup includes:

- `/srv/compose`
- Jellyfin configuration
- Open WebUI state excluding cache
- Ollama state excluding large model blobs/cache
- `/etc/docker/daemon.json`
- `/etc/fstab`
- SSH configuration drop-ins
- UFW configuration
- `/etc/smartd.conf`
- SHA-256 checksum

Excluded intentionally:

- Open WebUI cache/embedding cache
- Ollama model blobs
- other regenerable large caches

The automated job stops relevant application stacks for consistency and restarts them through cleanup/trap handling.

### Remaining recovery gap

Backups currently live on the same physical server. They help with configuration mistakes and rebuilds but not total node/disk loss.

**Pending:** off-host copy after storage work on the other node is complete and the destination is approved for writes.

## 13. Git and Rebuild Framework

Repository locations:

```text
compute-01: /home/psquare/projects/p2-home-os
core node:  /opt/p2-home-os
upstream:   private GitHub repository prabhat324/p2-home-os
```

GitHub is the central source of truth.

Existing compute bootstrap:

```text
bootstrap/compute/
├── bootstrap.sh
└── modules/
    ├── 00-preflight.sh
    ├── 10-system-update.sh
    ├── 20-baseline-packages.sh
    ├── 30-storage.sh
    ├── 40-docker.sh
    ├── 50-nvidia.sh
    ├── 60-security.sh
    ├── 70-power-management.sh
    ├── 80-directories.sh
    └── 90-verify.sh
```

Safety principles:

- destructive storage actions require explicit arming/confirmation
- `/srv` must be verified before service directories are populated
- SSH safety takes precedence over aggressive firewall automation
- bootstrap is a rebuild/fresh-build tool, not something to casually rerun against a live server

## 14. Final Health Baseline — 8 August 2026

```text
Hostname:       compute-01
OS:             Ubuntu 26.04 LTS
Kernel:         7.0.0-29-generic
Failed units:   0
Load average:   ~0.01 / 0.02 / 0.00

Memory total:   61 GiB
Memory used:    ~2.2 GiB
Available:      ~59 GiB
Swap:           8 GiB, 0 used

/:              ~468 GB total, 7% used
/srv:           ~954 GB total, 3% used
/mnt/media:     ~7.3 TB total, 12% used

open-webui:     healthy
ollama:         running
jellyfin:       healthy

NFS:            192.168.0.203:/mnt/media -> /mnt/media
Protocol:       NFSv4.2
Mode:           read-only
```

Listeners of interest:

```text
22/tcp       SSH
3000/tcp     Open WebUI
8096/tcp     Jellyfin
41641/udp    Tailscale
5353/udp     Avahi/mDNS
```

Port `111` is no longer listening.

## 15. Common Operations

Check containers:

```bash
docker ps --format 'table {{.Names}}	{{.Status}}	{{.Ports}}'
```

Restart Jellyfin:

```bash
cd /srv/compose/jellyfin
docker compose restart
```

Restart AI stack:

```bash
cd /srv/compose/ai
docker compose restart
```

Verify GPU:

```bash
nvidia-smi
```

Verify GPU inside containers:

```bash
docker exec jellyfin nvidia-smi
docker exec ollama nvidia-smi
```

Check NFS:

```bash
findmnt -t nfs,nfs4 /mnt/media
nfsstat -m
```

Trigger automount:

```bash
ls /mnt/media >/dev/null
findmnt /mnt/media
```

Verify read-only mode:

```bash
findmnt -no OPTIONS /mnt/media
```

Check Tailscale:

```bash
tailscale status
```

Check firewall:

```bash
sudo ufw status numbered
```

Check listening ports:

```bash
sudo ss -tulpn
```

Check failed services:

```bash
systemctl --failed --no-pager
```

Check temperatures:

```bash
sensors
nvidia-smi
```

Check NVMe health:

```bash
sudo smartctl -H /dev/nvme0
sudo smartctl -H /dev/nvme1
```

Check backup timer:

```bash
systemctl list-timers compute01-backup.timer --all --no-pager
```

Verify latest backup:

```bash
sudo bash -c '
cd /srv/backups/compute-01 || exit 1
LATEST=$(ls -1t compute-01_*.tar.gz | head -1)
echo "Latest: $LATEST"
sha256sum -c "${LATEST}.sha256"
tar -tzf "$LATEST" >/dev/null && echo "Archive integrity: PASS"
'
```

## 16. Reboot Verification Checklist

After a planned reboot:

```bash
systemctl --failed --no-pager
docker ps
tailscale status
findmnt -t nfs,nfs4 /mnt/media
nvidia-smi
systemctl list-timers compute01-backup.timer --all --no-pager
```

Confirm:

- no failed systemd units
- `jellyfin`, `ollama`, and `open-webui` running
- Tailscale connected
- `/mnt/media` NFSv4.2 and read-only
- NVIDIA GPU visible
- backup timer active

Application checks:

```text
Jellyfin:   http://192.168.0.31:8096
Open WebUI: http://192.168.0.31:3000
```

## 17. Known Issues / Deferred Work

1. **Router DHCP reservation** — reserve `192.168.0.31` for Ethernet MAC `6c:02:e0:c9:46:bc`.
2. **Open WebUI exposure** — after reservation, decide whether port `3000` remains LAN-wide or becomes Tailscale/private-only.
3. **Off-host backup** — copy backups to another physical system after current storage migration/copy work is complete and the target is safe for writes.
4. **Jellyfin HDR → SDR test** — NVIDIA transcoding is proven; explicit tone-mapping validation is optional/deferred.
5. **Bare-metal recovery rehearsal** — not yet performed.
6. **Application restore rehearsal** — backup archive is verified, but full Jellyfin/Open WebUI restore has not yet been rehearsed.

## 18. Completion State

Verified complete for the present phase:

- Ubuntu server build
- service NVMe/XFS layout
- Docker/Compose
- NVIDIA driver/runtime
- wired Ethernet
- Tailscale
- key-only SSH hardening
- UFW SSH policy
- read-only NFSv4.2 media access
- Jellyfin Docker deployment
- NVIDIA Jellyfin transcoding
- Ollama deployment
- Open WebUI deployment
- Docker local log driver
- automatic security updates
- SMART monitoring
- automated daily configuration/application-state backups
- backup archive/checksum validation
- reboot survival
- rpcbind/port 111 removal
- final system health audit

The next compute-node milestone should be driven by a real workload or resilience requirement rather than more foundation work.

## Appendix A — Key Paths

```text
/home/psquare/projects/p2-home-os

/srv/appdata/jellyfin
/srv/appdata/ollama
/srv/appdata/open-webui

/srv/compose/jellyfin
/srv/compose/ai

/srv/backups/compute-01

/mnt/media

/etc/docker/daemon.json
/etc/fstab
/etc/ssh/sshd_config.d/00-compute-auth.conf
/etc/ssh/sshd_config.d/99-compute-hardening.conf
/etc/ufw
/etc/smartd.conf

/usr/local/sbin/compute01-backup.sh
/etc/systemd/system/compute01-backup.service
/etc/systemd/system/compute01-backup.timer
```

## Appendix B — Addresses and Ports

```text
compute-01 LAN:       192.168.0.31
compute-01 Tailscale: 100.65.64.4
media-server LAN:     192.168.0.203
media-server TS:      100.67.245.78

SSH:                  22/tcp
Open WebUI:           3000/tcp
Jellyfin:             8096/tcp
Tailscale:            41641/udp
```

## Appendix C — Repository Workflow

Before changes:

```bash
cd /home/psquare/projects/p2-home-os
git status
git branch --show-current
git remote -v
git pull --ff-only
```

After a verified milestone:

```bash
git status
git diff
git add <specific-files>
git commit -m "<clear milestone description>"
git push origin "$(git branch --show-current)"
```

Do not use `git add .` automatically on a server repository containing possible generated files or secrets. Stage only the intended documentation/configuration files.
