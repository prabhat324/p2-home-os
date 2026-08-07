#!/usr/bin/env bash
set -u

echo "========================================="
echo " P² Compute OS Verification"
echo "========================================="

check_command() {
    local label="$1"
    local command="$2"

    printf "%-28s" "$label"

    if bash -lc "$command" >/dev/null 2>&1; then
        echo "PASS"
    else
        echo "FAIL"
    fi
}

echo
echo "System"
echo "------"
hostnamectl --static
grep PRETTY_NAME /etc/os-release
uname -r
free -h

echo
echo "Storage"
echo "-------"
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,MODEL
df -h / /srv 2>/dev/null || true

echo
echo "Services and tools"
echo "------------------"
check_command "Docker installed" "command -v docker"
check_command "Docker service active" "systemctl is-active --quiet docker"
check_command "Docker Compose installed" "docker compose version"
check_command "NVIDIA driver available" "command -v nvidia-smi"
check_command "NVIDIA GPU available" "nvidia-smi"
check_command "NVIDIA runtime configured" "docker info | grep -qi nvidia"
check_command "XFS /srv mounted" "findmnt -n /srv"
check_command "SSH service active" "systemctl is-active --quiet ssh"
check_command "Time synchronization active" "timedatectl show -p NTPSynchronized --value | grep -qx yes"

echo
echo "GPU"
echo "---"
nvidia-smi 2>/dev/null || true

echo
echo "Temperatures"
echo "------------"
sensors 2>/dev/null || true
