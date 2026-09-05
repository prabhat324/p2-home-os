#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("MEDIA01_ROOT", "/srv/media-production"))
APP = Path(__file__).resolve().parent
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".mkv", ".mts", ".m2ts"}

# The systemd unit intentionally protects /home. Keep all downloaded models and
# runtime caches on the production volume, where the service has write access.
CACHE_ROOT = ROOT / "work" / ".cache"
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))
os.environ.setdefault("HF_HOME", str(CACHE_ROOT / "huggingface"))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write_status(job, state, **details):
    payload = {"job": job.name, "state": state, "updated_at": stamp(), **details}
    path = ROOT / "logs" / f"{job.name}.status.json"
    path.write_text(json.dumps(payload, indent=2))


def command(cmd, log):
    with log.open("a") as handle:
        handle.write(f"\n[{stamp()}] {' '.join(map(str, cmd))}\n")
        handle.flush()
        return subprocess.run([str(x) for x in cmd], stdout=handle, stderr=subprocess.STDOUT, check=False)


def source_for(job):
    candidates = sorted(p for p in job.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    return candidates[0] if candidates else None


def make_review(job):
    source = source_for(job)
    if not source:
        return
    manifest_path = job / "project.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if manifest.get("ready") is not True:
        write_status(job, "WAITING_FOR_READY", instruction="Set project.json ready=true after file transfer completes")
        return
    work = ROOT / "work" / job.name
    review = ROOT / "review" / job.name
    work.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    lock = work / ".processing"
    if lock.exists() or (review / "review-4k.mp4").exists():
        return
    lock.write_text(stamp())
    log = ROOT / "logs" / f"{job.name}.log"
    output = review / "review-4k.mp4"
    try:
        analysis = review / "analysis"
        if manifest.get("purpose") != "acceptance-test" and manifest.get("content_analysis", True):
            write_status(job, "ANALYZING_CONTENT", source=str(source))
            analysis_result = command([
                APP / "venv/bin/python", APP / "content_analyzer.py", source,
                "--output-dir", analysis,
                "--model", manifest.get("transcription_model", "large-v3-turbo"),
                "--language", manifest.get("language", "en"),
            ], log)
            if analysis_result.returncode:
                report_path = analysis / "content-report.json"
                if report_path.exists():
                    content_report = json.loads(report_path.read_text())
                    duplicate_count = len(content_report.get("probable_repeated_spoken_sections", []))
                    raise RuntimeError(
                        f"Content analysis blocked render: {duplicate_count} probable repeated spoken section(s)"
                    )
                raise RuntimeError(
                    f"Content analyzer failed with exit code {analysis_result.returncode}; see {log}"
                )
        write_status(job, "RENDERING", source=str(source))
        vf = "scale=3840:2160:force_original_aspect_ratio=decrease:flags=lanczos,pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-hwaccel", "cuda", "-i", source,
            "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf,
            "-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr",
            "-cq", "17", "-b:v", "35M", "-maxrate", "55M", "-bufsize", "110M",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-af", "loudnorm=I=-14:TP=-1:LRA=11", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2",
            output
        ]
        result = command(cmd, log)
        if result.returncode:
            raise RuntimeError(f"FFmpeg failed with exit code {result.returncode}")
        write_status(job, "QA_RUNNING", review=str(output))
        qa = command([APP / "venv/bin/python", APP / "qa_gate.py", output, "--report", review / "qa-report.json"], log)
        report = json.loads((review / "qa-report.json").read_text())
        if qa.returncode == 0:
            write_status(job, "REVIEW_REQUIRED", review=str(output), qa="PASS",
                         analysis=str(analysis) if analysis.exists() else None,
                         manual_gates=report["manual_gates"])
        else:
            write_status(job, "QA_FAILED", review=str(output), failures=report["failures"])
    except Exception as exc:
        write_status(job, "FAILED", error=str(exc), log=str(log))
    finally:
        lock.unlink(missing_ok=True)


def scan_once():
    for directory in (ROOT / "logs", CACHE_ROOT, CACHE_ROOT / "huggingface"):
        directory.mkdir(parents=True, exist_ok=True)
    for job in sorted((ROOT / "inbox").iterdir()):
        if job.is_dir():
            make_review(job)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    args = ap.parse_args()
    while True:
        scan_once()
        if not args.watch:
            return 0
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())
