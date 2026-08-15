from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "osho.db"

app = FastAPI(
    title="Project Osho Dashboard API",
    version="0.4.0",
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
    "telemetry_version": "TEXT",
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
            telemetry_version TEXT,
            notes TEXT,
            last_seen TEXT
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
        "version": "0.4.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/worker/heartbeat")
def worker_heartbeat(heartbeat: WorkerHeartbeat):
    now = datetime.now(timezone.utc).isoformat()
    progress = max(0, min(100, float(heartbeat.progress)))

    conn = db()
    conn.execute(
        """
        INSERT INTO workers (
            name, status, role, ip, current_job, stage, progress,
            service, service_version, worker_port,
            gpu_name, gpu_utilization, vram_used_mb, vram_total_mb,
            gpu_temperature_c, gpu_power_w, ollama_model,
            whisper_model, device, compute_type,
            load_1m, disk_free_gb, autopilot_status, telemetry_version,
            notes, last_seen
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(name) DO UPDATE SET
            status = excluded.status,
            role = COALESCE(excluded.role, workers.role),
            ip = COALESCE(excluded.ip, workers.ip),
            current_job = excluded.current_job,
            stage = excluded.stage,
            progress = excluded.progress,
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
            telemetry_version = COALESCE(excluded.telemetry_version, workers.telemetry_version),
            notes = excluded.notes,
            last_seen = excluded.last_seen
        """,
        (
            heartbeat.name,
            heartbeat.status,
            heartbeat.role,
            heartbeat.ip,
            heartbeat.current_job,
            heartbeat.stage,
            progress,
            heartbeat.service,
            heartbeat.service_version,
            heartbeat.worker_port,
            heartbeat.gpu_name,
            heartbeat.gpu_utilization,
            heartbeat.vram_used_mb,
            heartbeat.vram_total_mb,
            heartbeat.gpu_temperature_c,
            heartbeat.gpu_power_w,
            heartbeat.ollama_model,
            heartbeat.whisper_model,
            heartbeat.device,
            heartbeat.compute_type,
            heartbeat.load_1m,
            heartbeat.disk_free_gb,
            heartbeat.autopilot_status,
            heartbeat.telemetry_version,
            heartbeat.notes,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "worker": heartbeat.name,
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


@app.get("/api/dashboard")
def dashboard_data():
    conn = db()

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
        "uploading", "retrying", "processing", "running",
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

    worker_rows = conn.execute(
        "SELECT * FROM workers ORDER BY name"
    ).fetchall()

    workers = []
    now = datetime.now(timezone.utc)

    for row in worker_rows:
        worker = dict(row)
        try:
            last_seen = datetime.fromisoformat(worker["last_seen"])
            age = (now - last_seen).total_seconds()
            worker["age_seconds"] = round(age, 1)

            reported = worker.get("status") or "unknown"
            if age > 90:
                worker["status"] = "offline"
            elif age > 30:
                worker["status"] = "stale"
            elif reported in ("ok", "healthy"):
                worker["status"] = "online"
        except Exception:
            worker["status"] = "unknown"
            worker["age_seconds"] = None

        workers.append(worker)

    conn.close()

    return {
        "timestamp": now.isoformat(),
        "dashboard_version": "0.4.0",
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
        "latest_upload": dict(latest) if latest else None,
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
