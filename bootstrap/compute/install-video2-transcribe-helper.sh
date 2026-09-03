#!/usr/bin/env bash
set -euo pipefail
tmp_helper="$(mktemp)"
tmp_sudoers="$(mktemp)"
trap 'rm -f "$tmp_helper" "$tmp_sudoers"' EXIT
curl -fsSL "https://raw.githubusercontent.com/prabhat324/p2-home-os/ops-control/ops/privileged/p2ops-transcribe-srt" -o "$tmp_helper"
grep -q 'drive_id=1d6b1UNjcs3CnVWPxqzhXWh7ApnGzjkuN' "$tmp_helper"
sudo install -o root -g root -m 0755 "$tmp_helper" /usr/local/sbin/p2ops-transcribe-srt
printf '%s\n' 'p2ops ALL=(root) NOPASSWD: /usr/local/sbin/p2ops-transcribe-srt video2-20260903' > "$tmp_sudoers"
sudo visudo -cf "$tmp_sudoers"
sudo install -o root -g root -m 0440 "$tmp_sudoers" /etc/sudoers.d/p2ops-transcribe-srt
echo "Video2 transcription helper installed."
