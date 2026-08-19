from datetime import datetime, timedelta, timezone
import json
import urllib.error
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

import main as base


app = FastAPI(
    title="Project Osho Dashboard API",
    version=base.DASHBOARD_VERSION,
)


COMMAND_CENTER_ROUTES = (
    "/",
    "/media",
    "/monitoring",
    "/network",
    "/storage",
    "/services",
    "/osho",
    "/alerts",
)


GLANCES_NODES = {
    "core-01": "192.168.0.203",
    "compute-01": "192.168.0.31",
    "compute-02": "192.168.0.88",
    "compute-03": "192.168.0.158",
    "compute-04": "192.168.0.176",
}
GLANCES_PLUGINS = {"cpu", "mem", "fs", "uptime", "sensors"}


@app.get("/api/glances/{node}/api/4/{plugin}")
def glances_proxy(node: str, plugin: str):
    host = GLANCES_NODES.get(node)
    if host is None or plugin not in GLANCES_PLUGINS:
        raise HTTPException(status_code=404, detail="Unknown node or plugin")
    try:
        req = urllib.request.Request(
            f"http://{host}:61208/api/4/{plugin}",
            headers={"User-Agent": "P2-Dashboard-Glances-Proxy/1.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Glances unavailable for {node}") from exc


OSHO_PROGRESS_STYLE = """
<style id="osho-progress-style">
.osho-live-job{margin-top:14px}
.osho-job-title{font-size:18px;font-weight:800;line-height:1.3}
.osho-job-meta{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}
.osho-job-meta>div{border:1px solid var(--line);background:#0c1929;border-radius:9px;padding:9px}
.osho-job-meta span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.06em}
.osho-job-meta b{display:block;margin-top:4px;font-size:12px;overflow-wrap:anywhere}
.osho-progress-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:17px}
.osho-progress-head span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.osho-progress-head strong{font-size:22px}
.osho-progress-track{height:13px;background:#24344b;border:1px solid #31445e;border-radius:999px;overflow:hidden;margin-top:8px}
.osho-progress-track i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--purple),var(--blue));border-radius:999px;transition:width .45s ease}
.osho-progress-foot{display:flex;justify-content:space-between;gap:12px;margin-top:8px;color:var(--muted);font-size:10px}
@media(max-width:820px){.osho-job-meta{grid-template-columns:repeat(2,1fr)}}
</style>
"""


OSHO_PROGRESS_PANEL = """
<section class="section osho-live-job" id="oshoLiveProcessing">
  <div class="section-head">
    <h2>Live Processing</h2>
    <span class="badge" id="liveJobBadge">Checking</span>
  </div>
  <div class="empty-note" id="liveJobEmpty">Checking the active Osho job…</div>
  <div id="liveJobBody" style="display:none">
    <div class="osho-job-title" id="liveJobTitle">—</div>
    <div class="osho-job-meta">
      <div><span>Source / Job</span><b id="liveJobId">—</b></div>
      <div><span>Current stage</span><b id="liveJobStage">—</b></div>
      <div><span>Active worker</span><b id="liveJobWorker">—</b></div>
      <div><span>Telemetry updated</span><b id="liveJobUpdated">—</b></div>
    </div>
    <div class="osho-progress-head"><span>Job progress</span><strong id="liveJobPct">0%</strong></div>
    <div class="osho-progress-track"><i id="liveJobBar"></i></div>
    <div class="osho-progress-foot"><span id="liveJobDetail">Waiting for stage telemetry</span><span>refreshes every 3s</span></div>
  </div>
</section>
<script id="osho-progress-script">
(() => {
  const $ = id => document.getElementById(id);
  const clamp = n => Math.max(0, Math.min(100, Number(n) || 0));
  const cleanStage = value => String(value || 'Processing')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
  const relative = value => {
    if (!value) return '—';
    const t = new Date(value).getTime();
    if (!Number.isFinite(t)) return '—';
    const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    return `${hr}h ${min % 60}m ago`;
  };
  const activeWorkers = (workers, job) => {
    const jid = String(job?.id || job?.job_id || '');
    const names = (Array.isArray(workers) ? workers : []).filter(w => {
      const current = String(w?.current_job || '');
      const stage = String(w?.stage || '').toLowerCase();
      return (jid && current && (current === jid || current.includes(jid) || jid.includes(current))) ||
        (stage && !['idle', 'none', 'offline'].includes(stage));
    }).map(w => w.name).filter(Boolean);
    return [...new Set(names)].join(' + ') || 'autopilot / compute';
  };
  async function refreshLiveProcessing(){
    const empty = $('liveJobEmpty'), body = $('liveJobBody'), badge = $('liveJobBadge');
    if (!empty || !body || !badge) return;
    try {
      const r = await fetch('/api/dashboard', {cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (d.project_status === 'on_hold') {
        body.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = 'Project Osho is on hold. No processing workload is running.';
        badge.textContent = 'On Hold';
        badge.className = 'badge warn';
        return;
      }
      const job = d.current_job;
      const processing = Number(d.summary?.processing || 0);
      if (!job) {
        body.style.display = 'none';
        empty.style.display = 'block';
        if (processing > 0) {
          empty.textContent = `${processing} pipeline item${processing === 1 ? '' : 's'} processing; waiting for detailed job telemetry.`;
          badge.textContent = 'Processing';
          badge.className = 'badge warn';
        } else {
          empty.textContent = 'No active processing job right now.';
          badge.textContent = 'Idle';
          badge.className = 'badge';
        }
        return;
      }
      empty.style.display = 'none';
      body.style.display = 'block';
      const pct = clamp(job.progress);
      const stage = cleanStage(job.stage || job.status);
      const id = job.source_id || job.id || job.job_id || '—';
      $('liveJobTitle').textContent = job.title || job.name || `Osho ${id}`;
      $('liveJobId').textContent = id;
      $('liveJobStage').textContent = stage;
      $('liveJobWorker').textContent = job.worker || activeWorkers(d.workers, job);
      $('liveJobUpdated').textContent = relative(job.updated_at || job.created_at);
      $('liveJobPct').textContent = `${Math.round(pct)}%`;
      $('liveJobBar').style.width = `${pct}%`;
      $('liveJobDetail').textContent = `${stage} · ${Math.round(pct)}% complete`;
      badge.textContent = 'Processing';
      badge.className = 'badge';
    } catch (e) {
      body.style.display = 'none';
      empty.style.display = 'block';
      empty.textContent = `Live processing telemetry unavailable: ${e.message}`;
      badge.textContent = 'Offline';
      badge.className = 'badge bad';
    }
  }
  refreshLiveProcessing();
  setInterval(refreshLiveProcessing, 3000);
})();
</script>
"""


@app.get("/")
def dashboard_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/media")
def media_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/monitoring")
def monitoring_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/network")
def network_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/storage")
def storage_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/services")
def services_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/osho")
def osho_page():
    html = (base.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if 'id="osho-progress-style"' not in html:
        html = html.replace("</head>", OSHO_PROGRESS_STYLE + "\n</head>", 1)
    if 'id="oshoLiveProcessing"' not in html:
        html = html.replace("</main>", OSHO_PROGRESS_PANEL + "\n</main>", 1)
    return HTMLResponse(html)


@app.get("/alerts")
def alerts_page():
    return FileResponse(base.STATIC_DIR / "index.html")


@app.get("/youtube-analyst")
def youtube_analyst_page():
    return FileResponse(base.STATIC_DIR / "analytics.html")


@app.get("/analytics")
def analytics_page_alias():
    return FileResponse(base.STATIC_DIR / "analytics.html")


def _analytics_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payload TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS analytics_history_received_at "
        "ON analytics_history(received_at)"
    )
    conn.commit()


def _analytics_videos(payload):
    if not isinstance(payload, dict):
        return []
    videos = payload.get("videos")
    if not isinstance(videos, list):
        videos = payload.get("video_stats")
    return videos if isinstance(videos, list) else []


def _analytics_channel(payload):
    if not isinstance(payload, dict):
        return {}
    for key in ("channel", "channel_summary", "channel_stats"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _video_key(video):
    return str(video.get("video_id") or video.get("youtube_id") or video.get("reel_id") or "")


def _public_views(video):
    try:
        return max(0, int(float(video.get("public_views") or 0)))
    except Exception:
        return 0


def _uploaded_at(video):
    value = video.get("uploaded_at") or video.get("published_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _views_24h(conn, payload, now):
    videos = _analytics_videos(payload)
    channel = _analytics_channel(payload)
    tracked = len(videos)
    try:
        channel_count = int(channel.get("video_count"))
    except Exception:
        try:
            channel_count = int(payload.get("video_count"))
        except Exception:
            channel_count = None

    current = {
        _video_key(video): _public_views(video)
        for video in videos
        if _video_key(video)
    }
    current_total = sum(current.values())
    target = now - timedelta(hours=24)

    row = conn.execute(
        "SELECT received_at, payload FROM analytics_history "
        "WHERE received_at <= ? ORDER BY received_at DESC LIMIT 1",
        (target.isoformat(),),
    ).fetchone()

    window_complete = row is not None
    value = None
    window_hours = None

    if row is not None:
        try:
            baseline_payload = json.loads(row["payload"])
        except Exception:
            baseline_payload = {}
        baseline = {
            _video_key(video): _public_views(video)
            for video in _analytics_videos(baseline_payload)
            if _video_key(video)
        }
        value = sum(max(0, views - baseline.get(key, 0)) for key, views in current.items())
        try:
            baseline_at = datetime.fromisoformat(row["received_at"])
            if baseline_at.tzinfo is None:
                baseline_at = baseline_at.replace(tzinfo=timezone.utc)
            window_hours = round((now - baseline_at).total_seconds() / 3600, 2)
        except Exception:
            window_hours = 24.0
    else:
        uploads = [_uploaded_at(video) for video in videos]
        known_uploads = [stamp for stamp in uploads if stamp is not None]
        if videos and len(known_uploads) == len(videos) and min(known_uploads) >= target:
            value = current_total
            window_complete = True
            window_hours = 24.0

    coverage_complete = channel_count is None or tracked >= channel_count
    return {
        "value": value,
        "tracked_videos": tracked,
        "channel_videos": channel_count,
        "coverage_complete": coverage_complete,
        "window_complete": window_complete,
        "window_hours": window_hours,
    }


@app.post("/api/analytics/update")
async def analytics_update(request: Request):
    payload = await request.json()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    packed = json.dumps(payload, separators=(",", ":"))

    conn = base.db()
    _analytics_table(conn)
    conn.execute(
        """
        INSERT INTO analytics_state (id, payload, last_seen)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            last_seen = excluded.last_seen
        """,
        (packed, now),
    )

    last_history = conn.execute(
        "SELECT received_at FROM analytics_history ORDER BY id DESC LIMIT 1"
    ).fetchone()
    should_store = True
    if last_history is not None:
        try:
            previous = datetime.fromisoformat(last_history["received_at"])
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            should_store = (now_dt - previous).total_seconds() >= 300
        except Exception:
            should_store = True
    if should_store:
        conn.execute(
            "INSERT INTO analytics_history(received_at, payload) VALUES (?, ?)",
            (now, packed),
        )
        cutoff = (now_dt - timedelta(hours=72)).isoformat()
        conn.execute("DELETE FROM analytics_history WHERE received_at < ?", (cutoff,))

    conn.commit()
    conn.close()
    return {"ok": True, "received_at": now}


@app.get("/api/analytics")
def analytics_dashboard_data():
    conn = base.db()
    _analytics_table(conn)
    row = conn.execute(
        "SELECT payload, last_seen FROM analytics_state WHERE id = 1"
    ).fetchone()

    if row is None:
        conn.close()
        return {
            "status": "waiting",
            "age_seconds": None,
            "last_seen": None,
            "analytics": None,
            "views_24h": None,
        }

    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = None

    try:
        last_seen = datetime.fromisoformat(row["last_seen"])
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - last_seen).total_seconds(),
        )
    except Exception:
        age_seconds = None

    if payload is None:
        status = "invalid"
        views_24h = None
    else:
        views_24h = _views_24h(conn, payload, datetime.now(timezone.utc))
        if age_seconds is None:
            status = "unknown"
        elif age_seconds <= 30:
            status = "online"
        elif age_seconds <= 180:
            status = "stale"
        else:
            status = "offline"

    conn.close()
    return {
        "status": status,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "last_seen": row["last_seen"],
        "analytics": payload,
        "views_24h": views_24h,
    }


@app.get("/api/dashboard")
def reconciled_dashboard_data():
    data = base.dashboard_data()
    reconciliation = data.get("state_reconciliation") or {}
    current_job = data.get("current_job") or {}
    current_state = str(current_job.get("stage") or current_job.get("status") or "").lower()
    project_on_hold = current_state in {"paused", "on_hold", "on hold", "hold", "held"}

    if reconciliation.get("fresh"):
        status_counts = reconciliation.get("status_counts") or {}
        summary = data.setdefault("summary", {})

        summary["ready"] = sum(
            int(status_counts.get(key, 0) or 0)
            for key in ("ready_to_upload", "ready")
        )
        summary["queued"] = sum(
            int(status_counts.get(key, 0) or 0)
            for key in ("queued", "pending")
        )

        processing_states = {
            "downloading", "transcribing", "analyzing", "candidate_extraction",
            "ranking", "hook_ranking", "retention_qa", "generating_visuals",
            "rendering", "rendering_approved_clips", "quality_check", "metadata",
            "uploading", "retrying", "processing", "running", "remote_qa",
        }
        summary["processing"] = sum(
            int(status_counts.get(key, 0) or 0)
            for key in processing_states
        )

        summary["failed"] = sum(
            int(status_counts.get(key, 0) or 0)
            for key in ("failed", "error")
        )
        summary["skipped"] = int(status_counts.get("skipped", 0) or 0)

    if project_on_hold:
        summary = data.setdefault("summary", {})
        summary["processing"] = 0
        data["project_status"] = "on_hold"
        data["hold_job"] = current_job
        data["current_job"] = None

    return data


app.include_router(base.app.router)


# Project Mavrick telemetry is deliberately operational-only. The API rejects
# media, transcripts, prompts, observations, replies, and other retained content.
_MAVRICK_ALLOWED = {
    "state", "service", "camera", "microphone", "model", "model_ready",
    "speaker_route", "output_device", "last_error", "last_error_at",
    "stt_ms", "vision_ms", "tts_ms", "total_ms", "rss_mb", "load_1m",
    "version", "privacy", "updated_at",
}
_MAVRICK_FORBIDDEN = {
    "image", "frame", "audio", "transcript", "prompt", "observation",
    "reply", "question", "utterance", "media",
}


def _mavrick_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mavrick_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payload TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _sanitize_mavrick(payload):
    if not isinstance(payload, dict):
        return {}
    lowered = {str(key).lower() for key in payload}
    if lowered & _MAVRICK_FORBIDDEN:
        raise HTTPException(status_code=400, detail="Mavrick telemetry contains forbidden retained content")
    clean = {key: payload.get(key) for key in _MAVRICK_ALLOWED if key in payload}
    packed = json.dumps(clean, separators=(",", ":"))
    if len(packed.encode("utf-8")) > 8192:
        raise HTTPException(status_code=413, detail="Mavrick telemetry is too large")
    return clean


@app.post("/api/mavrick/update")
async def mavrick_update(request: Request):
    clean = _sanitize_mavrick(await request.json())
    now = datetime.now(timezone.utc).isoformat()
    clean["updated_at"] = clean.get("updated_at") or now
    conn = base.db()
    _mavrick_table(conn)
    conn.execute(
        """
        INSERT INTO mavrick_state (id, payload, last_seen)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            last_seen = excluded.last_seen
        """,
        (json.dumps(clean, separators=(",", ":")), now),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "received_at": now}


@app.get("/api/mavrick")
def mavrick_dashboard_data():
    conn = base.db()
    _mavrick_table(conn)
    row = conn.execute("SELECT payload, last_seen FROM mavrick_state WHERE id = 1").fetchone()
    conn.close()

    payload = {}
    last_seen = None
    age_seconds = None
    if row is not None:
        last_seen = row["last_seen"]
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {}
        try:
            stamp = datetime.fromisoformat(last_seen)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
        except Exception:
            age_seconds = None

    ollama_models = []
    try:
        req = urllib.request.Request(
            "http://192.168.0.88:11434/api/tags",
            headers={"User-Agent": "P2-Dashboard-Mavrick/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            tags = json.loads(response.read().decode("utf-8"))
        ollama_models = [
            str(item.get("name") or item.get("model") or "")
            for item in tags.get("models", [])
            if isinstance(item, dict)
        ]
    except Exception:
        pass

    configured_model = str(payload.get("model") or "qwen3-vl:2b")
    model_ready = configured_model in ollama_models
    payload["model"] = configured_model
    payload["model_ready"] = model_ready

    if row is None:
        status = "waiting"
    elif age_seconds is None or age_seconds > 45:
        status = "offline"
    elif payload.get("service") != "active":
        status = "degraded"
    elif not model_ready or not payload.get("camera") or not payload.get("microphone"):
        status = "degraded"
    else:
        status = "ready"

    return {
        "status": status,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "last_seen": last_seen,
        "mavrick": payload,
        "privacy": "operational telemetry only; no frames, audio, transcripts, or replies",
    }