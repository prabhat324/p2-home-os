#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo bash bootstrap-root.sh" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ffmpeg mediainfo imagemagick sox rubberband-cli \
  python3 python3-venv python3-pip python3-dev \
  git curl jq rsync inotify-tools sqlite3 \
  fonts-dejavu-core fonts-liberation2 fonts-noto-core fonts-noto-color-emoji \
  libgl1 libglib2.0-0 libsndfile1 nvtop htop tmux smartmontools nvme-cli

getent group mediaops >/dev/null || groupadd mediaops
usermod -aG mediaops psquare
usermod -aG mediaops p2ops

install -d -o p2ops -g mediaops -m 2775 \
  /srv/media-production/inbox \
  /srv/media-production/work \
  /srv/media-production/output \
  /srv/media-production/review \
  /srv/media-production/archive \
  /srv/media-production/failed \
  /srv/media-production/logs \
  /srv/media-production/assets \
  /srv/media-production/profiles

echo "MEDIA01_ROOT_BOOTSTRAP=ready"
