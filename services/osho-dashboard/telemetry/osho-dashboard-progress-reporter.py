#!/usr/bin/env python3
"""Read-only Project Osho operational progress reporter.

This sidecar exists because the current zero-touch autopilot no longer emits the
legacy dashboard operational heartbeat. It never mutates Osho pipeline state;
it only reads the authoritative catalog/process/artifact state and posts a
normalized current-job view to the dashboard APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"
DASHBOARD_BASE = os.environ.get("OSHO_DASHBOARD_BASE", "http://192.168.0.88:8787")
HEARTBEAT_URL = f"{DASHBOARD_BASE}/api/worker/heartbeat"
JOB_URL = f"{DASHBOARD_BASE}/api/jobs/update"
DASHBOARD_URL = f"{DASHBOARD_BASE}/api/dashboard"
WORKER_HEALTH_URL = os.environ.get("OSHO_WORKER_HEALTH_URL", "http://127.0.0.1:8800/health")
INTERVAL = float(os.environ.get("OSHO_PROGRESS_INTERVAL", "5"))
CATALOG_DB = Path(os.environ.get("OSHO_CATALOG_DB", "/srv/osho/library/catalog/catalog.sqlite"))
TRANSCRIPTS = Path("/srv/osho/transcripts")
CANDIDATES = Path("/srv/osho/candidates")
WORK_ROOT = Path("/srv/osho/work")
AUTOPILOT_LOGS = Path("/srv/osho/logs/autopilot")

TERMINAL = {"published", "uploaded", "failed", "skipped", "done", "complete", "completed", "cancelled", "canceled"}
DUAL_GPU_STAGES = {"hook_ranking", "retention_qa", "remote_qa"}

STAGE_BASE = {
    "downloading": 5,
    "transcribing": 20,
    "candidate_extraction": 32,
    "hook_ranking": 45,
    "retention_qa": 65,
    "remote_qa": 68,
    "rendering": 80,
    "rendering_approved_clips": 82,
    "generating_visuals": 80,
    "quality_check": 88,
    "metadata": 92,
    "ready_to_upload": 94,
    "uploading": 97,
    "published": 100,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp(value: object, lo: float = 0, hi: float = 100) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(lo, min(hi, number))


def http_json(url: str, payload: dict | None = None, timeout: float = 4) -> dict | None:
    try:
        if payload is None:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"Project-Osho-Progress/{VERSION}"},
            )
        else:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"Project-Osho-Progress/{VERSION}",
                },
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def worker_healthy() -> bool:
    data = http_json(WORKER_HEALTH_URL, timeout=3)
    return bool(data and str(data.get("status", "")).lower() in {"ok", "healthy"})


def autopilot_active() -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "osho-autopilot.service"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            check=False,
        )
        return proc.stdout.strip() == "active"
    except Exception:
        return False


def process_lines() -> list[str]:
    try:
        output = subprocess.check_output(
            ["ps", "-eo", "args="],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return [line.strip() for line in output.splitlines() if line.strip()]
    except Exception:
        return []


def read_catalog() -> tuple[sqlite3.Connection, sqlite3.Row | None, sqlite3.Row | None]:
    conn = sqlite3.connect(f"file:{CATALOG_DB}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    active = conn.execute(
        """
        SELECT *
        FROM osho_autopilot_state
        WHERE lower(trim(status)) = 'processing'
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).fetchone()
    source = None
    if active is not None:
        source = conn.execute(
            "SELECT source_id, title, duration_seconds FROM discourses WHERE source_id = ? LIMIT 1",
            (active["source_id"],),
        ).fetchone()
    return conn, active, source


def transcript_exists(source_id: str) -> bool:
    if not TRANSCRIPTS.exists():
        return False
    for path in TRANSCRIPTS.glob(f"{source_id}*"):
        name = path.name.lower()
        if "retention-qa" in name or "retention_qa" in name:
            continue
        if path.is_file() and path.stat().st_size > 0:
            return True
    return False


def qa_exists(source_id: str) -> bool:
    if not TRANSCRIPTS.exists():
        return False
    return any(
        p.is_file() and p.stat().st_size > 0
        for p in TRANSCRIPTS.glob(f"{source_id}*retention*qa*.json")
    )


def rank_exists(source_id: str) -> bool:
    paths = [
        CANDIDATES / f"{source_id}.hook-ranked-v5.json",
        CANDIDATES / f"{source_id}.hook_ranked_v5.json",
    ]
    return any(p.exists() and p.stat().st_size > 0 for p in paths)


def active_worker_job(source_id: str) -> dict | None:
    if not WORK_ROOT.exists():
        return None
    matches: list[tuple[float, dict]] = []
    for path in WORK_ROOT.glob("*/job.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("source_id") or "") != source_id:
            continue
        status = str(data.get("status") or data.get("stage") or "").lower()
        if status in TERMINAL:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        matches.append((mtime, data))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def progress_ratio_from_log(path: Path, keywords: tuple[str, ...]) -> float | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]
    except OSError:
        return None
    ratio_re = re.compile(r"\b(\d{1,4})\s*(?:/|\bof\b)\s*(\d{1,4})\b", re.I)
    for line in reversed(lines):
        low = line.lower()
        if not any(word in low for word in keywords):
            continue
        for match in reversed(list(ratio_re.finditer(line))):
            current, total = int(match.group(1)), int(match.group(2))
            if 1 < total <= 2000 and 0 <= current <= total:
                return current / total
    return None


