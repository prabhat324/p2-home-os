# Project Osho Dashboard and Control Plane

## Purpose

The Project Osho dashboard is the human-visible surface for the zero-touch pipeline. It should answer immediately:

1. What is Osho doing right now?
2. Is every worker healthy?
3. Which node owns the work?
4. What happened to recent jobs and uploads?

The dashboard backend runs on `compute-02`, keeping UI/control-plane responsibilities separate from GPU-heavy processing.

## Version 0.4

As of 2026-08-14, dashboard v0.4 is source-controlled under:

```text
services/osho-dashboard/
```

The production dashboard remains on compute-02 at:

```text
http://compute-02:8787
```

v0.4 is designed as an in-place upgrade of the existing v0.3 SQLite-backed dashboard. Its schema migration adds columns with `ALTER TABLE` and preserves the current `/data/osho.db` database.

## v0.4 summary counters

```text
Uploaded
Processing
Ready
Queued
Skipped
Failed
```

`Skipped` is intentionally separate from `Failed`. Project Osho can reject a source because it has no safe V5 candidate or no genuine retention approval; that is healthy pipeline behavior, not a failure.

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

The `/api/jobs/update` payload now accepts an optional `worker` field. Controllers should populate it whenever work is assigned to `compute-01` or `compute-03`.

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

The v0.4 telemetry agent reports every 10 seconds and can expose:

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

This is particularly important for `compute-03`, which was previously invisible because the v0.3 dashboard only displayed workers that explicitly posted basic heartbeats.

## Verified compute-03 capabilities

compute-03 has a healthy Project Osho Worker API on TCP 8800 and has reported:

```json
{
  "status": "ok",
  "service": "Project Osho Worker",
  "version": "0.6.2",
  "whisper_model": "medium",
  "device": "cuda",
  "compute_type": "int8_float16"
}
```

compute-03 has also successfully completed an isolated distributed job through transcription and `rendering_approved_clips`, producing a 1080x1920 H.264/AAC reel. It is therefore a proven processing worker, not merely a standby host.

## Heartbeat health interpretation

```text
online    heartbeat <= 30 seconds old and worker API healthy
stale     heartbeat > 30 seconds old
 offline   heartbeat > 90 seconds old
degraded  telemetry agent is alive but local worker API is unavailable
unknown   heartbeat timestamp/state cannot be interpreted
```

The dashboard refreshes every 3 seconds; telemetry agents post every 10 seconds.

## Telemetry deployment

Agent source:

```text
services/osho-dashboard/telemetry/osho-dashboard-heartbeat.py
```

systemd unit:

```text
osho-dashboard-heartbeat.service
```

The service is intended to run on both compute-01 and compute-03 as user `psquare` and starts automatically at boot.

Default destination:

```text
http://compute-02:8787/api/worker/heartbeat
```

## Database schema migration

The v0.4 backend retains the existing `jobs` and `workers` tables and adds missing fields automatically. Important new worker columns include:

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

The `jobs` table adds:

```text
worker
```

Runtime database files are ignored by Git and must not be committed.

## Stage vocabulary

Keep machine-readable stage names stable. Current/recommended vocabulary includes:

```text
queued
downloading
transcribing
candidate_extraction
hook_ranking
retention_qa
rendering
rendering_approved_clips
metadata
ready_to_upload
uploading
published
skipped
failed
```

## Important events

Meaningful zero-touch events include:

```text
NO SAFE V5 CANDIDATES
0 GENUINE APPROVALS — SKIPPED
RECONCILED AS PUBLISHED
worker stale / offline / degraded
upload started
upload succeeded
upload failed
```

A future activity/event stream should persist these as structured events rather than scrape terminal logs.

## Deployment safety

The repository includes:

```text
services/osho-dashboard/deploy-to-compute02.sh
```

The deployment script:

1. backs up the currently deployed source/config on compute-02;
2. preserves `data/osho.db`;
3. validates Docker Compose;
4. rebuilds the container;
5. checks `/health` and `/api/dashboard`.

Detailed deployment instructions are in `services/osho-dashboard/README.md`.

## Hostname failure mode

A previous dashboard outage was caused by cluster name resolution:

```text
curl: (6) Could not resolve host: compute-02
ssh: Could not resolve hostname compute-02
```

Troubleshoot in this order:

```bash
getent hosts compute-02
ping -c 2 compute-02
ssh compute-02
curl -fsS http://compute-02:8787/health
```

Do not rewrite application code until name resolution and TCP reachability have been verified.

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
