from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import threading
import time

from fastapi import HTTPException, Request

import power_server as base


app = base.app
LIVE_FILE = Path("/data/g50-live.json")
LIVE_MAX_AGE_SECONDS = 150
_live_lock = threading.Lock()
_original_collect_device = base._collect_device

DEVICE_MAP = {
    "g50-1": "g50-1",
    "g50-2": "g50-2",
    "p2-g50-01": "g50-1",
    "p2-g50-02": "g50-2",
}


def _load_live():
    try:
        data = json.loads(LIVE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_live(data):
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIVE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(LIVE_FILE)
    os.chmod(LIVE_FILE, 0o600)


def _number(value, minimum, maximum, name):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {name}") from exc
    if not minimum <= number <= maximum:
        raise HTTPException(status_code=422, detail=f"Out-of-range {name}")
    return number


def _trusted_peer(peer: str | None):
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    # Normal Docker DNAT preserves the LAN source. Some deployments expose the
    # bridge gateway instead, so permit only the dashboard bridge gateway as a
    # fallback. This endpoint can alter telemetry only; it has no control path.
    return str(addr) == "192.168.0.203" or str(addr) == "172.17.0.1"


def _fresh_live(device_id: str):
    with _live_lock:
        item = _load_live().get(device_id)
    if not isinstance(item, dict):
        return None
    try:
        age = time.time() - float(item.get("received_at", 0))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > LIVE_MAX_AGE_SECONDS:
        return None
    return item


def _collect_device_with_web(device_id: str, config: dict):
    current = _original_collect_device(device_id, config)
    live = _fresh_live(device_id)
    if not live:
        return current

    current.update({
        "online": True,
        "telemetry": "metered",
        "watts": live.get("watts"),
        "watts_source": "authenticated_web:olstatus.htm",
        "current_a": live.get("current_a"),
        "current_source": "authenticated_web:olstatus.htm",
        "voltage_v": live.get("voltage_v"),
        "frequency_hz": live.get("frequency_hz"),
        "web_telemetry_at": live.get("observed_at"),
        "web_telemetry_age_seconds": round(time.time() - float(live["received_at"]), 1),
        "message": None,
    })
    return current


# The existing /api/power/g50 handler resolves this module global at request
# time, so patching the collector lets the existing integration/cost code use
# the authenticated-web watts without duplicating billing logic.
base._collect_device = _collect_device_with_web


@app.post("/api/power/g50/ingest")
async def ingest_g50_power(request: Request):
    peer = request.client.host if request.client else None
    if not _trusted_peer(peer):
        raise HTTPException(status_code=403, detail=f"Untrusted telemetry source: {peer or 'unknown'}")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="JSON object required")
    source_device = str(payload.get("device") or "")
    device_id = DEVICE_MAP.get(source_device)
    if device_id is None:
        raise HTTPException(status_code=422, detail="Unknown G50 device")

    watts = _number(payload.get("watts"), 0, 5000, "watts")
    current_a = _number(payload.get("current_a"), 0, 30, "current_a")
    voltage_v = _number(payload.get("voltage_v"), 80, 150, "voltage_v")
    frequency_hz = _number(payload.get("frequency_hz"), 40, 70, "frequency_hz")
    if watts is None:
        raise HTTPException(status_code=422, detail="watts is required")

    now = time.time()
    observed_at = payload.get("observed_at") or datetime.now(timezone.utc).isoformat()
    item = {
        "device": device_id,
        "watts": watts,
        "current_a": current_a,
        "voltage_v": voltage_v,
        "frequency_hz": frequency_hz,
        "observed_at": str(observed_at),
        "received_at": now,
        "source": "core-01/authenticated-g50-web",
    }
    with _live_lock:
        data = _load_live()
        data[device_id] = item
        _write_live(data)

    # Do not make clients wait for the normal 12-second power cache to expire.
    try:
        base._cache["at"] = 0.0
    except Exception:
        pass
    return {"status": "accepted", "device": device_id, "received_at": now}
