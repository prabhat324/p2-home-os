from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "osho.db"
DASHBOARD_VERSION = "0.5.3"

app = FastAPI(
    title="Project Osho Dashboard API",
    version=DASHBOARD_VERSION,
)


class WorkerHeartbeat(BaseModel):
    name: str
    status: str = "online"
    role: str | None = None
    ip: str | None = None
    current_job: str | None = None
    stage: str | None = None
    progress: float = 0
    service: str | None = None
    service_version: str | None = None
    worker_port: int | None = None
    gpu_name: str | None = None
    gpu_utilization: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    gpu_temperature_c: float | None = None
    gpu_power_w: float | None = None
    ollama_model: str | None = None
    whisper_model: str | None = None
    device: str | None = None
    compute_type: str | None = None
    load_1m: float | None = None
    disk_free_gb: float | None = None
    autopilot_status: str | None = None
    telemetry_version: str | None = None
    notes: str | None = None


class JobUpdate(BaseModel):
    id: str
    status: str = "queued"
    stage: str | None = None
    title: str | None = None
    progress: float = 0
    worker: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    published_at: str | None = None
    youtube_url: str | None = None
    error: str | None = None


class StateSnapshot(BaseModel):
    source: str = "compute-01"
    uploaded: int | None = None
    processing: int | None = None
    ready: int | None = None
    queued: int | None = None
    skipped: int | None = None
    failed: int | None = None
    latest_upload: dict | None = None
    status_counts: dict[str, int] | None = None
    notes: str | None = None


WORKER_COLUMNS = {
    "role": "TEXT",
    "ip": "TEXT",
    "service": "TEXT",
    "service_version": "TEXT",
    "worker_port": "INTEGER",
    "gpu_name": "TEXT",
    "gpu_utilization": "REAL",
    "vram_used_mb": "REAL",
    "vram_total_mb": "REAL",
    "gpu_temperature_c": "REAL",
    "gpu_power_w": "REAL",
    "ollama_model": "TEXT",
    "whisper_model": "TEXT",
    "device": "TEXT",
    "compute_type": "TEXT",
    "load_1m": "REAL",
    "disk_free_gb": "REAL",
    "autopilot_status": "TEXT",
    "health_status": "TEXT",
    "telemetry_version": "TEXT",
    "telemetry_last_seen": "TEXT",
    "notes": "TEXT",
}

