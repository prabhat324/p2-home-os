#!/bin/bash
set -e

OUTPUT="/opt/p2-home-os/inventory/system-snapshot.txt"

{
    echo "P² Home OS System Snapshot"
    echo "Generated: $(date)"
    echo
    echo "Hostname:"
    hostname
    echo
    echo "IP addresses:"
    hostname -I
    echo
    echo "Operating system:"
    cat /etc/os-release
    echo
    echo "Storage:"
    df -h
    echo
    echo "Block devices:"
    lsblk -o NAME,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS
    echo
    echo "Docker containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo
    echo "Failed services:"
    systemctl --failed --no-pager || true
} > "$OUTPUT"

echo "Snapshot saved to $OUTPUT"
