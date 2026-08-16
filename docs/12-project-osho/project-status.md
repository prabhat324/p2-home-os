# Project Osho Status

## Full hold requested — enforcement pending — 2026-08-16

Project Osho has an indefinite, reversible **full hold requested** by owner decision. Enforcement is pending one-time node-administrator authorization because the `p2ops` control account is not permitted to stop or disable system services.

The hold applies only to Project Osho. The core pSquare Home OS dashboard (`dashboard.home.arpa` / `homepage`), monitoring, media, smart-home, storage, AI, and other shared platform services remain operational. Shared Ollama services must not be disabled merely because Osho is held; only Osho-triggered resident models should be unloaded when GPU capacity is needed.

The hold policy is:

- no Osho processing, ranking, QA, rendering, analytics, dashboard/controller, notification, or publishing workload may run;
- no Osho systemd service or timer may start automatically;
- Osho containers are stopped and their restart policies are disabled;
- resident Ollama models are unloaded from Osho GPU nodes;
- YouTube auto-upload is disabled;
- source material, transcripts, job state, renders, metadata, logs, upload receipts, application code, credentials on their existing hosts, and documentation are preserved;
- unrelated services and data are not removed or disabled.

The authoritative control-plane operation is:

```text
operation: osho-hold
target: osho_nodes
```

The playbook writes a hold marker on every Osho node:

```text
/var/lib/p2-home-os/holds/project-osho.json
```

It also preserves the pre-hold worker environment as:

```text
/srv/compose/osho-worker/.env.pre-full-hold
```

Do not restart an Osho unit, container, worker, dashboard, or publisher while this status remains `full_hold`. A future restart must use a documented resume playbook that restores only reviewed components and begins with public auto-upload disabled.

## Preserved outcome and lessons

The system proved that a distributed, file-backed media pipeline could reuse transcripts, rank candidate hooks, perform retention QA, render valid 1080×1920 H.264/AAC clips, track state, and publish some successful YouTube Shorts with durable IDs/receipts.

The principal operational lesson is that a successful render or a dashboard `ready_to_upload` count is not proof of publication. Future publishing pipelines must treat a verified platform ID plus a durable receipt as the end-to-end success condition. They should retain idempotency checks, bounded retries, preflight validation, file-backed state, explicit reconciliation, and separation between rendering and publication.

The project remains preserved for audit and possible future study; the hold is not a deletion.

## Enforcement record

The first control run (`31955607723`) reached compute-01, compute-02, and compute-03 but made no changes because sudo rejected Ansible privilege escalation. The subsequent audit (`31955639960`) succeeded and confirmed active Osho services on compute-01 and compute-03. Do not mark this hold enforced until a successful control run verifies no active Osho units, containers, processes, resident Ollama models, or Osho GPU processes.
