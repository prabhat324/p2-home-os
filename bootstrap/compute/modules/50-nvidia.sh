#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y ubuntu-drivers-common

echo "Installing Ubuntu's recommended NVIDIA driver..."
sudo ubuntu-drivers install

curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor --yes \
  -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -fsSL \
  https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  nvidia-container-toolkit

sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

echo "NVIDIA installation completed."
echo "A reboot may be required before nvidia-smi succeeds."
