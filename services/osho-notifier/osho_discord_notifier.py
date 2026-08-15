#!/usr/bin/env python3
"""Project Osho Discord notifier."""

from __future__ import annotations
import json
import os
import pathlib
import re
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

def journal_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["journalctl", "-u", "osho-autopilot.service", "-f", "-n", "0", "-o", "cat"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )

def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    save_state(state)
    post("🟢 **Project Osho Discord notifier online**\nWatching autopilot events and YouTube uploads on compute-01.")
    proc = journal_process()
    last_receipt_scan = 0.0
    try:
        while True:
            if proc.poll() is not None:
                post("⚠️ Project Osho journal watcher restarted.")
                time.sleep(3)
                proc = journal_process()
            line = proc.stdout.readline().strip() if proc.stdout else ""
            if line and EVENT_RE.search(line):
                icon = "🔴" if URGENT_RE.search(line) else "🔵"
                post(f"{icon} **Osho pipeline**\n{line[-1800:]}")
            now = time.monotonic()
            if now - last_receipt_scan >= 15:
                scan_receipts(state)
                last_receipt_scan = now
            if not line:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
