# Architecture Overview

The authoritative current platform overview is [System Overview](../01-system-overview.md).

## Current node split

```text
core-01 / media-server  -> storage + always-on infrastructure
compute-01              -> primary GPU/application workloads
compute-02              -> lightweight orchestration/control plane
compute-03              -> secondary GPU worker
```

For network relationships see [Network Topology](network-topology.md). For application placement see [Service Map](service-map.md).

This page intentionally stays concise so it does not become a second, conflicting copy of the as-built state.
