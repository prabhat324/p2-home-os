from datetime import datetime, timezone
import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse

import main as base


app = FastAPI(
    title="Project Osho Dashboard API",
    version=base.DASHBOARD_VERSION,
)


# Real page URLs backed by the shared command-center shell. The frontend reads
# location.pathname and renders only the content belonging to that page.
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
    .replace(/\\b\\w/g, c => c.toUpperCase());
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


# Compatibility alias for bookmarks and the analytics reporter UI added before
# the P² sidebar redesign.
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
    conn.commit()


@app.post("/api/analytics/update")
async def analytics_update(request: Request):
    payload = await request.json()
    now = datetime.now(timezone.utc).isoformat()

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
        (json.dumps(payload, separators=(",", ":")), now),
    )
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
    conn.close()

    if row is None:
        return {
            "status": "waiting",
            "age_seconds": None,
            "last_seen": None,
            "analytics": None,
        }

    try:
        payload = json.loads(row["payload"])
    except Exception:
        payload = None

    try:
        last_seen = datetime.fromisoformat(row["last_seen"])
        age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - last_seen).total_seconds(),
        )
    except Exception:
        age_seconds = None

    if payload is None:
        status = "invalid"
    elif age_seconds is None:
        status = "unknown"
    elif age_seconds <= 30:
        status = "online"
    elif age_seconds <= 180:
        status = "stale"
    else:
        status = "offline"

    return {
        "status": status,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "last_seen": row["last_seen"],
        "analytics": payload,
    }


@app.get("/api/dashboard")
def reconciled_dashboard_data():
    """Prefer fresh autopilot reconciliation over legacy job-row counters."""
    data = base.dashboard_data()
    reconciliation = data.get("state_reconciliation") or {}

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

    return data


# Keep the existing v0.5 dashboard API, health endpoint, telemetry endpoints and
# startup behavior intact. Routes registered above win; everything else comes
# from main.py.
app.include_router(base.app.router)
