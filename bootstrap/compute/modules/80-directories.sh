#!/usr/bin/env bash
set -euo pipefail

if ! findmnt -n /srv >/dev/null 2>&1; then
    echo "/srv is not mounted. Refusing to create runtime data on the OS disk."
    exit 1
fi

sudo mkdir -p \
  /srv/appdata \
  /srv/compose \
  /srv/models \
  /srv/transcode \
  /srv/cache \
  /srv/backups \
  /srv/logs \
  /srv/scripts \
  /srv/downloads

sudo chown -R "$USER":"$USER" \
  /srv/appdata \
  /srv/compose \
  /srv/models \
  /srv/transcode \
  /srv/cache \
  /srv/backups \
  /srv/logs \
  /srv/scripts \
  /srv/downloads

docker network inspect p2-network >/dev/null 2>&1 || \
  docker network create p2-network

echo "P² runtime structure created."
