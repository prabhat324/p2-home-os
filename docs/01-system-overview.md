# System Overview

## Purpose

The P² Home OS server provides:

- Home media streaming
- Personal music streaming
- Network storage
- Smart-home management
- Security-camera integration
- DNS-based ad and tracker blocking
- Remote access
- Server monitoring
- Automated media organization
- Future private photo and document hosting

## Server

- Hostname: `media-server`
- Operating system: Debian GNU/Linux 13
- Kernel architecture: ARM64
- Hardware: Raspberry Pi 5
- Memory: approximately 8 GB
- Local IPv4 address: `192.168.0.203`
- Tailscale IPv4 address: `100.67.245.78`

## Main Dashboard

- Homepage direct URL: `http://192.168.0.203:3000`
- Friendly URL: `http://dashboard.home.arpa`

## Architecture

Internet
→ Rogers gateway
→ TP-Link BE19000 Wi-Fi 7 router
→ TP-Link BE9300 extenders
→ Raspberry Pi 5
→ Docker services and attached storage

## Current Platform Components

- Jellyfin
- Homepage
- AdGuard Home
- Caddy
- Tailscale
- Home Assistant
- Scrypted
- Navidrome
- Radarr
- Sonarr
- Bazarr
- Jellyseerr
- Prowlarr
- qBittorrent
- Glances
- Uptime Kuma
- Samba

# System Overview

## Server

- Hostname: `media-server`
- Hardware: Raspberry Pi 5
- Memory: 8 GB
- Operating system: Debian GNU/Linux 13
- Architecture: ARM64
- Local IP: `192.168.0.203`
- Tailscale IP: `100.67.245.78`

## Purpose

The server provides:

- Media streaming
- Music streaming
- Network storage
- Smart-home control
- Camera integration
- DNS ad blocking
- Monitoring
- Remote access
- Automated media management
- Future private photo hosting

## Main URLs

- Homepage: `http://dashboard.home.arpa`
- Jellyfin: `http://jellyfin.home.arpa`
- Navidrome: `http://music.home.arpa`
- Home Assistant: `http://192.168.0.203:8123`
- AdGuard Home: `http://adguard.home.arpa`
- Scrypted: `http://cameras.home.arpa`
