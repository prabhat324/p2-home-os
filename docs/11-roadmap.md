# Roadmap

## Near term

### Documentation and observability

- Keep MkDocs aligned with as-built service placement.
- Add current service-health/status data to the Project Osho dashboard.
- Persist worker/GPU/job history rather than relying only on live status.
- Add automated checks for hostname resolution and required mounts.

### Project Osho

- Harden YouTube OAuth/token storage outside Git.
- Complete scheduler/controller behavior on compute-02.
- Make compute-03 a persistent managed worker.
- Add duplicate-upload/idempotency protection around receipts.
- Add production-shaped test mode that cannot publish publicly.
- Capture ranking/QA versions and correlate them with actual YouTube performance.

### Photos

- Verify the current 2 TB backup mount and run a verified backup of the 3 TB primary photo library.
- Perform restore testing rather than relying on successful copy logs alone.
- Keep the primary photo library read-only inside Immich.

## Medium term

- Consolidate cluster hostname management into local DNS rather than duplicated `/etc/hosts` entries.
- Add central monitoring for disk usage, GPU state, service health, and worker heartbeats.
- Improve Home Assistant voice orchestration using the existing Whisper and Piper endpoints.
- Formalize service recovery/runbooks and test them after major changes.

## Longer term

- Add additional GPU worker capacity only when workload data shows a real bottleneck.
- Consider stage-aware Osho scheduling based on VRAM, model availability, and worker utilization.
- Maintain infrastructure-as-code for reproducible rebuilds.
- Build a verified multi-copy backup strategy for irreplaceable family data and secrets.

## Guardrails

- Do not expose internal services directly to the public internet without a specific authenticated design.
- Do not commit credentials or tokens.
- Do not treat a planned component as production until it is verified.
- Do not move heavy GPU work onto core-01 or orchestration-heavy duties onto compute-01 without a deliberate architecture change.
