#!/usr/bin/env bash
set -euo pipefail
root=/srv/media-production
job=wasaga-report-2026
docker build -t psquare/media-post:0.1 /srv/compose/media-post
docker run --rm --gpus all \
  -v "$root:/work" \
  psquare/media-post:0.1 \
  --project /app/project.json \
  --master "/work/inbox/$job/master.mp4" \
  --captions "/work/inbox/$job/captions.srt" \
  --assets "/work/inbox/$job" \
  --output "/work/output/$job"

