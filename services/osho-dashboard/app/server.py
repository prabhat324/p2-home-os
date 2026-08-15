from datetime import datetime, timezone
import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse

import main as base


app = FastAPI(
    title="Project Osho Dashboard API",
    version=base.DASHBOARD_VERSION,
)


ANALYTICS_NAV = """
<div style="display:flex;gap:8px;margin:-6px 0 16px">
  <a href="/" style="padding:8px 11px;border:1px solid #5fa8ff;border-radius:10px;background:rgba(95,168,255,.12);font-size:12px;font-weight:700;letter-spacing:.6px">PIPELINE</a>
  <a href="/analytics" style="padding:8px 11px;border:1px solid #252b39;border-radius:10px;background:#121620;font-size:12px;font-weight:700;letter-spacing:.6px">ANALYTICS</a>
</div>
"""


@app.get("/")
def dashboard_with_analytics_tab():
    html = (base.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if 'href="/analytics"' not in html:
        marker = '<div class="mode" id="mode">'
        html = html.replace(marker, ANALYTICS_NAV + "\n    " + marker, 1)
    return HTMLResponse(html)


@app.get("/analytics")
def analytics_page():
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


# Keep the v0.5 dashboard API, health endpoint, telemetry endpoints and startup
# behavior intact. Our routes are registered first, so / and /analytics above
# win while all other existing routes continue to come from main.py.
app.include_router(base.app.router)
