#!/usr/bin/env bash
set -euo pipefail

DATA_DEVICE="${P2_DATA_DEVICE:-/dev/nvme1n1}"
DATA_PARTITION="${DATA_DEVICE}p1"
MOUNT_POINT="/srv"
LABEL="P2_SRV"

echo "Target data device: $DATA_DEVICE"

if findmnt -n "$MOUNT_POINT" >/dev/null 2>&1; then
    echo "$MOUNT_POINT is already mounted. No storage changes required."
    exit 0
fi

if [[ "${P2_ALLOW_DISK_WIPE:-no}" != "yes" ]]; then
    echo "Storage is not configured."
    echo "This operation can erase $DATA_DEVICE."
    echo "To permit formatting on a fresh build, run:"
    echo "P2_ALLOW_DISK_WIPE=yes P2_DATA_DEVICE=$DATA_DEVICE $0"
    exit 1
fi

read -r -p "Type ERASE-$DATA_DEVICE to confirm destructive formatting: " CONFIRM

if [[ "$CONFIRM" != "ERASE-$DATA_DEVICE" ]]; then
    echo "Confirmation failed. Aborting."
    exit 1
fi

sudo wipefs -a "$DATA_DEVICE"
sudo parted -s "$DATA_DEVICE" mklabel gpt
sudo parted -s "$DATA_DEVICE" mkpart primary xfs 1MiB 100%
sudo partprobe "$DATA_DEVICE"
sudo udevadm settle
sudo mkfs.xfs -f -L "$LABEL" "$DATA_PARTITION"

UUID="$(sudo blkid -s UUID -o value "$DATA_PARTITION")"

sudo mkdir -p "$MOUNT_POINT"

if ! grep -q "UUID=$UUID " /etc/fstab; then
    echo "UUID=$UUID $MOUNT_POINT xfs defaults,noatime 0 2" | \
      sudo tee -a /etc/fstab >/dev/null
fi

sudo mount -a
findmnt "$MOUNT_POINT"
