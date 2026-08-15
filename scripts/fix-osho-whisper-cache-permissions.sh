#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${OSHO_WORKER_CONTAINER:-osho-worker}"
FALLBACK_MODELS="${OSHO_MODELS_DIR:-/srv/osho/models}"
MODEL_NAME="${OSHO_WHISPER_MODEL_CACHE:-models--Systran--faster-whisper-medium}"

echo "========================================"
echo " OSHO WHISPER CACHE PERMISSION FIX"
echo "========================================"

MODELS_DIR=""

if command -v docker >/dev/null 2>&1 && docker inspect "$CONTAINER" >/dev/null 2>&1; then
    MODELS_DIR="$(
        docker inspect \
            -f '{{range .Mounts}}{{if eq .Destination "/models"}}{{.Source}}{{end}}{{end}}' \
            "$CONTAINER" 2>/dev/null || true
    )"
fi

if [[ -z "$MODELS_DIR" ]]; then
    MODELS_DIR="$FALLBACK_MODELS"
fi

MODEL_DIR="${MODELS_DIR%/}/${MODEL_NAME}"

if [[ ! -d "$MODEL_DIR" ]]; then
    echo "Model cache not found:"
    echo "  $MODEL_DIR"
    exit 1
fi

TARGET_UID=""
TARGET_GID=""

if command -v docker >/dev/null 2>&1 \
    && docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -qx true; then
    TARGET_UID="$(docker exec "$CONTAINER" id -u 2>/dev/null || true)"
    TARGET_GID="$(docker exec "$CONTAINER" id -g 2>/dev/null || true)"
fi

if [[ -z "$TARGET_UID" || -z "$TARGET_GID" ]]; then
    TARGET_UID="$(id -u psquare)"
    TARGET_GID="$(id -g psquare)"
fi

echo "Container:  $CONTAINER"
echo "Models:     $MODELS_DIR"
echo "Model cache: $MODEL_DIR"
echo "Writer UID:GID: ${TARGET_UID}:${TARGET_GID}"

echo
echo "=== BEFORE ==="
find "$MODEL_DIR" -maxdepth 2 \
    -printf '%u:%g %m %p\n' 2>/dev/null \
    | head -40 || true

echo
echo "=== APPLY ==="
sudo chown -R "${TARGET_UID}:${TARGET_GID}" "$MODEL_DIR"
sudo chmod -R u+rwX "$MODEL_DIR"

echo
echo "=== VERIFY HOST ==="
find "$MODEL_DIR" -maxdepth 2 \
    -printf '%u:%g %m %p\n' 2>/dev/null \
    | head -40 || true

if command -v docker >/dev/null 2>&1 \
    && docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -qx true; then
    echo
    echo "=== VERIFY INSIDE WORKER ==="
    docker exec "$CONTAINER" sh -lc '
        set -eu
        test -r /models/models--Systran--faster-whisper-medium
        test -w /models/models--Systran--faster-whisper-medium
        for d in refs trees; do
            if [ -d "/models/models--Systran--faster-whisper-medium/$d" ]; then
                test -w "/models/models--Systran--faster-whisper-medium/$d"
            fi
        done
        echo "Whisper model cache is readable and writable."
    '
else
    echo
    echo "Worker container is not running; host ownership was fixed but container write test was skipped."
fi

echo
echo "No Osho job, Autopilot service, Ollama process, or calibration process was restarted."
