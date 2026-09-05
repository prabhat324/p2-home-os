#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def probe(path):
    p = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout)


def rational(value):
    a, b = value.split("/")
    return float(a) / float(b) if float(b) else 0.0


def detect(path, vf):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", vf, "-an", "-f", "null", "-"])
    return p.stderr


def loudness(path):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"])
    if p.returncode: raise RuntimeError("Audio QA failed: " + p.stderr[-2000:])
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", p.stderr, re.S)
    if not blocks: raise RuntimeError("Audio QA produced no measurement")
    return json.loads(blocks[-1])


def repeated_sequences(path, seconds=5):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", "blackdetect=d=0.75:pix_th=0.10,freezedetect=n=-50dB:d=2,fps=1,scale=9:8,format=gray", "-f", "rawvideo", "-"]
    p = subprocess.run(cmd, capture_output=True, check=False)
    if p.returncode: raise RuntimeError("Video QA failed: " + p.stderr.decode(errors="replace")[-2000:])
    frame_size = 9 * 8
    frames = [p.stdout[i:i + frame_size] for i in range(0, len(p.stdout) - frame_size + 1, frame_size)]
    hashes = []
    for frame in frames:
        value = 0
        bit = 0
        for y in range(8):
            row = frame[y * 9:(y + 1) * 9]
            for x in range(8):
                value |= (1 if row[x] > row[x + 1] else 0) << bit
                bit += 1
        hashes.append(value)
    seen, repeats = {}, []
    for i in range(0, max(0, len(hashes) - seconds + 1)):
        signature = tuple(hashes[i:i + seconds])
        previous = seen.get(signature)
        if previous is not None and i - previous >= seconds + 5:
            repeats.append({"first_second": previous, "repeat_second": i, "seconds": seconds})
        else:
            seen[signature] = i
    return repeats[:20], p.stderr.decode(errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--profile", type=Path, default=Path(__file__).with_name("quality-profile.json"))
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    cfg = json.loads(args.profile.read_text())
    info = probe(args.video)
    videos = [s for s in info["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    failures, warnings = [], []
    if not videos:
        failures.append("No video stream")
    if not audios:
        failures.append("No audio stream")
    if videos:
        v = videos[0]
        if int(v.get("width", 0)) < cfg["delivery"]["width"] or int(v.get("height", 0)) < cfg["delivery"]["height"]:
            failures.append(f"Resolution is {v.get('width')}x{v.get('height')}, below required 3840x2160")
        ratio = int(v.get("width", 0)) / max(int(v.get("height", 1)), 1)
        if abs(ratio - 16 / 9) > 0.01:
            failures.append(f"Aspect ratio {ratio:.4f} is not 16:9")
        fps = rational(v.get("avg_frame_rate", "0/1"))
        if fps < 23 or fps > 61:
            warnings.append(f"Unusual frame rate: {fps:.3f}")
    if audios:
        a = audios[0]
        if int(a.get("sample_rate", 0)) != cfg["delivery"]["audio_sample_rate"]:
            failures.append(f"Audio sample rate is {a.get('sample_rate')}, expected 48000")
        if int(a.get("channels", 0)) != cfg["delivery"]["audio_channels"]:
            warnings.append(f"Audio has {a.get('channels')} channel(s), delivery target is stereo")

    repeats, detection_log = repeated_sequences(args.video, int(cfg["qa_gates"]["fail_on_probable_repeated_sequence_seconds"]))
    black_segments = re.findall(r"black_start:([0-9.]+).*?black_end:([0-9.]+).*?black_duration:([0-9.]+)", detection_log)
    if black_segments: failures.append(f"Detected {len(black_segments)} black segment(s) >= 0.75s")
    freeze_events = re.findall(r"freeze_duration: ([0-9.]+)", detection_log)
    if freeze_events: failures.append(f"Detected {len(freeze_events)} freeze event(s) >= 2s; review intentional stills")
    if repeats: failures.append(f"Detected {len(repeats)} probable non-consecutive repeated sequence(s); review static scenes")
    audio = loudness(args.video) if audios else {}
    if audio:
        measured = float(audio.get("input_i", -99))
        peak = float(audio.get("input_tp", 99))
        target = cfg["delivery"]["integrated_loudness_lufs"]
        tol = cfg["delivery"]["loudness_tolerance_lu"]
        if abs(measured - target) > tol:
            failures.append(f"Integrated loudness {measured:.1f} LUFS is outside {target:.1f}±{tol:.1f}")
        if peak > cfg["delivery"]["true_peak_max_dbtp"]:
            failures.append(f"True peak {peak:.1f} dBTP exceeds -1.0 dBTP")

    report = {
        "profile": cfg["profile"], "file": str(args.video),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures, "warnings": warnings,
        "probe": info, "loudness": audio, "probable_repeated_sequences": repeats,
        "manual_gates": [
            "Full timeline review completed",
            "No cropped faces, text, or source material",
            "Captions remain in bottom safe area and do not cover content",
            "All zooms are slow, eased, and editorially motivated",
            "No repeated footage or duplicated spoken section",
            "Every graph communicates real labeled data and cites its source",
            "Names, numbers, quotations, dates, and protected terms verified",
            "Political presentation remains neutral and avoids gotcha editing"
        ]
    }
    out = args.report or args.video.with_suffix(".qa.json")
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": report["status"], "report": str(out), "failures": failures, "warnings": warnings}, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())

