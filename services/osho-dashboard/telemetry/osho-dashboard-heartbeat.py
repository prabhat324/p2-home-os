#!/usr/bin/env python3
import csv
import io
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

TELEMETRY_VERSION = "1.0.0"
DASHBOARD_URL = os.environ.get(
    "OSHO_DASHBOARD_URL",
    "http://compute-02:8787/api/worker/heartbeat",
)
INTERVAL = float(os.environ.get("OSHO_HEARTBEAT_INTERVAL", "10"))
WORKER_PORT = int(os.environ.get("OSHO_WORKER_PORT", "8800"))
WORKER_HEALTH_URL = os.environ.get(
    "OSHO_WORKER_HEALTH_URL",
    f"http://127.0.0.1:{WORKER_PORT}/health",
)

ROLE_BY_HOST = {
    "compute-01": "Primary GPU worker / autopilot",
    "compute-03": "Secondary GPU worker",
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
    status = run("systemctl", "is-active", "osho-autopilot.service")
    return status or "unknown"


def payload():
    hostname = socket.gethostname().split(".")[0]
    health = worker_health()

    data = {
        "name": hostname,
        "status": "online" if health else "degraded",
        "role": ROLE_BY_HOST.get(hostname, "Osho worker"),
        "ip": preferred_ip(),
        "current_job": None,
        "stage": "Idle" if health else "Worker API unavailable",
        "progress": 0,
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


def post(data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        DASHBOARD_URL,
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
    while True:
        try:
            post(payload())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"heartbeat failed: {exc}", flush=True)
        except Exception as exc:
            print(f"heartbeat unexpected error: {exc}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
