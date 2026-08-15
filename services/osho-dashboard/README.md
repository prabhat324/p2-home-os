# Project Osho Dashboard v0.5

Source-controlled implementation of the Project Osho dashboard running on `compute-02:8787`.

## What v0.5 adds

v0.5 keeps all v0.4 worker telemetry and adds **authoritative state reconciliation** from compute-01.

compute-01 telemetry v1.2 reads, without modifying:

```text
/srv/osho/library/catalog/catalog.sqlite
/srv/osho/youtube/receipts
```

It sends a state snapshot every 10 seconds to:

```text
POST http://192.168.0.88:8787/api/state/reconcile
```

The dashboard stores the latest snapshot in `state_snapshots` and uses it while it is fresh (<= 90 seconds).

Reconciliation can correct:

- durable published/uploaded count from YouTube receipts;
- latest published video/title/time/URL from the newest receipt;
- skipped count from `osho_autopilot_state`;
- persisted processing/remote-QA state;
- ready/queued/failed counts when those states are explicitly present in the authoritative table.

The reconciliation is intentionally selective. A missing authoritative status does **not** overwrite an existing dashboard count with zero. This prevents real v0.4 job history from disappearing simply because a different state store does not represent that category.

## v0.4 telemetry retained

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
3. preserves an existing compute-02 `compose.yml` so host-specific settings are not lost;
4. installs the repository baseline Compose file only when compute-02 has no existing Compose file;
5. copies the application/build files;
6. validates `docker compose config`;
7. rebuilds/restarts the dashboard container;
8. checks `/health` and `/api/dashboard`.

The backend migrates the existing SQLite schema in place. v0.5 adds the `state_snapshots` table and preserves the existing `jobs` and `workers` data.

## Install telemetry on compute-01

From the repository checkout on compute-01:

```bash
cd ~/projects/p2-home-os/services/osho-dashboard/telemetry
bash install.sh
```

compute-01 sends both rich worker telemetry and the read-only authoritative state snapshot.

## Install telemetry on compute-03

From compute-01 or another host with SSH access:

```bash
cd ~/projects/p2-home-os
rsync -av services/osho-dashboard/telemetry/ compute-03:/tmp/osho-dashboard-telemetry/
ssh -t compute-03 'cd /tmp/osho-dashboard-telemetry && bash install.sh'
```

compute-03 sends worker telemetry and its catalog-derived operational assignment. It does not send the global state snapshot.

The services use compute-02's fixed Osho control-plane address rather than depending on cluster DNS:

```text
http://192.168.0.88:8787/api/worker/heartbeat
http://192.168.0.88:8787/api/state/reconcile
```

## Verify

```bash
curl -fsS http://192.168.0.88:8787/health | python3 -m json.tool
curl -fsS http://192.168.0.88:8787/api/dashboard | python3 -m json.tool
```

Expected versions after deployment:

```text
dashboard_version: 0.5.0
compute-01 telemetry_version: 1.2.0
```

`/api/dashboard` also exposes `state_reconciliation` with its source, age, freshness, raw status counts and notes.

Check individual agents:

```bash
systemctl status osho-dashboard-heartbeat.service --no-pager
journalctl -u osho-dashboard-heartbeat.service -n 50 --no-pager
```

## Runtime data and secrets

`services/osho-dashboard/data/` and SQLite database files are excluded by `.gitignore`. No worker token, YouTube OAuth token, API key, password or SSH key belongs in this directory or repository.

Reconciliation reads receipt metadata only. It does not read or transmit YouTube OAuth credentials.

## Current-job ownership

The dashboard backend accepts an optional `worker` field on `/api/jobs/update`. Producers/controllers should send the assigned worker as jobs move between nodes. Worker telemetry is intentionally separate from durable job ownership so a stale worker heartbeat cannot rewrite job history.
