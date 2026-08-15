#!/usr/bin/env python3
import csv
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

TELEMETRY_VERSION = "1.2.0"
DASHBOARD_URL = os.environ.get(
    "OSHO_DASHBOARD_URL",
    "http://192.168.0.88:8787/api/worker/heartbeat",
)
STATE_URL = os.environ.get(
    "OSHO_STATE_URL",
    "http://192.168.0.88:8787/api/state/reconcile",
)
INTERVAL = float(os.environ.get("OSHO_HEARTBEAT_INTERVAL", "10"))
WORKER_PORT = int(os.environ.get("OSHO_WORKER_PORT", "8800"))
WORKER_HEALTH_URL = os.environ.get(
    "OSHO_WORKER_HEALTH_URL",
    f"http://127.0.0.1:{WORKER_PORT}/health",
)
CATALOG_DB = Path(
    os.environ.get(
        "OSHO_CATALOG_DB",
        "/srv/osho/library/catalog/catalog.sqlite",
    )
)
RECEIPT_DIR = Path(
    os.environ.get(
        "OSHO_RECEIPT_DIR",
        "/srv/osho/youtube/receipts",
    )
)

ROLE_BY_HOST = {
    "compute-01": "Primary GPU worker / autopilot",
    "compute-03": "Secondary GPU worker",
}

# compute-01 already has a dedicated operational heartbeat sender that owns
# current_job/stage/progress. compute-03 does not, so this telemetry agent also
# emits the compatible basic heartbeat for compute-03 using Osho's catalog DB.
CATALOG_OPERATIONAL_HOSTS = {"compute-03"}

PROCESSING_STATES = {
    "downloading",
    "transcribing",
    "analyzing",
    "candidate_extraction",
    "ranking",
    "hook_ranking",
    "retention_qa",
    "generating_visuals",
    "rendering",
    "rendering_approved_clips",
    "quality_check",
    "metadata",
    "uploading",
    "retrying",
    "processing",
    "running",
    "remote_qa",
}


def run(*args, timeout=4):
    try:
        return subprocess.check_output(
            args,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).strip()
    except Exception:
        return ""


def preferred_ip():
    values = run("hostname", "-I").split()
    for value in values:
        if value.startswith("192.168.0."):
            return value
    return values[0] if values else None


def worker_health():
    try:
        req = urllib.request.Request(
            WORKER_HEALTH_URL,
            headers={"User-Agent": f"Project-Osho-Telemetry/{TELEMETRY_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def gpu_stats():
    output = run(
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    )
    if not output:
        return {}

    try:
        row = next(csv.reader(io.StringIO(output)))
        if len(row) < 6:
            return {}
        return {
            "gpu_name": row[0].strip(),
            "gpu_utilization": float(row[1].strip()),
            "vram_used_mb": float(row[2].strip()),
            "vram_total_mb": float(row[3].strip()),
            "gpu_temperature_c": float(row[4].strip()),
            "gpu_power_w": float(row[5].strip()),
        }
    except Exception:
        return {}


def ollama_model():
    output = run("ollama", "ps")
    if not output:
        return None
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    return lines[1].split()[0]


def load_1m():
    try:
        return round(os.getloadavg()[0], 2)
    except Exception:
        return None


def disk_free_gb():
    for path in ("/srv", "/"):
        try:
            if os.path.exists(path):
                return round(shutil.disk_usage(path).free / (1024 ** 3), 1)
        except Exception:
            pass
    return None


def autopilot_status(hostname):
    if hostname != "compute-01":
        return None
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "osho-autopilot.service"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=4,
            check=False,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def active_catalog_assignment(hostname):
    if hostname not in CATALOG_OPERATIONAL_HOSTS or not CATALOG_DB.exists():
        return None

    try:
        conn = sqlite3.connect(
            f"file:{CATALOG_DB}?mode=ro",
            uri=True,
            timeout=2,
        )
        conn.row_factory = sqlite3.Row

        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(discourses)").fetchall()
        }
        required = {
            "source_id",
            "processing_status",
            "processing_phase",
            "processing_worker",
            "processing_job_id",
        }
        if not required.issubset(columns):
            conn.close()
            return None

        order_by = (
            "COALESCE(processing_started_at, '') DESC, source_id"
            if "processing_started_at" in columns
            else "source_id"
        )

        row = conn.execute(
            f"""
            SELECT
                source_id,
                processing_phase,
                processing_job_id
            FROM discourses
            WHERE processing_status = 'processing'
              AND processing_worker = ?
            ORDER BY {order_by}
            LIMIT 1
            """,
            (hostname,),
        ).fetchone()
        conn.close()

        if row is None:
            return None

        source_id = row["source_id"]
        return {
            "current_job": row["processing_job_id"] or f"source:{source_id}",
            "stage": row["processing_phase"] or "processing",
            "progress": 0,
        }
    except (sqlite3.Error, OSError):
        return None


def telemetry_payload(hostname, health):
    data = {
        "name": hostname,
        "status": "online" if health else "degraded",
        "role": ROLE_BY_HOST.get(hostname, "Osho worker"),
        "ip": preferred_ip(),
        "worker_port": WORKER_PORT,
        "ollama_model": ollama_model(),
        "load_1m": load_1m(),
        "disk_free_gb": disk_free_gb(),
        "autopilot_status": autopilot_status(hostname),
        "telemetry_version": TELEMETRY_VERSION,
    }
    data.update(gpu_stats())

    if health:
        data.update({
            "service": health.get("service"),
            "service_version": health.get("version"),
            "whisper_model": health.get("whisper_model"),
            "device": health.get("device"),
            "compute_type": health.get("compute_type"),
        })

    return data


def operational_payload(hostname, health):
    assignment = active_catalog_assignment(hostname)
    if assignment:
        return {
            "name": hostname,
            "status": "online" if health else "degraded",
            **assignment,
        }

    return {
        "name": hostname,
        "status": "online" if health else "degraded",
        "current_job": None,
        "stage": "Idle" if health else "Worker API unavailable",
        "progress": 0,
    }


def autopilot_status_counts():
    if not CATALOG_DB.exists():
        return None

    try:
        conn = sqlite3.connect(
            f"file:{CATALOG_DB}?mode=ro",
            uri=True,
            timeout=2,
        )
        rows = conn.execute(
            """
            SELECT lower(trim(status)) AS status, COUNT(*)
            FROM osho_autopilot_state
            WHERE status IS NOT NULL AND trim(status) <> ''
            GROUP BY lower(trim(status))
            """
        ).fetchall()
        conn.close()
        return {str(status): int(count) for status, count in rows}
    except (sqlite3.Error, OSError):
        return None


def receipt_records():
    if not RECEIPT_DIR.exists():
        return []

    records = []
    for path in RECEIPT_DIR.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue

            video_id = data.get("video_id")
            youtube_url = data.get("youtube_url")
            if not youtube_url and video_id:
                youtube_url = f"https://www.youtube.com/watch?v={video_id}"

            timestamp = (
                data.get("uploaded_at")
                or data.get("published_at")
                or data.get("created_at")
            )
            if not timestamp:
                timestamp = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(path.stat().st_mtime),
                )

            identity = (
                str(video_id)
                if video_id
                else str(data.get("job_id") or data.get("source_id") or path)
            )

            records.append({
                "identity": identity,
                "timestamp": str(timestamp),
                "job_id": data.get("job_id"),
                "source_id": data.get("source_id"),
                "video_id": video_id,
                "youtube_url": youtube_url,
                "title": data.get("title"),
            })
        except (OSError, ValueError, TypeError):
            continue

    deduped = {}
    for record in records:
        prior = deduped.get(record["identity"])
        if prior is None or record["timestamp"] > prior["timestamp"]:
            deduped[record["identity"]] = record

    return list(deduped.values())