def infer_stage(source_id: str, started_at: str | None) -> tuple[str, float, str]:
    commands = process_lines()
    joined = "\n".join(commands)

    worker_job = active_worker_job(source_id)
    if worker_job:
        stage = str(worker_job.get("stage") or worker_job.get("status") or "processing").lower()
        raw = clamp(worker_job.get("progress"))
        base = STAGE_BASE.get(stage, 75)
        # Rendering/metadata/upload progress is often stage-local. Keep the
        # dashboard's overall percentage monotonic within the stage range.
        spans = {
            "generating_visuals": (76, 8),
            "rendering": (78, 10),
            "rendering_approved_clips": (80, 8),
            "quality_check": (88, 3),
            "metadata": (91, 3),
            "uploading": (95, 4),
        }
        if stage in spans:
            lo, span = spans[stage]
            progress = lo + span * (raw / 100.0)
        else:
            progress = max(base, raw)
        worker = str(worker_job.get("worker") or "compute-01")
        return stage, clamp(progress), worker

    hook_pattern = re.compile(rf"hook_ranker_v5\.py\s+{re.escape(source_id)}(?:\s|$)")
    qa_pattern = re.compile(rf"retention_qa_v4\.py\s+{re.escape(source_id)}(?:\s|$)")

    if hook_pattern.search(joined):
        ratio = progress_ratio_from_log(
            AUTOPILOT_LOGS / f"{source_id}-hook-v5.log",
            ("hook", "anchor", "candidate", "review"),
        )
        progress = 36 + (18 * ratio if ratio is not None else 9)
        return "hook_ranking", clamp(progress), "compute-01 + compute-03"

    if qa_pattern.search(joined):
        ratio = progress_ratio_from_log(
            AUTOPILOT_LOGS / f"{source_id}-retention-qa-v4.log",
            ("qa", "candidate", "review", "retention"),
        )
        progress = 56 + (18 * ratio if ratio is not None else 9)
        return "retention_qa", clamp(progress), "compute-01 + compute-03"

    if not transcript_exists(source_id):
        return "transcribing", 20, "compute-01"
    if not rank_exists(source_id):
        return "hook_ranking", 36, "compute-01 + compute-03"
    if not qa_exists(source_id):
        return "retention_qa", 56, "compute-01 + compute-03"

    # QA has completed and the autopilot still owns the source. The next
    # productive stage is render preparation / worker handoff.
    return "rendering_approved_clips", 78, "compute-01"


def post_operational_heartbeat(job: dict | None) -> None:
    healthy = worker_healthy()
    if job:
        payload = {
            "name": "compute-01",
            "status": "online" if healthy else "degraded",
            "current_job": job["id"],
            "stage": job["stage"],
            "progress": job["progress"],
        }
    else:
        payload = {
            "name": "compute-01",
            "status": "online" if healthy else "degraded",
            "current_job": None,
            "stage": "Idle" if healthy else "Worker API unavailable",
            "progress": 0,
        }
    http_json(HEARTBEAT_URL, payload)


def dashboard_current_job() -> dict | None:
    data = http_json(DASHBOARD_URL)
    if not data:
        return None
    job = data.get("current_job")
    return job if isinstance(job, dict) else None


def finalize_stale_reporter_job(conn: sqlite3.Connection, active_source: str | None) -> None:
    current = dashboard_current_job()
    if not current:
        return
    job_id = str(current.get("id") or "")
    if not job_id.startswith("source:"):
        return
    source_id = job_id.split(":", 1)[1]
    if active_source and source_id == active_source:
        return
    row = conn.execute(
        "SELECT status, finished_at, updated_at FROM osho_autopilot_state WHERE source_id = ? LIMIT 1",
        (source_id,),
    ).fetchone()
    if row is None:
        return
    status = str(row["status"] or "").lower()
    if status not in TERMINAL:
        return
    progress = 100 if status in {"published", "uploaded", "skipped", "done", "complete", "completed"} else clamp(current.get("progress"))
    http_json(
        JOB_URL,
        {
            "id": job_id,
            "status": status,
            "stage": status,
            "title": current.get("title"),
            "progress": progress,
            "worker": current.get("worker"),
            "created_at": current.get("created_at"),
            "updated_at": row["finished_at"] or row["updated_at"] or now_iso(),
            "error": None,
        },
    )


def one_iteration() -> None:
    if not CATALOG_DB.exists():
        post_operational_heartbeat(None)
        return

    conn, active, source = read_catalog()
    try:
        active_source = str(active["source_id"]) if active is not None else None
        finalize_stale_reporter_job(conn, active_source)

        if active is None:
            post_operational_heartbeat(None)
            return

        source_id = str(active["source_id"])
        title = str(source["title"] if source is not None and source["title"] else f"Source {source_id}")

        if autopilot_active():
            stage, progress, worker = infer_stage(source_id, active["started_at"])
        else:
            stage, progress, worker = "paused", 0, "compute-01"

        job = {
            "id": f"source:{source_id}",
            "status": "processing",
            "stage": stage,
            "title": title,
            "progress": round(clamp(progress), 1),
            "worker": worker,
            "created_at": active["started_at"],
            "updated_at": now_iso(),
            "error": None,
        }
        http_json(JOB_URL, job)
        post_operational_heartbeat(job)
    finally:
        conn.close()


def main() -> None:
    print(f"Project Osho progress reporter {VERSION} starting", flush=True)
    while True:
        try:
            one_iteration()
        except Exception as exc:
            print(f"progress reporter error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(max(3.0, INTERVAL))


if __name__ == "__main__":
    main()
