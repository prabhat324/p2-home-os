#!/usr/bin/env bash
set -euo pipefail

EXPECTED_HOSTNAME="compute-01"

echo "Running P² Compute preflight checks..."

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Run this bootstrap as a regular sudo-capable user, not root."
    exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required."
    exit 1
fi

if [[ "$(hostnamectl --static)" != "$EXPECTED_HOSTNAME" ]]; then
    echo "Warning: hostname is $(hostnamectl --static), expected $EXPECTED_HOSTNAME."
fi

if [[ "$(dpkg --print-architecture)" != "amd64" ]]; then
    echo "Unsupported architecture: $(dpkg --print-architecture)"
    exit 1
fi

if ! grep -q '^ID=ubuntu$' /etc/os-release; then
    echo "This bootstrap expects Ubuntu."
    exit 1
fi

echo "Preflight checks passed."
