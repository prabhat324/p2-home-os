from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import os
import re
import sqlite3
import subprocess
import threading
import time
from zoneinfo import ZoneInfo

from fastapi.responses import FileResponse, HTMLResponse

import storage_server as base_server


app = base_server.app

TORONTO = ZoneInfo("America/Toronto")
CACHE_SECONDS = 12
MAX_INTEGRATION_GAP_SECONDS = 120
POWER_DB = Path(os.environ.get("P2_POWER_DB", "/data/power-grid.db"))

G50_DEVICES = {
    "g50-1": {"label": "G50 #1", "ip": "192.168.0.236", "community_env": "G50_1_SNMP_COMMUNITY"},
    "g50-2": {"label": "G50 #2", "ip": "192.168.0.240", "community_env": "G50_2_SNMP_COMMUNITY"},
}

SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
SYS_DESCR_OID = "1.3.6.1.2.1.1.1.0"
MODEL_OID = "1.3.6.1.4.1.318.1.1.4.1.4.0"
SERIAL_OID = "1.3.6.1.4.1.318.1.1.4.1.5.0"
OUTLET_STATE_OID = "1.3.6.1.4.1.318.1.1.4.2.2.0"

# APC has several generations of PDU MIBs. The G50/AP9537AV units on this
# network expose the legacy switched-PDU identity/control tree. These power
# OIDs are intentionally probed rather than assumed; unsupported OIDs are
# reported as unavailable instead of inventing a watt value.
POWER_PROBES = (
    ("rPDUIdentDevicePowerWatts", "1.3.6.1.4.1.318.1.1.12.1.16.0", 1.0),
    ("rPDU2DeviceStatusPower", "1.3.6.1.4.1.318.1.1.26.4.3.1.5.1", 10.0),
)
CURRENT_PROBES = (
    ("rPDULoadStatusLoad", "1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1", 10.0),
    ("rPDU2PhaseStatusCurrent", "1.3.6.1.4.1.318.1.1.26.6.3.1.5.1", 10.0),
)
ENERGY_PROBES = (
    ("rPDU2DeviceStatusEnergy", "1.3.6.1.4.1.318.1.1.26.4.3.1.9.1", 10.0),
)

TOU_RATES = {
    "off_peak": 0.098,
    "mid_peak": 0.157,
    "on_peak": 0.203,
}

# Wasaga Distribution residential tariff effective May 1, 2026.
# The non-RPP Global Adjustment rider is deliberately excluded because this
# dashboard models a residential RPP TOU account.
WASAGA_VARIABLE_RATES = {
    "low_voltage": 0.0040,
    "deferral_variance_2026": 0.0006,
    "retail_transmission_network": 0.0117,
    "retail_transmission_line": 0.0081,
    "wholesale_market_service": 0.0041,
    "capacity_based_recovery_class_b": 0.0006,
    "rural_remote_protection": 0.0006,
}
WASAGA_FIXED_MONTHLY = {
    "service_charge": 29.74,
    "smart_metering_entity_charge": 0.42,
}
WASAGA_LOSS_FACTOR_SECONDARY = 1.0798
ONTARIO_ELECTRICITY_REBATE = 0.235
ONTARIO_HST = 0.13

HOLIDAYS_2026 = {
    date(2026, 1, 1),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 18),
    date(2026, 7, 1),
    date(2026, 8, 3),
    date(2026, 9, 7),
    date(2026, 10, 12),
    date(2026, 12, 25),
    date(2026, 12, 28),
}

_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()
_db_lock = threading.Lock()


def _tou_period(at: datetime | None = None):
    local = (at or datetime.now(TORONTO)).astimezone(TORONTO)
    summer = 5 <= local.month <= 10
    if local.weekday() >= 5 or local.date() in HOLIDAYS_2026:
        period = "off_peak"
    else:
        hour = local.hour + local.minute / 60
        if hour < 7 or hour >= 19:
            period = "off_peak"
        elif summer:
            if 11 <= hour < 17:
                period = "on_peak"
            else:
                period = "mid_peak"
        else:
            if 7 <= hour < 11 or 17 <= hour < 19:
                period = "on_peak"
            else:
                period = "mid_peak"
    return {
        "period": period,
        "label": period.replace("_", " ").title(),
        "season": "summer" if summer else "winter",
        "rate_cad_per_kwh": TOU_RATES[period],
        "rate_cents_per_kwh": round(TOU_RATES[period] * 100, 1),
        "local_time": local.isoformat(),
    }


def _variable_bill_rate(tou_rate: float):
    # Marginal bill-equivalent estimate for another measured kWh.
    # Commodity is adjusted by Wasaga's secondary-meter loss factor; published
    # variable delivery/regulatory rates are then added. OER is a credit on the
    # pre-HST base amount; HST remains a separate invoice charge.
    commodity_with_loss = tou_rate * WASAGA_LOSS_FACTOR_SECONDARY
    variable_delivery = sum(WASAGA_VARIABLE_RATES.values())
    pre_tax_base = commodity_with_loss + variable_delivery
    oer_credit = pre_tax_base * ONTARIO_ELECTRICITY_REBATE
    hst = pre_tax_base * ONTARIO_HST
    customer_cost = pre_tax_base + hst - oer_credit
    return {
        "commodity_with_loss": commodity_with_loss,
        "variable_delivery_regulatory": variable_delivery,
        "pre_tax_base": pre_tax_base,
        "oer_credit": oer_credit,
        "hst": hst,
        "customer_cost": customer_cost,
    }


