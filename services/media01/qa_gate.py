#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
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
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"])
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", p.stderr, re.S)
    return json.loads(blocks[-1]) if blocks else {}


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

    black = detect(args.video, "blackdetect=d=0.75:pix_th=0.10")
    black_segments = re.findall(r"black_start:([0-9.]+).*?black_end:([0-9.]+).*?black_duration:([0-9.]+)", black)
    if black_segments:
        failures.append(f"Detected {len(black_segments)} black segment(s) >= 0.75s")
    freeze = detect(args.video, "freezedetect=n=-50dB:d=2")
    freeze_events = re.findall(r"freeze_duration: ([0-9.]+)", freeze)
    if freeze_events:
        failures.append(f"Detected {len(freeze_events)} freeze event(s) >= 2s")
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
        "probe": info, "loudness": audio,
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
