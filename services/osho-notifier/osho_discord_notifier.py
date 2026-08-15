#!/usr/bin/env python3
"""Project Osho Discord notifier."""

from __future__ import annotations
import json
import os
import pathlib
import re
import select
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = pathlib.Path.home()
CONFIG = HOME / ".config" / "osho-discord.env"
STATE_DIR = HOME / ".local" / "state"
STATE_FILE = STATE_DIR / "osho-discord-state.json"
RECEIPTS = pathlib.Path("/srv/osho/youtube/receipts")
MAX_MESSAGE = 1900
EVENT_RE = re.compile(
    r"(OSHO AUTOPILOT|STARTED|STOPPED|source|candidate|SAFE CANDIDATES|"
    r"GENUINE APPROVALS|queued|submitted|running|render|complete|failed|"
    r"error|upload|publish|ready_to_upload|skip)",
    re.IGNORECASE,
)
URGENT_RE = re.compile(r"(failed|failure|error|traceback|stopped)", re.IGNORECASE)

def load_webhook() -> str:
    try:
        for raw in CONFIG.read_text(encoding="utf-8").splitlines():
            if raw.startswith("DISCORD_WEBHOOK_URL="):
                value = raw.split("=", 1)[1].strip()
                if value.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")):
                    return value
    except FileNotFoundError:
        pass
    raise SystemExit("valid DISCORD_WEBHOOK_URL is missing")

WEBHOOK = load_webhook()

