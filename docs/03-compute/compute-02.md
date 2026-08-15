# compute-02

## Role

Lightweight orchestration and control-plane node. Project Osho intentionally keeps its dashboard/controller responsibilities here so compute-01 remains available for heavy GPU work.

## Network

- Hostname: `compute-02`
- LAN: `192.168.0.88`

All cluster nodes should resolve `compute-02` by hostname. A previous Osho dashboard outage was traced to hostname resolution rather than the dashboard application itself.

## Project Osho

Confirmed Osho dashboard deployment:

```text
/srv/compose/osho-dashboard
```

Confirmed dashboard port:

```text
8787/tcp
```

Responsibilities:

- expose Osho job/queue status;
- expose worker heartbeat/state;
- provide the dashboard UI/backend;
- evolve into the durable scheduling/controller node;
- remain responsive while compute-01/compute-03 are GPU-saturated.

## Voice services

Piper text-to-speech has been deployed on compute-02 using the Wyoming protocol.

Known service:

```text
wyoming-piper
```

Known port:

```text
10200/tcp
```

Known voice model:

```text
en_US-lessac-medium
```

Validation:

```bash
nc -vz compute-02 10200
```

## GPU

No NVIDIA GPU is currently documented/required for this node. Osho's control plane should not assume `nvidia-smi` exists on compute-02.

## Operational checks

```bash
getent hosts compute-02
ssh compute-02
ss -lntp | grep -E ':8787|:10200'
docker ps
```

When the dashboard is unreachable, verify DNS/hosts resolution and the TCP listener before changing application code.
