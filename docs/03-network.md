# Network Architecture

## LAN addressing

| Host | LAN address | Notes |
|---|---:|---|
| `core-01` / `media-server` | `192.168.0.203` | Storage/infrastructure |
| `compute-01` | `192.168.0.31` | Primary GPU/application node |
| `compute-02` | `192.168.0.88` | Osho control plane / Piper |
| `compute-03` | `192.168.0.158` wired | Secondary GPU worker |

compute-03 has also been observed on Wi-Fi at `192.168.0.150`, but wired Ethernet has the preferred route metric and should be treated as the production path.

## Hostname resolution

Every cluster node should resolve:

```text
core-01
media-server
compute-01
compute-02
compute-03
```

The cluster has used consistent `/etc/hosts` entries where local DNS did not yet provide these names.

Validation:

```bash
getent hosts compute-01 compute-02 compute-03 media-server
ping -c 2 compute-03
ssh compute-03
```

A hostname-resolution failure can look like an application outage. Fix resolution before changing services.

## Key service ports

| Service | Host | Port |
|---|---|---:|
| Jellyfin | compute-01 | 8096 |
| Open WebUI | compute-01 | 3000 |
| Wyoming Whisper | compute-01 | 10300 |
| Project Osho dashboard | compute-02 | 8787 |
| Wyoming Piper | compute-02 | 10200 |
| Project Osho worker API | compute-03 | 8800 |

## Storage network

The 8 TB media drive is physically hosted by core-01 and exported to compute-01 via NFSv4.2:

```text
192.168.0.203:/mnt/media -> /mnt/media
```

The compute-01 mount is read-only.

## Remote access

Tailscale is the preferred remote-access mechanism.

Confirmed addresses include:

- core-01: `100.67.245.78`
- compute-01: `100.65.64.4`

Avoid direct public port forwarding for internal dashboards and storage services.

## Wired switching

A Cisco SG350-10MP is used in the wired network path. Consistent DNS/hosts configuration matters more than hard-coding DHCP addresses into application configs.
