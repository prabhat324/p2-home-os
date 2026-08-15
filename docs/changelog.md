# Change Log

## 2026-08-14

### Project Osho

- Added full Project Osho documentation section.
- Documented distributed architecture across compute-01, compute-02, and compute-03.
- Documented V5 candidate ranking, retention QA, render/publish states, skip-vs-fail behavior, YouTube receipts, reconciliation, and idempotency requirements.
- Added operational runbook and troubleshooting guidance.
- Added source-controlled Project Osho Dashboard v0.4 under `services/osho-dashboard/`.
- Dashboard v0.4 adds dynamic compute-03 visibility, GPU/VRAM/temperature/power telemetry, worker/Whisper/Ollama details, load, free disk, heartbeat age, compute-01 autopilot state, and stale/offline/degraded worker health.
- Added `Skipped` and `Queued` dashboard counters, assigned-worker support, and clickable latest YouTube upload links.
- Added a standard telemetry heartbeat agent and systemd service for compute-01 and compute-03.
- Added safe compute-02 deployment tooling that preserves the existing SQLite runtime database and backs up deployed source/config before replacement.

### Compute cluster

- Updated compute-01 from planned to verified operational state.
- Added compute-02 host documentation and its Osho/Piper roles.
- Added compute-03 host documentation and its RTX 2060/Osho/Ollama roles.
- Updated core-01 to reflect that production Jellyfin has migrated to compute-01 while the 8 TB media disk remains on core-01.

### Storage

- Documented read-only NFS media flow from core-01 to compute-01.
- Documented the 3 TB primary private-photo library as read-only inside Immich.
- Marked the 2 TB backup drive as designated but not currently re-verified, avoiding a false backup-coverage claim.

### Services and operations

- Replaced placeholder Services, Smart Home, Backups, Recovery, Troubleshooting, and Roadmap pages.
- Documented Wyoming Whisper on compute-01 and Piper on compute-02.
- Added maintenance checks for GPUs, mounts, hostnames, containers, and Osho services.
- Added recovery ordering and duplicate-upload protection guidance.

### Architecture

- Replaced empty network-topology and service-map placeholders.
- Updated the documentation homepage and repository README to describe the distributed platform instead of the original Raspberry Pi-only design.

## Earlier

- Initial documentation website created.
- compute-01 build and as-built runbook established.