def _community(device):
    specific = os.environ.get(device["community_env"], "").strip()
    generic = os.environ.get("G50_SNMP_COMMUNITY", "").strip()
    return specific or generic or "public"


def _run_snmpget(host: str, community: str, oid: str):
    proc = subprocess.run(
        ["snmpget", "-v1", "-c", community, "-On", "-t", "1", "-r", "0", host, oid],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=3,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "SNMP query failed").strip())
    line = proc.stdout.strip()
    match = re.match(r"^\.?([0-9.]+)\s+=\s+([^:]+):\s*(.*)$", line)
    if not match:
        raise RuntimeError("Unparseable SNMP response")
    _, kind, value = match.groups()
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return kind.strip(), value


def _snmp_value(host: str, community: str, oid: str):
    try:
        _, value = _run_snmpget(host, community, oid)
    except Exception:
        return None
    if "No Such" in value:
        return None
    return value


def _number(value):
    if value is None:
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", str(value))
    return float(match.group(0)) if match else None


def _probe_scaled(host, community, probes):
    for source, oid, scale in probes:
        value = _snmp_value(host, community, oid)
        parsed = _number(value)
        if parsed is not None:
            return parsed / scale, source
    return None, None


def _collect_device(key: str, device: dict):
    community = _community(device)
    name = _snmp_value(device["ip"], community, SYS_NAME_OID)
    if name is None:
        return {
            "id": key,
            "label": device["label"],
            "ip": device["ip"],
            "online": False,
            "snmp": False,
            "telemetry": "unavailable",
            "message": "SNMP read access is disabled, filtered, or uses a different read-only community.",
            "watts": None,
            "current_a": None,
            "meter_kwh": None,
        }

    watts, watts_source = _probe_scaled(device["ip"], community, POWER_PROBES)
    current_a, current_source = _probe_scaled(device["ip"], community, CURRENT_PROBES)
    meter_kwh, energy_source = _probe_scaled(device["ip"], community, ENERGY_PROBES)
    model = _snmp_value(device["ip"], community, MODEL_OID)
    serial = _snmp_value(device["ip"], community, SERIAL_OID)
    descr = _snmp_value(device["ip"], community, SYS_DESCR_OID)
    outlet_state = _snmp_value(device["ip"], community, OUTLET_STATE_OID)

    return {
        "id": key,
        "label": name or device["label"],
        "ip": device["ip"],
        "online": True,
        "snmp": True,
        "telemetry": "metered" if watts is not None else "identity_only",
        "model": model,
        "serial": serial,
        "description": descr,
        "outlet_state": outlet_state,
        "watts": watts,
        "watts_source": watts_source,
        "current_a": current_a,
        "current_source": current_source,
        "meter_kwh": meter_kwh,
        "energy_source": energy_source,
        "message": (
            None
            if watts is not None
            else "Device identity/outlet SNMP is available, but this legacy G50 firmware does not expose a supported watt meter OID."
        ),
    }


