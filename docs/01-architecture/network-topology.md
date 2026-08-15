# Network Topology

```text
                         Home LAN 192.168.0.0/24
                                  |
                         Cisco SG350-10MP
                                  |
          +-----------------------+-----------------------+
          |                       |                       |
  core-01 / media-server      compute-01              compute-02
     192.168.0.203           192.168.0.31            192.168.0.88
  storage + infrastructure   GPU/applications        control plane
          |                                               |
          | NFSv4.2 read-only                              | Osho dashboard :8787
          +-----------------------> compute-01              | Piper :10200
                                                          |
                                                   compute-03
                                                   192.168.0.158
                                                   RTX 2060 worker
                                                   Osho :8800
```

## Preferred paths

- Use wired Ethernet for compute nodes where available.
- compute-03 has also been observed at Wi-Fi address `192.168.0.150`; wired `192.168.0.158` is preferred.
- Use hostnames in service configuration instead of hard-coded IPs when local resolution is reliable.
- Use Tailscale for remote access rather than public port forwarding.

## Cluster names

```text
media-server / core-01
compute-01
compute-02
compute-03
```

## Storage path

```text
core-01:/mnt/media
   -> NFSv4.2 read-only
compute-01:/mnt/media
   -> Jellyfin
```

## Key service ports

```text
compute-01:8096   Jellyfin
compute-01:3000   Open WebUI
compute-01:10300  Wyoming Whisper
compute-02:8787   Project Osho dashboard
compute-02:10200  Wyoming Piper
compute-03:8800   Project Osho worker API
```
