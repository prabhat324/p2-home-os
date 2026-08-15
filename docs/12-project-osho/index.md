# Project Osho

Project Osho is an automated short-form video production and publishing pipeline built on the P² Home OS compute cluster.

Its goal is to take authorized/licensed long-form source material, identify strong short-form moments, render them as vertical videos, generate publishing metadata, and ultimately publish them to YouTube with minimal or zero manual intervention.

> **Security note:** this repository documents architecture, paths, services, ports, workflows, and operational procedures. Credentials, OAuth secrets, access tokens, cookies, private keys, and other secrets must never be committed.

## Current state

As of 2026-08-14, the project has moved beyond a single-machine prototype and is operating as a distributed pipeline:

- **compute-01** is the primary heavy-processing node.
- **compute-02** is the control-plane/dashboard node.
- **compute-03** has been proven as an additional render/worker node and is available for GPU-assisted expansion.
- The worker pipeline can reuse existing transcripts, rank candidate hooks, run retention QA, render approved clips, generate metadata, and hand completed jobs to the publishing layer.
- The zero-touch V5 autopilot is designed to operate without human approval for public publishing workflows.
- The dashboard API exposes job and worker status for monitoring from a browser or dedicated display.
- YouTube upload integration has been tested far enough to produce upload receipts/IDs, but credential handling and long-term production scheduling must remain isolated from source control.

## Project goals

1. Ingest authorized source media.
2. Transcribe source content efficiently using GPU acceleration where available.
3. Reuse transcripts whenever possible instead of retranscribing unchanged media.
4. Identify compelling 25–55 second short-form segments.
5. Rank potential hooks using a dedicated ranking stage.
6. Apply retention-oriented QA before rendering.
7. Render vertical 1080×1920 clips suitable for YouTube Shorts/Reels.
8. Generate titles, descriptions, hashtags, and publishing metadata.
9. Queue completed clips for YouTube publishing.
10. Track job state, errors, workers, and upload receipts through the control plane.
11. Scale horizontally by allowing additional compute workers to process jobs.

## Documentation map

- [Architecture](architecture.md) — host roles, services, data flow, scaling model.
- [Pipeline](pipeline.md) — source-to-upload processing stages and current scoring/ranking logic.
- [Services and Paths](services-and-paths.md) — containers, systemd units, ports, storage layout, APIs.
- [Dashboard and Control Plane](dashboard.md) — compute-02 dashboard API and job/worker status schema.
- [Operations](operations.md) — health checks, restart procedures, troubleshooting, safe testing.
- [YouTube Publishing](youtube-publishing.md) — publishing handoff, receipts, credential policy, and current status.

## Design principles

### Separate control plane from heavy compute

The system intentionally keeps orchestration and UI responsibilities separate from expensive AI/video workloads. This allows the dashboard and scheduler to remain responsive while GPU workers are saturated.

### Jobs are file-backed and inspectable

Project Osho stores sources, transcripts, candidate decisions, work directories, renders, metadata, logs, and receipts as normal files under `/srv/osho`. This makes the system easier to debug, recover, migrate, and audit.

### Reuse expensive work

Transcription is one of the most expensive stages. Existing transcript artifacts should be reused whenever the source has already been processed and the transcript is still valid.

### Worker expansion must be additive

New workers such as compute-03 should increase throughput without changing the external control-plane interface. The controller should dispatch work; workers should execute jobs and report state.

### Public automation requires stricter QA

Because the zero-touch mode can publish without human approval, retention QA, metadata validation, duplicate protection, upload receipts, and error isolation are not optional safeguards.

## Known successful outputs

The pipeline has produced successful public YouTube upload records for source `000001`, including video IDs:

- `WZKMoBtfreM`
- `crS_KjpMI-U`

These IDs are operational evidence only. They do not replace the local receipt files under `/srv/osho/youtube/receipts`.

## Next major milestones

- Complete hardened YouTube OAuth/token storage outside Git.
- Finalize publishing scheduler/controller behavior on compute-02.
- Add dashboard test mode using a production-shaped `test_transcript.json` fixture.
- Formalize compute-03 as a persistent worker instead of an ad-hoc render node.
- Add duplicate-content protection and upload idempotency checks.
- Add persistent metrics/history for throughput, failures, ranking scores, and uploads.
- Add notification hooks for failed jobs and successful publishing events.
