# Project Osho Dashboard v0.4

Source-controlled implementation of the Project Osho dashboard running on `compute-02:8787`.

## What v0.4 adds

- Dynamic `compute-01` and `compute-03` worker cards.
- Worker heartbeat states: online, stale, offline, degraded.
- GPU model, utilization, VRAM, temperature and power.
- Worker API version and endpoint.
- Whisper model/device/compute type.
- Active Ollama model when one is loaded.
- One-minute load and `/srv` free space.
- compute-01 autopilot service state.
- Heartbeat age and telemetry-agent version.
- Queue counters for Uploaded, Processing, Ready, Queued, Skipped and Failed.
- Assigned worker field on jobs when the producer supplies it.
- Clickable latest YouTube upload link.
- Explicit compute-02 control-plane card with dashboard and Piper ports.

## Layout

```text
services/osho-dashboard/
├── Dockerfile
├── compose.yml
├── requirements.txt
├── deploy-to-compute02.sh
├── app/
│   ├── main.py
│   └── static/index.html
└── telemetry/
    ├── install.sh
    ├── osho-dashboard-heartbeat.py
    └── osho-dashboard-heartbeat.service
```

## Deploy dashboard to compute-02

Run from a checkout of `p2-home-os` on a host that can SSH to `compute-02`:

```bash
cd ~/projects/p2-home-os
bash services/osho-dashboard/deploy-to-compute02.sh
```

The deploy script:

1. creates a timestamped backup of the currently deployed dashboard source/config;
2. does **not** replace `data/osho.db`;
3. copies v0.4 source files;
4. validates `docker compose config`;
5. rebuilds/restarts the dashboard container;
6. checks `/health` and `/api/dashboard`.

The v0.4 backend migrates the existing SQLite schema forward with `ALTER TABLE` for missing columns. The database does not need to be deleted or recreated.

## Install telemetry on compute-01

From the repository checkout on compute-01:

```bash
cd ~/projects/p2-home-os/services/osho-dashboard/telemetry
bash install.sh
```

## Install telemetry on compute-03

From compute-01 or another host with SSH access:

```bash
cd ~/projects/p2-home-os
rsync -av services/osho-dashboard/telemetry/ compute-03:/tmp/osho-dashboard-telemetry/
ssh -t compute-03 'cd /tmp/osho-dashboard-telemetry && bash install.sh'
```

The systemd service runs as `psquare`, starts at boot, and sends a heartbeat every 10 seconds to:

```text
http://compute-02:8787/api/worker/heartbeat
```

## Verify

```bash
curl -fsS http://compute-02:8787/health | python3 -m json.tool
curl -fsS http://compute-02:8787/api/dashboard | python3 -m json.tool
```

Within roughly 10 seconds of enabling telemetry on both GPU nodes, the `workers` array should contain `compute-01` and `compute-03`.

Check individual agents:

```bash
systemctl status osho-dashboard-heartbeat.service --no-pager
journalctl -u osho-dashboard-heartbeat.service -n 50 --no-pager
```

## Runtime data and secrets

`services/osho-dashboard/data/` and SQLite database files are excluded by `.gitignore`. No worker token, YouTube OAuth token, API key, password or SSH key belongs in this directory or repository.

## Current-job ownership

The dashboard backend accepts an optional `worker` field on `/api/jobs/update`. Producers/controllers should send the assigned worker as jobs move between nodes. Worker telemetry is intentionally separate from durable job ownership so a stale worker heartbeat cannot rewrite job history.
