# Project Osho Services and Paths

## Application paths

### Primary worker application

```text
/srv/compose/osho-worker
```

This directory contains the Osho worker application and autopilot code on the compute nodes where it has been deployed.

Known process entry points include:

```text
/srv/compose/osho-worker/osho_autopilot.py
hook_ranker_v5.py
app.py
```

### Durable Osho data

```text
/srv/osho
```

Keep durable project data separate from application code. The durable tree is expected to contain or evolve toward clearly separated source, transcript, work, output, metadata, log, queue, and receipt areas.

Recommended layout:

```text
/srv/osho/
├── sources/
├── transcripts/
├── jobs/
├── work/
├── renders/
├── metadata/
├── logs/
├── queue/
└── youtube/
    └── receipts/
```

Existing production paths should be preserved when they differ from this suggested organization; do not move live data simply to make the tree match documentation.

## Systemd service

### Zero-touch autopilot

Known unit:

```text
osho-autopilot.service
```

Observed active process:

```text
/usr/bin/python3 /srv/compose/osho-worker/osho_autopilot.py
```

Useful commands:

```bash
sudo systemctl status osho-autopilot.service --no-pager
sudo journalctl -u osho-autopilot.service -n 100 --no-pager
sudo journalctl -u osho-autopilot.service -f
sudo systemctl restart osho-autopilot.service
```

Before restarting the service during a long-running job, first determine whether the current stage is safely resumable.

## Worker API

On compute-03, the worker has been observed running as:

```text
python3 -m uvicorn app:app --host 0.0.0.0 --port 8800
```

Therefore the worker API listens on:

```text
TCP 8800
```

Basic checks:

```bash
ss -lntp | grep ':8800'
ps aux | grep '[u]vicorn app:app'
curl -fsS http://127.0.0.1:8800/ || true
```

Use the actual health/status route implemented by `app.py` when known. Do not assume `/` is the health endpoint.

## Ollama

Ollama is used for local LLM inference in Osho-related analysis/ranking/metadata work.

Observed model on compute-03:

```text
qwen3:8b
```

Useful commands:

```bash
ollama ps
ollama list
ps aux | grep '[o]llama'
nvidia-smi
```

On a 6 GB GPU, a model such as `qwen3:8b` may run with a mixed CPU/GPU split. This is expected when full model/context residency does not fit in VRAM.

Do not assume high reported GPU utilization alone means the process is healthy. Check:

- VRAM usage;
- GPU temperature;
- power draw;
- process age;
- model response latency;
- whether another Osho process is competing for VRAM.

## Dashboard / control-plane service

The Osho dashboard backend is hosted on compute-02. Its purpose is to expose current queue/job/worker state to the dashboard UI.

When testing from another host, prefer hostname resolution:

```bash
curl http://compute-02:<dashboard-port>/<status-route>
```

A previous failure mode was not an application failure but DNS/hostname resolution:

```text
curl: (6) Could not resolve host: compute-02
ssh: Could not resolve hostname compute-02: Temporary failure in name resolution
```

If this occurs, fix cluster name resolution before modifying the Osho dashboard service.

## Hostname resolution

Each node should be able to resolve:

```text
compute-01
compute-02
compute-03
core-01
```

Verify from every Osho node:

```bash
getent hosts compute-01
getent hosts compute-02
getent hosts compute-03
ping -c 2 compute-03
ssh compute-03
```

The cluster has previously required `/etc/hosts` consistency so nodes could SSH/ping each other without hard-coded IP addresses.

## GPU inspection

Use this compact query to see the information most useful for Osho:

```bash
nvidia-smi --query-gpu=\
name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu \
--format=csv
```

List GPU processes:

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv
```

Observed examples:

### compute-01

```text
Quadro RTX 3000
6144 MiB VRAM
```

Ollama has been observed consuming roughly half the GPU memory while Osho ranking work was active.

### compute-03

```text
NVIDIA GeForce RTX 2060
6144 MiB VRAM
```

The Osho Uvicorn worker and Ollama have been run concurrently on this host.

## Process inspection

Useful single command:

```bash
pgrep -af 'hook_ranker_v5|retention_qa|osho_autopilot|uvicorn|ollama'
```

This quickly answers:

- Is the autopilot alive?
- Is ranking currently running?
- Is retention QA currently running?
- Is the worker API alive?
- Is a local Ollama model consuming resources?

## Logs

### Autopilot

```bash
sudo journalctl -u osho-autopilot.service -n 100 --no-pager
```

Typical meaningful events include:

```text
NO SAFE V5 CANDIDATES
0 GENUINE APPROVALS — SKIPPED
RECONCILED AS PUBLISHED
```

These are state transitions, not necessarily errors.

## Configuration and secret policy

Configuration can be documented and versioned when it contains non-secret values such as:

- hostnames;
- ports;
- model names;
- path locations;
- ranking parameters;
- feature flags;
- public privacy setting names.

Never commit:

```text
OAuth client_secret.json
OAuth access/refresh tokens
YouTube API credentials
session cookies
SSH private keys
passwords
API bearer tokens
private webhook URLs containing secrets
```

If environment files are used, commit only a sanitized example such as:

```text
.env.example
```

and keep the real `.env` ignored.

## Backup priority

Back up in this order:

1. YouTube upload receipts and durable job state.
2. Metadata and transcripts.
3. Final renders.
4. Source inventory / source references.
5. Application configuration/code if it is not already fully represented in Git.
6. Temporary work directories only when needed for an active recovery.

The application can be redeployed from source control; durable job history and publishing receipts cannot be recreated as safely.
