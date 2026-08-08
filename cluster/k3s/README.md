# P² Compute Cluster

K3s-based GPU compute cluster for P² Home OS.

## Current Cluster

### compute-01

- Role: K3s server, control-plane, etcd and worker
- LAN: 192.168.0.31
- Tailscale: 100.65.64.4
- OS: Ubuntu 26.04 LTS
- GPU: NVIDIA Quadro RTX 3000 6 GB
- NVIDIA driver: 595.84
- K3s data: /srv/k3s
- Embedded etcd: enabled
- Secrets encryption: enabled
- Traefik: disabled
- ServiceLB: disabled

## Networking

- Pod network: 10.42.0.0/16
- Service network: 10.43.0.0/16
- Kubernetes API: TCP 6443
- Kubernetes API allowed through Tailscale
- Wired Ethernet is used as the node address

## NVIDIA GPU Support

The NVIDIA Kubernetes device plugin is deployed through the
K3s Helm controller.

Manifest:

cluster/k3s/addons/nvidia-device-plugin/helmchart.yaml

GPU nodes are explicitly labeled:

sudo k3s kubectl label node <node> \
  nvidia.com/gpu.present=true --overwrite

compute-01 currently reports:

nvidia.com/gpu: 1

A CUDA test pod successfully ran nvidia-smi through Kubernetes
and detected the Quadro RTX 3000.

## Future compute-02

A future compute node should:

1. Run compatible Ubuntu/Linux.
2. Install the NVIDIA driver.
3. Install NVIDIA Container Toolkit.
4. Join the existing K3s cluster.
5. Use wired Ethernet for normal cluster/data traffic.
6. Be labeled as a compute/GPU node.
7. Receive the NVIDIA device plugin automatically.

Example labels:

sudo k3s kubectl label node compute-02 \
  p2-role=compute \
  p2-gpu=nvidia \
  nvidia.com/gpu.present=true \
  --overwrite

## Important

Do NOT commit:

- K3s server token
- kubeconfig credentials
- etcd snapshots
- TLS private keys
- application secrets
- Lucy voice samples or private voice models

Runtime K3s state remains under /srv/k3s.

## Verification

Cluster:

sudo k3s kubectl get nodes -o wide

Pods:

sudo k3s kubectl get pods -A

GPU:

sudo k3s kubectl get node compute-01 \
  -o jsonpath='capacity={.status.capacity.nvidia\.com/gpu} allocatable={.status.allocatable.nvidia\.com/gpu}{"\n"}'

Expected:

capacity=1 allocatable=1
