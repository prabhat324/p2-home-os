#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git curl wget vim nano tree htop btop tmux jq unzip zip rsync \
  smartmontools nvme-cli pciutils usbutils lm-sensors ncdu \
  iftop iotop dnsutils net-tools traceroute nmap \
  software-properties-common ca-certificates gnupg \
  lsb-release bash-completion xfsprogs
