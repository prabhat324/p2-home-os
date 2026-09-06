import os
import re
import subprocess
import threading
import time
import urllib.request

from fastapi.responses import FileResponse, HTMLResponse

import server as base_server


app = base_server.app
base_server.GLANCES_NODES["media-01"] = "192.168.0.6"

QNAP_HOST = "192.168.0.53"
COMMUNITY_FILE = "/data/storage-01-snmp-community"
DISK_TREE = "1.3.6.1.4.1.24681.1.3.11"
VOLUME_TREE = "1.3.6.1.4.1.24681.1.2.17"
CPU_OID = "1.3.6.1.4.1.24681.1.2.1.0"
SYS_DESCR_OID = "1.3.6.1.2.1.1.1.0"
CACHE_SECONDS = 10

_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def _community():
    value = os.environ.get("QNAP_SNMP_COMMUNITY", "").strip()
    if value:
        return value
    try:
        with open(COMMUNITY_FILE, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _qts_reachable():
    try:
        req = urllib.request.Request(
            "http://192.168.0.53:8080/",
            headers={"User-Agent": "P2-Dashboard-QNAP/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def _run_snmp(tool, oid, community):
    proc = subprocess.run(
        [tool, "-v2c", "-c", community, "-On", QNAP_HOST, oid],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=6,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "SNMP query failed").strip())
    return proc.stdout


def _parse_lines(text):
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"^\.?([0-9.]+)\s+=\s+([^:]+):\s*(.*)$", line)
        if not match:
            continue
        oid, kind, value = match.groups()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        rows.append((oid, kind.strip(), value))
    return rows


def _single_value(text):
    rows = _parse_lines(text)
    return rows[0][2] if rows else None


def _table(text, prefix):
    result = {}
    prefix = prefix.strip(".") + "."
    for oid, kind, value in _parse_lines(text):
        if not oid.startswith(prefix):
            continue
        suffix = oid[len(prefix):].split(".")
        if len(suffix) < 2:
            continue
        try:
            column = int(suffix[-2])
            index = int(suffix[-1])
        except ValueError:
            continue
        result.setdefault(index, {})[column] = value
    return result


def _float_prefix(value):
    if value is None:
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", str(value))
    return float(match.group(0)) if match else None


def _collect():
    community = _community()
    qts = _qts_reachable()
    if not community:
        return {
            "status": "unconfigured",
            "online": qts,
            "qts_reachable": qts,
            "snmp_configured": False,
            "model": "QNAP TS-831X",
            "ip": QNAP_HOST,
            "message": "SNMP community secret is not installed on compute-02",
        }

    try:
        cpu_text = _run_snmp("snmpget", CPU_OID, community)
        descr_text = _run_snmp("snmpget", SYS_DESCR_OID, community)
        disk_text = _run_snmp("snmpwalk", DISK_TREE, community)
        volume_text = _run_snmp("snmpwalk", VOLUME_TREE, community)

        disks_raw = _table(disk_text, "1.3.6.1.4.1.24681.1.3.11.1")
        disks = []
        for index in sorted(disks_raw):
            row = disks_raw[index]
            label = row.get(2) or f"HDD{index}"
            temp = _float_prefix(row.get(3))
            model = row.get(5) or "--"
            try:
                capacity = int(row.get(6) or 0)
            except ValueError:
                capacity = 0
            health = row.get(7) or "--"
            populated = model != "--" and capacity > 0
            disks.append({
                "bay": index,
                "label": label,
                "populated": populated,
                "temperature_c": temp if populated and temp and temp > 0 else None,
                "model": model if populated else None,
                "capacity_bytes": capacity if populated else 0,
                "health": health if populated else "EMPTY",
            })

        volumes_raw = _table(volume_text, "1.3.6.1.4.1.24681.1.2.17.1")
        volumes = []
        for index in sorted(volumes_raw):
            row = volumes_raw[index]
            total = row.get(4)
            free = row.get(5)
            total_n = _float_prefix(total)
            free_n = _float_prefix(free)
            used_pct = None
            if total_n and free_n is not None and total_n > 0:
                used_pct = max(0.0, min(100.0, 100.0 * (total_n - free_n) / total_n))
            volumes.append({
                "index": index,
                "name": row.get(2) or f"Volume {index}",
                "filesystem": row.get(3),
                "total": total,
                "free": free,
                "used_percent": round(used_pct, 2) if used_pct is not None else None,
                "status": row.get(6) or "Unknown",
            })

        populated = [disk for disk in disks if disk["populated"]]
        good = [disk for disk in populated if str(disk["health"]).upper() == "GOOD"]
        temps = [disk["temperature_c"] for disk in populated if disk["temperature_c"] is not None]
        volume_ready = all(str(volume["status"]).lower() == "ready" for volume in volumes) if volumes else False
        disks_good = len(good) == len(populated) and len(populated) > 0
        status = "healthy" if disks_good and volume_ready else "degraded"

        return {
            "status": status,
            "online": True,
            "qts_reachable": qts,
            "snmp_configured": True,
            "model": "QNAP TS-831X",
            "ip": QNAP_HOST,
            "system_description": _single_value(descr_text),
            "cpu_percent": _float_prefix(_single_value(cpu_text)),
            "bay_count": len(disks),
            "populated_bays": len(populated),
            "empty_bays": len(disks) - len(populated),
            "good_disks": len(good),
            "max_disk_temperature_c": max(temps) if temps else None,
            "disks": disks,
            "volumes": volumes,
            "updated_at": time.time(),
        }
    except Exception as exc:
        return {
            "status": "offline" if not qts else "snmp_error",
            "online": qts,
            "qts_reachable": qts,
            "snmp_configured": True,
            "model": "QNAP TS-831X",
            "ip": QNAP_HOST,
            "message": str(exc)[:240],
        }


@app.get("/api/storage/storage-01")
def storage01_data():
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
        data = _collect()
        _cache["at"] = now
        _cache["data"] = data
        return data


@app.get("/assets/storage01.js")
def storage01_js():
    return FileResponse(base_server.base.STATIC_DIR / "storage01.js", media_type="application/javascript")


@app.middleware("http")
async def storage01_ui_injector(request, call_next):
    # The Osho page has its own dynamic HTML injection in server.py; leave it alone.
    if request.url.path in {"/", "/media", "/monitoring", "/network", "/storage", "/services", "/alerts"}:
        html = (base_server.base.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("</body>", '<script src="/assets/storage01.js"></script>\n</body>', 1)
        return HTMLResponse(html)
    return await call_next(request)