def state_reconcile_payload(hostname):
    if hostname != "compute-01":
        return None

    status_counts = autopilot_status_counts()
    if status_counts is None:
        return None

    receipts = receipt_records()
    upload_state_keys = {"published", "uploaded"}.intersection(status_counts)
    uploaded_from_state = (
        sum(status_counts.get(status, 0) for status in upload_state_keys)
        if upload_state_keys
        else None
    )
    uploaded = len(receipts) if receipts else uploaded_from_state

    processing_keys = PROCESSING_STATES.intersection(status_counts)
    processing = (
        sum(status_counts.get(status, 0) for status in processing_keys)
        if processing_keys
        else None
    )

    ready_keys = {"ready_to_upload", "ready"}.intersection(status_counts)
    ready = (
        sum(status_counts.get(status, 0) for status in ready_keys)
        if ready_keys
        else None
    )

    queued_keys = {"queued", "pending"}.intersection(status_counts)
    queued = (
        sum(status_counts.get(status, 0) for status in queued_keys)
        if queued_keys
        else None
    )

    skipped = status_counts.get("skipped", 0)

    failed_keys = {"failed", "error"}.intersection(status_counts)
    failed = (
        sum(status_counts.get(status, 0) for status in failed_keys)
        if failed_keys
        else None
    )

    latest_upload = None
    if receipts:
        latest = max(receipts, key=lambda item: item["timestamp"])
        latest_upload = {
            "id": latest.get("job_id") or latest.get("video_id") or latest.get("source_id"),
            "status": "published",
            "stage": "published",
            "title": latest.get("title") or (
                f"Source {latest.get('source_id')}" if latest.get("source_id") else "YouTube upload"
            ),
            "progress": 100,
            "worker": "compute-01",
            "created_at": None,
            "updated_at": latest.get("timestamp"),
            "published_at": latest.get("timestamp"),
            "youtube_url": latest.get("youtube_url"),
            "error": None,
        }

    return {
        "source": hostname,
        "uploaded": uploaded,
        "processing": processing,
        "ready": ready,
        "queued": queued,
        "skipped": skipped,
        "failed": failed,
        "latest_upload": latest_upload,
        "status_counts": status_counts,
        "notes": "Read-only reconciliation from osho_autopilot_state and durable YouTube receipts.",
    }


def post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"Project-Osho-Telemetry/{TELEMETRY_VERSION}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        response.read()


def main():
    hostname = socket.gethostname().split(".")[0]

    while True:
        try:
            health = worker_health()
            post(DASHBOARD_URL, telemetry_payload(hostname, health))

            if hostname in CATALOG_OPERATIONAL_HOSTS:
                post(DASHBOARD_URL, operational_payload(hostname, health))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"heartbeat failed: {exc}", flush=True)
        except Exception as exc:
            print(f"heartbeat unexpected error: {exc}", flush=True)

        if hostname == "compute-01":
            try:
                snapshot = state_reconcile_payload(hostname)
                if snapshot:
                    post(STATE_URL, snapshot)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                print(f"state reconciliation failed: {exc}", flush=True)
            except Exception as exc:
                print(f"state reconciliation unexpected error: {exc}", flush=True)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