JOB_COLUMNS = {
    "worker": "TEXT",
}


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]):
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT,
            title TEXT,
            progress REAL NOT NULL DEFAULT 0,
            worker TEXT,
            created_at TEXT,
            updated_at TEXT,
            published_at TEXT,
            youtube_url TEXT,
            error TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workers (
            name TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'unknown',
            role TEXT,
            ip TEXT,
            current_job TEXT,
            stage TEXT,
            progress REAL NOT NULL DEFAULT 0,
            service TEXT,
            service_version TEXT,
            worker_port INTEGER,
            gpu_name TEXT,
            gpu_utilization REAL,
            vram_used_mb REAL,
            vram_total_mb REAL,
            gpu_temperature_c REAL,
            gpu_power_w REAL,
            ollama_model TEXT,
            whisper_model TEXT,
            device TEXT,
            compute_type TEXT,
            load_1m REAL,
            disk_free_gb REAL,
            autopilot_status TEXT,
            health_status TEXT,
            telemetry_version TEXT,
            telemetry_last_seen TEXT,
            notes TEXT,
            last_seen TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_snapshots (
            source TEXT PRIMARY KEY,
            uploaded INTEGER,
            processing INTEGER,
            ready INTEGER,
            queued INTEGER,
            skipped INTEGER,
            failed INTEGER,
            latest_upload_json TEXT,
            status_counts_json TEXT,
            notes TEXT,
            received_at TEXT NOT NULL
        )
        """
    )

    ensure_columns(conn, "jobs", JOB_COLUMNS)
    ensure_columns(conn, "workers", WORKER_COLUMNS)

    conn.commit()
    return conn


@app.on_event("startup")
def startup():
    conn = db()
    conn.close()


@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Project Osho Dashboard",
        "version": DASHBOARD_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/worker/heartbeat")
def worker_heartbeat(heartbeat: WorkerHeartbeat):
    now = datetime.now(timezone.utc).isoformat()
    conn = db()

    if heartbeat.telemetry_version:
        # Rich telemetry is deliberately separate from the legacy operational
        # heartbeat. It must never erase current_job/stage/progress maintained
        # by the existing operational heartbeat sender.
        conn.execute(
            """
            INSERT INTO workers (
                name, status, role, ip,
                service, service_version, worker_port,
                gpu_name, gpu_utilization, vram_used_mb, vram_total_mb,
                gpu_temperature_c, gpu_power_w, ollama_model,
                whisper_model, device, compute_type,
                load_1m, disk_free_gb, autopilot_status,
                health_status, telemetry_version, telemetry_last_seen, notes
            )
            VALUES (
                :name, :status, :role, :ip,
                :service, :service_version, :worker_port,
                :gpu_name, :gpu_utilization, :vram_used_mb, :vram_total_mb,
                :gpu_temperature_c, :gpu_power_w, :ollama_model,
                :whisper_model, :device, :compute_type,
                :load_1m, :disk_free_gb, :autopilot_status,
                :health_status, :telemetry_version, :telemetry_last_seen, :notes
            )
            ON CONFLICT(name) DO UPDATE SET
                role = COALESCE(excluded.role, workers.role),
                ip = COALESCE(excluded.ip, workers.ip),
                service = COALESCE(excluded.service, workers.service),
                service_version = COALESCE(excluded.service_version, workers.service_version),
                worker_port = COALESCE(excluded.worker_port, workers.worker_port),
                gpu_name = COALESCE(excluded.gpu_name, workers.gpu_name),
                gpu_utilization = excluded.gpu_utilization,
                vram_used_mb = excluded.vram_used_mb,
                vram_total_mb = COALESCE(excluded.vram_total_mb, workers.vram_total_mb),
                gpu_temperature_c = excluded.gpu_temperature_c,
                gpu_power_w = excluded.gpu_power_w,
                ollama_model = excluded.ollama_model,
                whisper_model = COALESCE(excluded.whisper_model, workers.whisper_model),
                device = COALESCE(excluded.device, workers.device),
                compute_type = COALESCE(excluded.compute_type, workers.compute_type),
                load_1m = excluded.load_1m,
                disk_free_gb = excluded.disk_free_gb,
                autopilot_status = excluded.autopilot_status,
                health_status = excluded.health_status,
                telemetry_version = excluded.telemetry_version,
                telemetry_last_seen = excluded.telemetry_last_seen,
                notes = excluded.notes
            """,
            {
                "name": heartbeat.name,
                "status": heartbeat.status,
                "role": heartbeat.role,
                "ip": heartbeat.ip,
                "service": heartbeat.service,
                "service_version": heartbeat.service_version,
                "worker_port": heartbeat.worker_port,
                "gpu_name": heartbeat.gpu_name,
                "gpu_utilization": heartbeat.gpu_utilization,
                "vram_used_mb": heartbeat.vram_used_mb,
                "vram_total_mb": heartbeat.vram_total_mb,
                "gpu_temperature_c": heartbeat.gpu_temperature_c,
                "gpu_power_w": heartbeat.gpu_power_w,
                "ollama_model": heartbeat.ollama_model,
                "whisper_model": heartbeat.whisper_model,
                "device": heartbeat.device,
                "compute_type": heartbeat.compute_type,
                "load_1m": heartbeat.load_1m,
                "disk_free_gb": heartbeat.disk_free_gb,
                "autopilot_status": heartbeat.autopilot_status,
                "health_status": heartbeat.status,
                "telemetry_version": heartbeat.telemetry_version,
                "telemetry_last_seen": now,
                "notes": heartbeat.notes,
            },
        )
    else:
        # Backward-compatible path for the existing operational heartbeat.
        progress = max(0, min(100, float(heartbeat.progress)))
        conn.execute(
            """
            INSERT INTO workers (
                name, status, current_job, stage, progress, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                status = excluded.status,
                current_job = excluded.current_job,
                stage = excluded.stage,
                progress = excluded.progress,
                last_seen = excluded.last_seen
            """,
            (
                heartbeat.name,
                heartbeat.status,
                heartbeat.current_job,
                heartbeat.stage,
                progress,
                now,
            ),
        )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "worker": heartbeat.name,
        "heartbeat_type": "telemetry" if heartbeat.telemetry_version else "operational",
        "received_at": now,
    }


@app.post("/api/jobs/update")
def update_job(job: JobUpdate):
    now = datetime.now(timezone.utc).isoformat()
    progress = max(0, min(100, float(job.progress)))
    created_at = job.created_at or now
    updated_at = job.updated_at or now

    conn = db()
    conn.execute(
        """
        INSERT INTO jobs (
            id, status, stage, title, progress, worker,
            created_at, updated_at, published_at, youtube_url, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            stage = excluded.stage,
            title = COALESCE(excluded.title, jobs.title),
            progress = excluded.progress,
            worker = COALESCE(excluded.worker, jobs.worker),
            updated_at = excluded.updated_at,
            published_at = COALESCE(excluded.published_at, jobs.published_at),
            youtube_url = COALESCE(excluded.youtube_url, jobs.youtube_url),
            error = excluded.error
        """,
        (
            job.id,
            job.status,
            job.stage,
            job.title,
            progress,
            job.worker,
            created_at,
            updated_at,
            job.published_at,
            job.youtube_url,
            job.error,
        ),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "job": job.id, "status": job.status}


def clamp_count(value: int | None):
    if value is None:
        return None
    return max(0, int(value))


@app.post("/api/state/reconcile")
def reconcile_state(snapshot: StateSnapshot):
    now = datetime.now(timezone.utc).isoformat()
    conn = db()
    conn.execute(
        """
        INSERT INTO state_snapshots (
            source, uploaded, processing, ready, queued, skipped, failed,
            latest_upload_json, status_counts_json, notes, received_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            uploaded = excluded.uploaded,
            processing = excluded.processing,
            ready = excluded.ready,
            queued = excluded.queued,
            skipped = excluded.skipped,
            failed = excluded.failed,
            latest_upload_json = excluded.latest_upload_json,
            status_counts_json = excluded.status_counts_json,
            notes = excluded.notes,
            received_at = excluded.received_at
        """,
        (
            snapshot.source,
            clamp_count(snapshot.uploaded),
            clamp_count(snapshot.processing),
            clamp_count(snapshot.ready),
            clamp_count(snapshot.queued),
            clamp_count(snapshot.skipped),
            clamp_count(snapshot.failed),
            json.dumps(snapshot.latest_upload) if snapshot.latest_upload else None,
            json.dumps(snapshot.status_counts or {}, sort_keys=True),
            snapshot.notes,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "source": snapshot.source,
        "received_at": now,
    }


def timestamp_age(now: datetime, value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return max(0.0, (now - parsed).total_seconds())
    except Exception:
        return None


def decode_json(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


@app.get("/api/dashboard")
def dashboard_data():
    conn = db()
    now = datetime.now(timezone.utc)

    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
    ).fetchall()
    counts = {row["status"]: row["count"] for row in rows}

    uploaded = counts.get("published", 0) + counts.get("uploaded", 0)
    ready = counts.get("ready_to_upload", 0)
    queued = counts.get("queued", 0)
    failed = counts.get("failed", 0)
    skipped = counts.get("skipped", 0)

    processing_statuses = [
        "downloading", "transcribing", "analyzing", "candidate_extraction",
        "ranking", "hook_ranking", "retention_qa", "generating_visuals",
        "rendering", "rendering_approved_clips", "quality_check", "metadata",
        "uploading", "retrying", "processing", "running", "remote_qa",
    ]
    processing = sum(counts.get(status, 0) for status in processing_statuses)

    current = conn.execute(
        """
        SELECT * FROM jobs
        WHERE status NOT IN (
            'published', 'uploaded', 'failed', 'skipped',
            'ready_to_upload', 'queued'
        )
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).fetchone()

    latest = conn.execute(
        """
        SELECT * FROM jobs
        WHERE status IN ('published', 'uploaded')
        ORDER BY COALESCE(published_at, updated_at) DESC
        LIMIT 1
        """
    ).fetchone()

    state_row = conn.execute(
        """
        SELECT * FROM state_snapshots
        ORDER BY received_at DESC
        LIMIT 1
        """
    ).fetchone()

    reconciliation = None
    reconciled_latest = None
    if state_row:
        state = dict(state_row)
        state_age = timestamp_age(now, state.get("received_at"))
        fresh = state_age is not None and state_age <= 90

        reconciliation = {
            "source": state.get("source"),
            "received_at": state.get("received_at"),
            "age_seconds": round(state_age, 1) if state_age is not None else None,
            "fresh": fresh,
            "status_counts": decode_json(state.get("status_counts_json")) or {},
            "notes": state.get("notes"),
        }

        if fresh:
            for key in ("uploaded", "processing", "ready", "queued", "skipped", "failed"):
                value = state.get(key)
                if value is None:
                    continue
                if key == "uploaded":
                    uploaded = value
                elif key == "processing":
                    processing = value
                elif key == "ready":
                    ready = value
                elif key == "queued":
                    queued = value
                elif key == "skipped":
                    skipped = value
                elif key == "failed":
                    failed = value

            reconciled_latest = decode_json(state.get("latest_upload_json"))

    worker_rows = conn.execute(
        "SELECT * FROM workers ORDER BY name"
    ).fetchall()

    workers = []

    for row in worker_rows:
        worker = dict(row)
        operational_age = timestamp_age(now, worker.get("last_seen"))
        telemetry_age = timestamp_age(now, worker.get("telemetry_last_seen"))
        available_ages = [age for age in (operational_age, telemetry_age) if age is not None]
        age = min(available_ages) if available_ages else None

        worker["operational_age_seconds"] = (
            round(operational_age, 1) if operational_age is not None else None
        )
        worker["telemetry_age_seconds"] = (
            round(telemetry_age, 1) if telemetry_age is not None else None
        )
        worker["age_seconds"] = round(age, 1) if age is not None else None

        if telemetry_age is None:
            worker["telemetry_state"] = "missing"
        elif telemetry_age > 90:
            worker["telemetry_state"] = "offline"
        elif telemetry_age > 30:
            worker["telemetry_state"] = "stale"
        else:
            worker["telemetry_state"] = "fresh"

        reported = (worker.get("status") or "unknown").lower()
        health_status = (worker.get("health_status") or "").lower()

        if age is None or age > 90:
            worker["status"] = "offline"
        elif telemetry_age is not None and telemetry_age <= 30 and health_status == "degraded":
            worker["status"] = "degraded"
        elif age > 30:
            worker["status"] = "stale"
        elif reported in ("drain", "maintenance"):
            worker["status"] = reported
        else:
            worker["status"] = "online"

        workers.append(worker)

    conn.close()

    return {
        "timestamp": now.isoformat(),
        "dashboard_version": DASHBOARD_VERSION,
        "mode": "Zero-Touch V5",
        "summary": {
            "uploaded": uploaded,
            "processing": processing,
            "ready": ready,
            "queued": queued,
            "skipped": skipped,
            "failed": failed,
        },
        "current_job": dict(current) if current else None,
        "latest_upload": reconciled_latest or (dict(latest) if latest else None),
        "state_reconciliation": reconciliation,
        "workers": workers,
        "control_plane": {
            "name": "compute-02",
            "status": "online",
            "role": "Osho dashboard / controller",
            "ip": "192.168.0.88",
            "dashboard_port": 8787,
            "piper_port": 10200,
        },
    }
