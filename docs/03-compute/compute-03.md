# compute-03

## Role

Secondary GPU worker for Project Osho and local AI workloads. It expands processing capacity without moving the control plane away from compute-02.

## Hardware

- NVIDIA GeForce RTX 2060
- 6 GB VRAM

## Network

- Hostname: `compute-03`
- Wired LAN observed: `192.168.0.158`
- Wi-Fi also observed at `192.168.0.150`
- Wired Ethernet has the lower route metric and is the preferred production path.

## Project Osho worker

Application path:

```text
/srv/compose/osho-worker
```

Worker process observed:

```text
python3 -m uvicorn app:app --host 0.0.0.0 --port 8800
```

Worker API:

```text
8800/tcp
```

## Ollama

Observed model:

```text
qwen3:8b
```

The model has operated with a mixed CPU/GPU split because the 6 GB GPU cannot conveniently hold the entire model/context at once.

Useful checks:

```bash
ollama ps
nvidia-smi
pgrep -af 'uvicorn|ollama|osho'
ss -lntp | grep ':8800'
```

## Deployment lesson

Creating `/srv/compose/osho-worker` remotely failed when `sudo` was invoked without a terminal:

```text
sudo: A terminal is required to authenticate
```

The destination directory must exist with appropriate ownership before `rsync` can copy the worker software.

## Current architecture

compute-03 is a worker, not the scheduler. The intended layout is:

```text
compute-02 controller/dashboard
  -> compute-01 primary worker
  -> compute-03 secondary worker
```

Future worker scheduling should consider free VRAM, utilization, current job count, and model availability.
