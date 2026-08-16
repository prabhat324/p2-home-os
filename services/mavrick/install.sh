#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run this installer as root." >&2; exit 1; }
case "$(hostname -s)" in
  compute-04) ;;
  *) echo "Project Mavrick installer is restricted to compute-04." >&2; exit 2 ;;
esac

BASE_URL="https://raw.githubusercontent.com/prabhat324/p2-home-os/master/services/mavrick"
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  python3-venv python3-pip ffmpeg v4l-utils alsa-utils libportaudio2 libgomp1 \
  curl ca-certificates

if ! id mavrick >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/mavrick --shell /usr/sbin/nologin mavrick
fi
usermod -aG video,audio,render mavrick

install -d -o root -g root -m 0755 /opt/mavrick
install -d -o root -g root -m 0755 /etc/mavrick
install -d -o mavrick -g mavrick -m 0700 /var/lib/mavrick/models/whisper
install -d -o mavrick -g mavrick -m 0700 /var/lib/mavrick/models/piper

curl -fsSL "$BASE_URL/mavrick.py" -o /opt/mavrick/mavrick.py
curl -fsSL "$BASE_URL/requirements.txt" -o /opt/mavrick/requirements.txt
curl -fsSL "$BASE_URL/mavrick.service" -o /etc/systemd/system/mavrick.service
curl -fsSL "$BASE_URL/config.env" -o /etc/mavrick/config.env
chmod 0755 /opt/mavrick/mavrick.py
chmod 0644 /opt/mavrick/requirements.txt /etc/systemd/system/mavrick.service /etc/mavrick/config.env

python3 -m venv /opt/mavrick/venv
/opt/mavrick/venv/bin/pip install --upgrade pip wheel
/opt/mavrick/venv/bin/pip install -r /opt/mavrick/requirements.txt

VOICE_DIR="/var/lib/mavrick/models/piper"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium"
curl -fL "$VOICE_BASE/en_US-amy-medium.onnx" \
  -o "$VOICE_DIR/en_US-amy-medium.onnx.part"
curl -fL "$VOICE_BASE/en_US-amy-medium.onnx.json" \
  -o "$VOICE_DIR/en_US-amy-medium.onnx.json.part"
test -s "$VOICE_DIR/en_US-amy-medium.onnx.part"
test -s "$VOICE_DIR/en_US-amy-medium.onnx.json.part"

# User-selected single-voice policy: remove prior Piper models only after Amy downloads.
find "$VOICE_DIR" -maxdepth 1 -type f \
  \( -name '*.onnx' -o -name '*.onnx.json' \) -delete
mv "$VOICE_DIR/en_US-amy-medium.onnx.part" \
  "$VOICE_DIR/en_US-amy-medium.onnx"
mv "$VOICE_DIR/en_US-amy-medium.onnx.json.part" \
  "$VOICE_DIR/en_US-amy-medium.onnx.json"
chown mavrick:mavrick \
  "$VOICE_DIR/en_US-amy-medium.onnx" \
  "$VOICE_DIR/en_US-amy-medium.onnx.json"
chmod 0600 \
  "$VOICE_DIR/en_US-amy-medium.onnx" \
  "$VOICE_DIR/en_US-amy-medium.onnx.json"
runuser -u mavrick -- /opt/mavrick/venv/bin/python - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("tiny.en", device="cpu", compute_type="int8", download_root="/var/lib/mavrick/models/whisper")
print("WHISPER_MODEL=ready")
PY

/opt/mavrick/venv/bin/python -m py_compile /opt/mavrick/mavrick.py
systemctl daemon-reload
systemctl enable mavrick.service
systemctl restart mavrick.service
sleep 5

echo "MAVRICK_SERVICE=$(systemctl is-active mavrick.service || true)"
echo "MAVRICK_CAMERA=$(readlink -f /dev/v4l/by-id/*C930e*video-index0 2>/dev/null || echo waiting)"
echo "MAVRICK_PRIVACY=local-only; media buffers are RAM-only"
systemctl status mavrick.service --no-pager -l | tail -n 20
