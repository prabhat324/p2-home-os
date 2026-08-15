# Project Osho Architecture

## Cluster roles

| Host | Primary Project Osho role | Notes |
| --- | --- | --- |
| `compute-01` | Heavy processing / primary GPU worker | Runs the main Osho processing stack, including the zero-touch autopilot. NVIDIA Quadro RTX 3000 6 GB. |
| `compute-02` | Control plane / dashboard | Hosts the Osho dashboard and is the intended location for scheduler/controller responsibilities. |
| `compute-03` | Additional GPU worker | Proven with the Osho worker and Ollama. NVIDIA GeForce RTX 2060 6 GB. Intended to expand render/AI capacity. |
| `core-01` | General infrastructure | Not currently a primary Osho execution node. Keep Osho-specific workload off this host unless the architecture is deliberately changed. |

## High-level data flow

```text
Authorized source media
        |
        v
  Source inventory
        |
        v
 Transcript lookup/reuse
        |
        +---- transcript missing/stale ----> transcription
        |
        v
 Candidate extraction
        |
        v
 Hook ranking (V5)
        |
        v
 Retention QA / safety gates
        |
        v
 Render worker
        |
        v
 Metadata generation
        |
        v
 Ready-to-upload queue
        |
        v
 YouTube publisher
        |
        v
 Receipt + dashboard state
```

## Control plane vs worker plane

### Control plane

The control plane should be lightweight and durable. Its responsibilities are:

- maintain the queue;
- decide which job is next;
- assign work to workers;
- expose worker heartbeats;
- expose current job state and aggregate queue state;
- record upload state and receipts;
- provide a browser/dashboard view;
- avoid performing GPU-heavy work itself unless intentionally configured.

`compute-02` is the preferred control-plane host.

### Worker plane

Workers perform expensive stages such as:

- transcript generation;
- semantic candidate analysis;
- hook ranking;
- retention QA;
- video decode/encode/render;
- metadata generation when backed by a local model.

`compute-01` is currently the main worker. `compute-03` has been validated as an additional worker.

## GPU and LLM layout

### compute-01

Observed Project Osho workload:

- GPU: NVIDIA Quadro RTX 3000, 6 GB VRAM.
- Osho autopilot process: `/usr/bin/python3 /srv/compose/osho-worker/osho_autopilot.py`.
- Ranking process example: `hook_ranker_v5.py`.
- Local Ollama server may occupy GPU memory concurrently with ranking/render stages.
- The workstation has an 80 W NVIDIA power limit and has been operated continuously for overnight jobs.

### compute-03

Observed Project Osho workload:

- GPU: NVIDIA GeForce RTX 2060, 6 GB VRAM.
- Osho worker API: `python3 -m uvicorn app:app --host 0.0.0.0 --port 8800`.
- Ollama model observed: `qwen3:8b`.
- Ollama was observed using a mixed CPU/GPU split because the model plus context exceeds convenient full-GPU residency on a 6 GB card.
- The worker was validated as a functioning expansion node even while no Osho jobs were actively queued.

## Why distributed workers matter

The system is constrained by several expensive resources:

1. GPU VRAM — local LLM and video/AI stages may contend for the same 6 GB GPU.
2. Encode/decode throughput — high-resolution video processing can saturate CPU/GPU resources independently of LLM inference.
3. Job latency — one long source can block a single-node pipeline.
4. Availability — a dedicated control plane prevents monitoring and scheduling from becoming unavailable when a GPU node is saturated or rebooted.

Adding workers should therefore be done through the existing worker API and shared job model rather than by copying unrelated orchestration logic to every host.

## Storage model

The durable Project Osho tree lives under:

```text
/srv/osho
```

The processing software itself has also been deployed under:

```text
/srv/compose/osho-worker
```

This separation is intentional:

- `/srv/compose/osho-worker` = application code and service configuration;
- `/srv/osho` = durable job data, sources, outputs, logs, and receipts.

The durable data directory should be backed up independently of the application checkout.

## Network model

All Project Osho nodes should resolve one another by hostname rather than hard-coded IP address where possible:

```text
compute-01
compute-02
compute-03
core-01
```

This avoids breaking worker/controller configuration when DHCP addresses change. Local DNS or consistent `/etc/hosts` entries should exist across the cluster.

The worker API on compute-03 has been observed on TCP port `8800`. Dashboard/controller endpoints should remain LAN-only unless intentionally proxied through an authenticated remote-access layer.

## Failure domains

### Worker failure

Expected behavior:

- worker heartbeat ages out;
- job returns to queue or is marked failed/retriable;
- dashboard stays online;
- partial work directory remains available for inspection.

### Control-plane failure

Expected behavior:

- workers should not corrupt already-running jobs;
- new work should stop being assigned;
- controller state should recover from durable queue/job files or its persistence layer after restart.

### Publisher failure

Expected behavior:

- rendered file remains intact;
- job must not be treated as published without a durable upload receipt;
- retries must check for an existing receipt/video ID to prevent duplicate uploads.

## Scaling direction

The preferred evolution is:

```text
compute-02
  controller/dashboard
      |
      +--> compute-01 worker
      +--> compute-03 worker
      +--> future worker(s)
```

Worker selection can later consider:

- worker health;
- free VRAM;
- GPU utilization;
- current job count;
- model availability;
- stage affinity (transcription vs LLM vs rendering);
- source data locality.