def _db():
    POWER_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(POWER_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS power_state (
            device TEXT PRIMARY KEY,
            last_at REAL,
            last_watts REAL,
            kwh_total REAL NOT NULL DEFAULT 0,
            tou_cost_total REAL NOT NULL DEFAULT 0,
            bill_cost_total REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS power_daily (
            day TEXT NOT NULL,
            device TEXT NOT NULL,
            kwh REAL NOT NULL DEFAULT 0,
            tou_cost REAL NOT NULL DEFAULT 0,
            bill_cost REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(day, device)
        )
        """
    )
    conn.commit()
    return conn


def _integrate(device_id: str, watts: float | None, now_ts: float, tou_rate: float, bill_rate: float):
    if watts is None or watts < 0:
        return
    with _db_lock:
        conn = _db()
        row = conn.execute("SELECT * FROM power_state WHERE device = ?", (device_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO power_state(device,last_at,last_watts) VALUES(?,?,?)",
                (device_id, now_ts, watts),
            )
            conn.commit()
            conn.close()
            return
        last_at = row["last_at"]
        last_watts = row["last_watts"]
        dt = now_ts - last_at if last_at is not None else None
        kwh = tou_cost = bill_cost = 0.0
        if (
            dt is not None
            and 0 < dt <= MAX_INTEGRATION_GAP_SECONDS
            and last_watts is not None
            and last_watts >= 0
        ):
            average_watts = (float(last_watts) + float(watts)) / 2.0
            kwh = average_watts / 1000.0 * dt / 3600.0
            tou_cost = kwh * tou_rate
            bill_cost = kwh * bill_rate

        conn.execute(
            """
            UPDATE power_state
            SET last_at=?, last_watts=?,
                kwh_total=kwh_total+?,
                tou_cost_total=tou_cost_total+?,
                bill_cost_total=bill_cost_total+?
            WHERE device=?
            """,
            (now_ts, watts, kwh, tou_cost, bill_cost, device_id),
        )
        if kwh:
            day = datetime.fromtimestamp(now_ts, TORONTO).date().isoformat()
            conn.execute(
                """
                INSERT INTO power_daily(day,device,kwh,tou_cost,bill_cost)
                VALUES(?,?,?,?,?)
                ON CONFLICT(day,device) DO UPDATE SET
                    kwh=kwh+excluded.kwh,
                    tou_cost=tou_cost+excluded.tou_cost,
                    bill_cost=bill_cost+excluded.bill_cost
                """,
                (day, device_id, kwh, tou_cost, bill_cost),
            )
        conn.commit()
        conn.close()


def _totals(device_id: str, now_ts: float):
    with _db_lock:
        conn = _db()
        state = conn.execute("SELECT * FROM power_state WHERE device=?", (device_id,)).fetchone()
        day = datetime.fromtimestamp(now_ts, TORONTO).date().isoformat()
        daily = conn.execute(
            "SELECT kwh,tou_cost,bill_cost FROM power_daily WHERE day=? AND device=?",
            (day, device_id),
        ).fetchone()
        conn.close()
    return {
        "kwh_today": float(daily["kwh"]) if daily else 0.0,
        "tou_cost_today_cad": float(daily["tou_cost"]) if daily else 0.0,
        "bill_cost_today_cad": float(daily["bill_cost"]) if daily else 0.0,
        "kwh_tracked": float(state["kwh_total"]) if state else 0.0,
        "tou_cost_tracked_cad": float(state["tou_cost_total"]) if state else 0.0,
        "bill_cost_tracked_cad": float(state["bill_cost_total"]) if state else 0.0,
    }


def _collect():
    now = datetime.now(TORONTO)
    now_ts = now.timestamp()
    tariff = _tou_period(now)
    bill = _variable_bill_rate(tariff["rate_cad_per_kwh"])
    devices = []
    for key, config in G50_DEVICES.items():
        device = _collect_device(key, config)
        _integrate(
            key,
            device.get("watts"),
            now_ts,
            tariff["rate_cad_per_kwh"],
            bill["customer_cost"],
        )
        device.update(_totals(key, now_ts))
        devices.append(device)

    live_watts = sum(d["watts"] for d in devices if d.get("watts") is not None)
    measured = [d for d in devices if d.get("watts") is not None]
    return {
        "status": "metered" if measured else "setup_required",
        "updated_at": now.isoformat(),
        "tariff": {
            **tariff,
            "utility": "Wasaga Distribution Inc.",
            "price_plan": "Ontario RPP Time-of-Use",
            "effective_prices": "2025-11-01",
            "distribution_tariff_effective": "2026-05-01",
            "loss_factor_secondary": WASAGA_LOSS_FACTOR_SECONDARY,
            "variable_delivery_regulatory_cad_per_kwh": round(sum(WASAGA_VARIABLE_RATES.values()), 4),
            "fixed_monthly_cad": round(sum(WASAGA_FIXED_MONTHLY.values()), 2),
            "oer_percent": ONTARIO_ELECTRICITY_REBATE * 100,
            "hst_percent": ONTARIO_HST * 100,
            "bill_equivalent_variable_rate_cad_per_kwh": round(bill["customer_cost"], 5),
            "bill_equivalent_variable_rate_cents_per_kwh": round(bill["customer_cost"] * 100, 3),
            "note": "Per-device totals exclude fixed monthly charges and any account-specific credits/adjustments.",
        },
        "devices": devices,
        "totals": {
            "live_watts": live_watts if measured else None,
            "metered_devices": len(measured),
            "kwh_today": sum(d["kwh_today"] for d in devices),
            "tou_cost_today_cad": sum(d["tou_cost_today_cad"] for d in devices),
            "bill_cost_today_cad": sum(d["bill_cost_today_cad"] for d in devices),
            "kwh_tracked": sum(d["kwh_tracked"] for d in devices),
            "tou_cost_tracked_cad": sum(d["tou_cost_tracked_cad"] for d in devices),
            "bill_cost_tracked_cad": sum(d["bill_cost_tracked_cad"] for d in devices),
        },
    }


@app.get("/api/power/g50")
def g50_power_data():
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
        data = _collect()
        _cache["at"] = now
        _cache["data"] = data
        return data


@app.get("/assets/powergrid.js")
def powergrid_js():
    return FileResponse(base_server.base_server.base.STATIC_DIR / "powergrid.js", media_type="application/javascript")


@app.middleware("http")
async def power_grid_ui_injector(request, call_next):
    if request.url.path in {"/", "/media", "/monitoring", "/network", "/storage", "/services", "/alerts"}:
        html = (base_server.base_server.base.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace(
            "</body>",
            '<script src="/assets/storage01.js"></script>\n'
            '<script src="/assets/powergrid.js"></script>\n</body>',
            1,
        )
        return HTMLResponse(html)
    return await call_next(request)
