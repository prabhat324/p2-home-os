# Network Architecture

## Primary Addresses

| Service | Direct Address | Friendly Address |
|---|---|---|
| Homepage | `http://192.168.0.203:3000` | `http://dashboard.home.arpa` |
| Jellyfin | `http://192.168.0.203:8096` | `http://jellyfin.home.arpa` |
| Jellyseerr | `http://192.168.0.203:5055` | `http://requests.home.arpa` |
| Radarr | `http://192.168.0.203:7878` | `http://radarr.home.arpa` |
| Sonarr | `http://192.168.0.203:8989` | `http://sonarr.home.arpa` |
| Bazarr | `http://192.168.0.203:6767` | `http://bazarr.home.arpa` |
| Prowlarr | `http://192.168.0.203:9696` | `http://prowlarr.home.arpa` |
| qBittorrent | `http://192.168.0.203:8080` | `http://downloads.home.arpa` |
| Uptime Kuma | `http://192.168.0.203:3001` | `http://status.home.arpa` |
| Glances | `http://192.168.0.203:61208` | `http://monitor.home.arpa` |
| AdGuard Home | `http://192.168.0.203:3002` | `http://adguard.home.arpa` |
| Scrypted | `https://192.168.0.203:10443` | `http://cameras.home.arpa` |
| Home Assistant | `http://192.168.0.203:8123` | Planned: `http://home.home.arpa` |
| Navidrome | `http://192.168.0.203:4533` | `http://music.home.arpa` |

## DNS

- AdGuard Home runs on the Raspberry Pi.
- DNS server address: `192.168.0.203`
- Internal wildcard domain: `*.home.arpa`
- Internal names resolve to `192.168.0.203`.
- Caddy selects the destination service based on hostname.

## Remote Access

- Tailscale is installed on the Raspberry Pi.
- Server Tailscale address: `100.67.245.78`
- Remote services should be accessed through Tailscale rather than exposed directly to the public internet.

## Important Note

Devices must use AdGuard Home as their DNS server to resolve `*.home.arpa` names.
