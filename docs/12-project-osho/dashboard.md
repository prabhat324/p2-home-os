# Project Osho Dashboard and Control Plane

## Purpose

The Project Osho dashboard is the human-visible surface for the zero-touch pipeline. It should answer immediately:

1. What is Osho doing right now?
2. Is every worker healthy?
3. Which node owns the work?
4. What happened to recent jobs, skips, failures and uploads?

The dashboard backend runs on `compute-02`, keeping UI/control-plane responsibilities separate from GPU-heavy processing.

## Version 0.5

As of 2026-08-14, dashboard v0.5 is source-controlled under:

```text
services/osho-dashboard/
```

The production endpoint is:

```text
http://192.168.0.88:8787
```

v0.5 is an in-place upgrade of the SQLite-backed dashboard. Existing `jobs`, `workers`, and `/data/osho.db` state are preserved. The backend adds a `state_snapshots` table for authoritative reconciliation.

## Summary counters

```text
Uploaded
Processing
Ready
Queued
Skipped
Failed
```

`Skipped` is intentionally separate from `Failed`. A source rejected because it has no safe V5 candidate or no genuine retention approval is healthy pipeline behavior, not a processing failure.

## Authoritative state reconciliation

Dashboard v0.5 no longer relies only on pushed dashboard job records for global counts.

The compute-01 telemetry agent v1.2 reads these production sources **read-only**:

```text
/srv/osho/library/catalog/catalog.sqlite
/srv/osho/youtube/receipts
```

Every 10 seconds compute-01 sends:

```text
POST /api/state/reconcile
```

The snapshot can include:

```text
published/uploaded count
processing count
ready count
queued count
skipped count
failed count
latest upload metadata
raw osho_autopilot_state status counts
```

The dashboard trusts a reconciliation snapshot only while it is <= 90 seconds old. If it becomes stale, local dashboard state remains available as a fallback.

Reconciliation is deliberately selective. If the authoritative table does not represent a category, the telemetry agent sends `null` rather than a fabricated zero, and the dashboard preserves its existing value for that category.

### Upload truth

Durable YouTube receipts are the preferred source for:

```text
Uploaded
Latest Upload
```

The agent deduplicates receipts, reconstructs the YouTube URL from `video_id` when necessary, and sends the newest receipt as the latest published item.

### Skip / processing truth

`osho_autopilot_state` is the source for persisted skip and active/recovery state. Examples include:

```text
skipped
processing
remote_qa
ready_to_upload
queued
failed
```

This means a source left in `processing` after an interrupted Autopilot run remains visible as persisted work requiring reconciliation rather than silently disappearing from the dashboard.

## Current job

The dashboard supports:

```text
job ID
source title
status
stage
progress
assigned worker
created / updated timestamps
published timestamp
YouTube URL
error
```

The `/api/jobs/update` payload accepts an optional `worker` field. Controllers should populate it whenever work is assigned to `compute-01` or `compute-03`.

## Latest upload

The latest successful upload card shows:

- title / job ID;
- publish/update timestamp;
- clickable YouTube URL when present.

A local `ready_to_upload` state is not considered published until the publishing layer succeeds and durable upload evidence is recorded.

## Systems view

### compute-02

The control plane is displayed explicitly with:

```text
compute-02
192.168.0.88:8787  dashboard/controller
Piper :10200
```

### compute-01 and compute-03

GPU workers register dynamically through:

```text
POST /api/worker/heartbeat
```

The telemetry agent reports every 10 seconds and can expose:

```text
hostname / role
LAN IP / worker port
worker API health
worker version
current worker stage/job when supplied
heartbeat age
GPU model
GPU utilization
VRAM used / total
GPU temperature
GPU power draw
1-minute system load
free space on /srv (or / fallback)
active Ollama model
Whisper model
CUDA/device type
Whisper compute type
compute-01 autopilot systemd state
telemetry-agent version
```

compute-03 also derives its active assignment from the catalog because it does not have compute-01's older dedicated operational heartbeat sender.

## Verified worker state

compute-01 and compute-03 have both been observed registering successfully on dashboard v0.4.1 before the v0.5 reconciliation upgrade.

compute-03 has reported:

```text
Project Osho Worker 0.6.2
NVIDIA GeForce RTX 2060
Whisper medium
cuda
int8_float16
```

It has also successfully completed an isolated distributed job through transcription and `rendering_approved_clips`, producing a 1080x1920 H.264/AAC reel.

## Heartbeat health interpretation

```text
online    heartbeat <= 30 seconds old and worker API healthy
stale     heartbeat > 30 seconds old
offline   heartbeat > 90 seconds old
degraded  telemetry agent is alive but local worker API is unavailable
unknown   heartbeat timestamp/state cannot be interpreted
```

The UI refreshes every 3 seconds; telemetry agents post every 10 seconds.

## Telemetry deployment

Agent source:

```text
services/osho-dashboard/telemetry/osho-dashboard-heartbeat.py
```

systemd unit:

```text
osho-dashboard-heartbeat.service
```

The service runs as `psquare`, starts automatically at boot, and uses fixed compute-02 Osho endpoints so telemetry does not depend on local DNS resolution:

```text
http://192.168.0.88:8787/api/worker/heartbeat
http://192.168.0.88:8787/api/state/reconcile
```

Telemetry v1.2 also knows:

```text
OSHO_CATALOG_DB=/srv/osho/library/catalog/catalog.sqlite
OSHO_RECEIPT_DIR=/srv/osho/youtube/receipts
```

Only compute-01 emits the global reconciliation snapshot.

## Database schema

The backend retains the existing `jobs` and `workers` tables.

Important worker fields include:

```text
role
ip
service
service_version
worker_port
gpu_name
gpu_utilization
vram_used_mb
vram_total_mb
gpu_temperature_c
gpu_power_w
ollama_model
whisper_model
device
compute_type
load_1m
disk_free_gb
autopilot_status
telemetry_version
```

v0.5 adds:

```text
state_snapshots
```

with one latest snapshot per source host. Runtime database files are ignored by Git and must not be committed.

## Stage vocabulary

Keep machine-readable stage names stable. Current/recommended vocabulary includes:

```text
queued
downloading
transcribing
candidate_extraction
hook_ranking
retention_qa
remote_qa
rendering
rendering_approved_clips
metadata
ready_to_upload
uploading
published
skipped
failed
```

## Deployment safety

The repository includes:

```text
services/osho-dashboard/deploy-to-compute02.sh
```

The deployment script:

1. backs up the currently deployed source/config on compute-02;
2. preserves `data/osho.db`;
3. preserves an existing host-specific `compose.yml`;
4. validates Docker Compose;
5. rebuilds the dashboard container;
6. checks `/health` and `/api/dashboard`.

Detailed deployment instructions are in `services/osho-dashboard/README.md`.

## Hostname failure mode

A previous telemetry registration failure was caused by cluster name resolution:

```text
curl: (6) Could not resolve host: compute-02
```

The telemetry service now uses compute-02's fixed Osho control-plane IP (`192.168.0.88`) to avoid making worker registration depend on hostname resolution. Hostname consistency should still be repaired for SSH and general cluster administration, but it is no longer a prerequisite for dashboard heartbeats.

## Future improvements

Useful next dashboard features include:

- durable activity/event timeline;
- per-stage elapsed time;
- historical GPU/worker utilization charts;
- jobs processed per worker;
- skip/failure rates by ranker/QA version;
- uploads per day/week;
- YouTube performance feedback correlated with candidate/ranker versions;
- worker drain/maintenance mode;
- alerts for stale workers, low disk, overheating, or repeated failures.
