# Project Osho Operations

## Daily health check

Run from the relevant hosts:

```bash
systemctl is-active osho-autopilot.service || true
pgrep -af 'osho_autopilot|hook_ranker_v5|retention_qa|uvicorn|ollama'
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv
```

On compute-02, verify the dashboard/controller endpoint and on compute-03 verify the worker API on TCP 8800.

## Autopilot

```bash
sudo systemctl status osho-autopilot.service --no-pager
sudo journalctl -u osho-autopilot.service -n 100 --no-pager
sudo journalctl -u osho-autopilot.service -f
```

Do not restart during a long-running stage until you know the stage is safely resumable.

## Worker checks

```bash
getent hosts compute-01 compute-02 compute-03
ssh compute-03 'hostname; uptime'
ssh compute-03 "ss -lntp | grep ':8800' || true"
```

If a hostname fails to resolve, fix cluster name resolution before changing application code.

## GPU checks

```bash
nvidia-smi
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv
```

On compute-01 the Quadro RTX 3000 has 6 GB VRAM; on compute-03 the RTX 2060 has 6 GB VRAM. Ollama and Osho stages may contend for this memory.

## Expected non-error states

The following log messages can be healthy decisions:

```text
NO SAFE V5 CANDIDATES
0 GENUINE APPROVALS — SKIPPED
RECONCILED AS PUBLISHED
```

A skipped source is not the same as a failed job.

## Failure triage order

1. Verify host resolution and network connectivity.
2. Verify the process/service is alive.
3. Verify disk paths and free space.
4. Verify GPU/VRAM pressure.
5. Inspect the latest job state and work directory.
6. Inspect autopilot/worker logs.
7. Check for an existing upload receipt before retrying publishing.
8. Retry only the failed stage when possible.

## Safe restart principles

- Prefer idempotent stage restarts.
- Never blindly re-upload a job with a receipt/video ID.
- Preserve partial work until the failure is understood.
- Avoid deleting transcripts merely to force a rerun.
- Keep test-mode fixtures incapable of public upload.

## compute-03 deployment note

When creating `/srv/compose/osho-worker` remotely, `sudo` over non-interactive SSH can fail with:

```text
sudo: A terminal is required to authenticate
```

Create privileged destination directories in an interactive session first, or use an approved non-interactive privilege method. Do not assume `rsync` created a destination after a failed `sudo` command.

## Publishing recovery

If upload state and queue state disagree:

1. inspect `/srv/osho/youtube/receipts`;
2. validate the recorded video ID;
3. reconcile the local job to published;
4. do not upload a second copy merely because the queue still says `ready_to_upload`.

## Change management

Whenever ranking, QA, or publishing behavior changes, record:

- date;
- affected host/service;
- previous behavior;
- new behavior;
- validation command/results;
- rollback method.

This is especially important for zero-touch public publishing changes.
