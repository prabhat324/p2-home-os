# Project Osho Dashboard and Control Plane

## Purpose

The Project Osho dashboard is the human-visible surface for a zero-touch system. It should answer three questions immediately:

1. What is Osho doing right now?
2. Is every worker healthy?
3. What happened to recent jobs and uploads?

The dashboard backend runs on `compute-02`, keeping UI/control-plane responsibilities separate from GPU-heavy processing.

## Observed API shape

The dashboard API has returned JSON structured like:

```json
{
  "timestamp": "2026-08-14T01:54:33.664603+00:00",
  "summary": {
    "uploaded": 0,
    "processing": 0,
    "queued": 15,
    "failed": 1
  },
  "current_job": {
    "id": "OSHO-20260813-200537-fc38cb",
    "status": "ready_to_upload",
    "stage": "ready_to_upload",
    "title": "A Bird on the Wing 09",
    "progress": 100.0,
    "created_at": "2026-08-13T20:05:37.918243+00:00",
    "updated_at": "2026-08-13T20:06:51.134561+00:00",
    "published_at": null,
    "youtube_url": null,
    "error": null
  },
  "latest_upload": null,
  "workers": []
}
```

The exact implementation may evolve, but this schema captures the important control-plane concepts.

## Summary counters

Recommended counters:

- `uploaded` — successfully published jobs with durable receipts.
- `processing` — jobs actively owned by a worker.
- `queued` — jobs waiting for work.
- `failed` — jobs that need intervention or retry.
- `skipped` — useful future addition for sources intentionally rejected by QA.

Skipped and failed must not be combined. A healthy zero-touch pipeline will intentionally skip some sources.

## Current job

The dashboard should expose:

```text
job ID
source ID/title
status
stage
progress
assigned worker
created timestamp
last updated timestamp
published timestamp
YouTube URL/video ID
error
```

A job at `progress: 100` is not necessarily published. For example, `ready_to_upload` means production is complete but the upload still needs to succeed and be recorded.

## Worker status

Each worker entry should include at least:

```text
name
status
current_job
stage
progress
last_seen
age_seconds
```

Recommended extensions:

```text
GPU model
GPU utilization
VRAM used / total
GPU temperature
power draw
CPU load
free disk
Ollama model loaded
worker version
```

Worker state should be derived from recent heartbeats, not merely whether the host responds to ping.

Suggested health interpretation:

```text
online     heartbeat fresh
stale      heartbeat delayed beyond normal processing interval
offline    heartbeat exceeded failure threshold
drain      intentionally accepting no new jobs
```

## Stage vocabulary

Keep stage names stable and machine-friendly. Example lifecycle:

```text
queued
transcribing
candidate_extraction
hook_ranking
retention_qa
rendering
metadata
ready_to_upload
uploading
published
skipped
failed
```

If the implementation currently uses different labels, document them rather than silently renaming live states.

## Production status events

Important autopilot events should appear on the dashboard or event log, including:

```text
NO SAFE V5 CANDIDATES
0 GENUINE APPROVALS — SKIPPED
RECONCILED AS PUBLISHED
worker offline / stale
upload started
upload succeeded
upload failed
```

These status updates were specifically identified as useful dashboard information during Project Osho development.

## Test mode

The dashboard/control-plane needs a test mode that exercises the real data shape without touching production publishing.

Recommended fixture:

```text
test_transcript.json
```

Requirements:

- same schema as a real transcript;
- enough timestamps/text to run candidate extraction and ranking;
- unmistakably marked as test data;
- cannot accidentally trigger public upload;
- produces the same dashboard state transitions as a normal job wherever practical.

## Hostname failure mode

A previous dashboard check failed with:

```text
curl: (6) Could not resolve host: compute-02
ssh: Could not resolve hostname compute-02: Temporary failure in name resolution
```

This was a cluster name-resolution problem, not proof of a broken dashboard backend.

Troubleshooting order:

```bash
getent hosts compute-02
ping -c 2 compute-02
ssh compute-02
ss -lntp
curl -v http://compute-02:<port>/<route>
```

Do not restart or rewrite application code before confirming that DNS/hosts resolution and the TCP listener work.

## Dashboard design priorities

A dedicated phone/tablet dashboard should favor status at a glance:

### Top row

```text
AUTOPILOT: RUNNING / STOPPED
CURRENT SOURCE
CURRENT STAGE
PROGRESS
```

### Queue summary

```text
Queued | Processing | Uploaded | Skipped | Failed
```

### Workers

One compact card per worker showing:

```text
compute-01  ONLINE  ranking  66% GPU  74°C
compute-03  ONLINE  idle     17% GPU  57°C
```

### Activity log

Latest meaningful events, newest first.

### Publishing

Latest upload title, timestamp, and YouTube link/video ID.

## API durability

The dashboard should read durable state from the controller/job store. It should not depend on scraping terminal output as its primary data source.

Terminal/process inspection is excellent for diagnostics, but the control plane should expose stable structured data directly.

## Future metrics

Persist metrics that can answer:

- average time per source;
- time spent per stage;
- jobs per day;
- skip rate;
- failure rate;
- average candidates generated;
- average candidates surviving QA;
- worker utilization;
- uploads per day/week;
- ranker version vs resulting YouTube retention/performance.

This turns the dashboard from a status screen into the feedback system used to improve Osho itself.