def post(message: str, retries: int = 4) -> bool:
    payload = json.dumps({
        "username": "Project Osho",
        "content": message[:MAX_MESSAGE],
        "allowed_mentions": {"parse": []},
    }).encode("utf-8")
    request = urllib.request.Request(
        WEBHOOK, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Project-Osho/1.0"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return 200 <= response.status < 300
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    wait = float(json.loads(exc.read().decode("utf-8")).get("retry_after", 1))
                    if wait > 100:
                        wait /= 1000
                except Exception:
                    wait = 2
                time.sleep(min(max(wait, 1), 30))
                continue
            print(f"Discord HTTP error: {exc.code}", file=sys.stderr, flush=True)
            return False
        except Exception as exc:
            print(f"Discord delivery error: {type(exc).__name__}", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
    return False

def load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    existing = [p.name for p in RECEIPTS.glob("*.json")] if RECEIPTS.is_dir() else []
    return {"receipts": existing}

def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(tmp, STATE_FILE)

def receipt_message(path: pathlib.Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    video_id = data.get("video_id") or data.get("youtube_video_id") or data.get("id") or data.get("youtube_id")
    title = data.get("title") or data.get("reel_id") or path.stem
    status = data.get("status") or data.get("upload_status") or "published"
    if not video_id and str(status).lower() not in {"uploaded", "published", "complete", "success"}:
        return None
    link = f"https://youtube.com/shorts/{video_id}" if video_id else "(receipt created)"
    return f"🚀 **YouTube upload {status}**\n**{title}**\n{link}"

def scan_receipts(state: dict) -> None:
    seen = set(state.get("receipts", []))
    if not RECEIPTS.is_dir():
        return
    changed = False
    for path in sorted(RECEIPTS.glob("*.json"), key=lambda p: p.stat().st_mtime):
        if path.name in seen:
            continue
        message = receipt_message(path)
        if message:
            post(message)
        seen.add(path.name)
        changed = True
    if changed:
        state["receipts"] = sorted(seen)[-2000:]
        save_state(state)


def worker_healthy() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8800/health", timeout=5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False

def critical_conditions() -> dict[str, str]:
    conditions: dict[str, str] = {}
    autopilot = command(["systemctl", "is-active", "osho-autopilot.service"])
    if autopilot != "active":
        conditions["autopilot"] = f"Autopilot service is {autopilot}"
    if not worker_healthy():
        conditions["worker"] = "Primary Osho worker health check failed"
    disk = shutil.disk_usage("/srv/osho")
    free_pct = disk.free * 100 / disk.total if disk.total else 0
    if free_pct < 10 or disk.free < 100 * 2**30:
        conditions["disk"] = (
            f"Osho storage is low: {disk.free / 2**30:.1f} GiB free "
            f"({free_pct:.1f}%)"
        )
    gpu_raw = command([
        "nvidia-smi", "--query-gpu=temperature.gpu",
        "--format=csv,noheader,nounits",
    ])
    try:
        temperatures = [int(v.strip()) for v in gpu_raw.splitlines() if v.strip()]
        hottest = max(temperatures)
        if hottest >= 85:
            conditions["gpu_temperature"] = f"GPU temperature is critical: {hottest}°C"
    except Exception:
        pass
    return conditions

def monitor_health(state: dict, now_epoch: float) -> None:
    previous = state.setdefault("critical_alerts", {})
    current = critical_conditions()
    changed = False
    for key, message in current.items():
        prior = previous.get(key, {})
        last_sent = float(prior.get("last_sent", 0)) if isinstance(prior, dict) else 0
        if not prior or now_epoch - last_sent >= 3600:
            post(f"🚨 **CRITICAL — Project Osho**\n{message}\nHost: compute-01")
            previous[key] = {"message": message, "last_sent": now_epoch}
            changed = True
    for key in list(previous):
        if key not in current:
            old = previous.pop(key)
            message = old.get("message", key) if isinstance(old, dict) else key
            post(f"✅ **RECOVERED — Project Osho**\n{message}\nHost: compute-01")
            changed = True
    last_summary = float(state.get("last_health_summary", 0))
    if now_epoch - last_summary >= 6 * 3600:
        post(resource_snapshot())
        state["last_health_summary"] = now_epoch
        changed = True
    if changed:
        save_state(state)

def journal_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["journalctl", "-u", "osho-autopilot.service", "-f", "-n", "0", "-o", "cat"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )


def command(args: list[str]) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    except Exception:
        return "unavailable"

def resource_snapshot() -> str:
    load = pathlib.Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3]
    mem = {}
    for line in pathlib.Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", 1)
        mem[key] = int(value.strip().split()[0])
    mem_total = mem.get("MemTotal", 0) / 1024 / 1024
    mem_avail = mem.get("MemAvailable", 0) / 1024 / 1024
    mem_used = max(mem_total - mem_avail, 0)
    disk = shutil.disk_usage("/srv/osho")
    gpu = command([
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ])
    autopilot = command(["systemctl", "is-active", "osho-autopilot.service"])
    worker = "unavailable"
    try:
        with urllib.request.urlopen("http://127.0.0.1:8800/health", timeout=5) as response:
            worker_data = json.loads(response.read().decode("utf-8"))
            worker = str(worker_data.get("status") or worker_data.get("ok") or "healthy")
    except Exception:
        pass
    pending = len(list(pathlib.Path("/srv/osho/renders/pending").glob("*"))) if pathlib.Path("/srv/osho/renders/pending").is_dir() else 0
    receipts = len(list(RECEIPTS.glob("*.json"))) if RECEIPTS.is_dir() else 0
    uptime = command(["uptime", "-p"])
    return (
        "📊 **Project Osho resource snapshot — compute-01**\n"
        f"**Time:** {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"**Uptime:** {uptime}\n"
        f"**Load (1/5/15m):** {' / '.join(load)}\n"
        f"**RAM:** {mem_used:.1f} / {mem_total:.1f} GiB used\n"
        f"**Osho disk:** {disk.used / 2**30:.1f} / {disk.total / 2**30:.1f} GiB used "
        f"({disk.free / 2**30:.1f} GiB free)\n"
        f"**GPU:** {gpu}\n"
        f"**Autopilot:** {autopilot}\n"
        f"**Worker health:** {worker}\n"
        f"**Pending renders:** {pending}\n"
        f"**YouTube receipts:** {receipts}"
    )

def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    save_state(state)
    post("🟢 **Project Osho Discord notifier online**\nWatching autopilot events and YouTube uploads on compute-01.")
    proc = journal_process()
    last_receipt_scan = 0.0
    last_health_check = 0.0
    try:
        while True:
            if proc.poll() is not None:
                post("⚠️ Project Osho journal watcher restarted.")
                time.sleep(3)
                proc = journal_process()
            line = ""
            if proc.stdout:
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if ready:
                    line = proc.stdout.readline().strip()
            if line and EVENT_RE.search(line):
                icon = "🔴" if URGENT_RE.search(line) else "🔵"
                post(f"{icon} **Osho pipeline**\n{line[-1800:]}")
            now = time.monotonic()
            if now - last_receipt_scan >= 15:
                scan_receipts(state)
                last_receipt_scan = now
            if now - last_health_check >= 60:
                monitor_health(state, time.time())
                last_health_check = now
            if not line:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0

if __name__ == "__main__":
    if "--snapshot" in sys.argv:
        raise SystemExit(0 if post(resource_snapshot()) else 1)
    raise SystemExit(main())
