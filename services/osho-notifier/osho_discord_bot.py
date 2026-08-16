#!/usr/bin/env python3
"""Read-only two-way Discord command bridge for Project Osho.

Uses Discord REST polling so no inbound home-network port is required.
Commands are accepted only from one configured channel and, when configured,
one Discord user ID.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = pathlib.Path.home()
CONFIG = HOME / ".config" / "osho-discord-bot.env"
STATE_DIR = HOME / ".local" / "state"
STATE_FILE = STATE_DIR / "osho-discord-bot-state.json"
API = "https://discord.com/api/v10"
DB = pathlib.Path("/srv/osho/library/catalog/catalog.sqlite")
RECEIPTS = pathlib.Path("/srv/osho/youtube/receipts")
METADATA = pathlib.Path("/srv/osho/metadata")


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw in CONFIG.read_text(encoding="utf-8").splitlines():
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            values[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    required = ("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID")
    missing = [k for k in required if not values.get(k)]
    if missing:
        raise SystemExit("missing Discord bot config: " + ",".join(missing))
    return values


CFG = load_config()
TOKEN = CFG["DISCORD_BOT_TOKEN"]
CHANNEL_ID = CFG["DISCORD_CHANNEL_ID"]
ALLOWED_USER_ID = CFG.get("DISCORD_ALLOWED_USER_ID", "")
BOT_USER_ID = CFG.get("DISCORD_BOT_USER_ID", "")


def api(method: str, path: str, payload: dict | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "Project-Osho-Discord-Bridge/1.0",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                body = response.read()
                return json.loads(body.decode("utf-8")) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    body = json.loads(exc.read().decode("utf-8"))
                    wait = float(body.get("retry_after", 1.0))
                except Exception:
                    wait = 2.0
                time.sleep(min(max(wait, 1.0), 30.0))
                continue
            raise
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    return {}


def post(text: str) -> None:
    api("POST", f"/channels/{CHANNEL_ID}/messages", {
        "content": text[:1900],
        "allowed_mentions": {"parse": []},
    })


def command(args: list[str], timeout: int = 12) -> str:
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.STDOUT, timeout=timeout
        ).strip()
    except subprocess.CalledProcessError as exc:
        return (exc.output or f"exit {exc.returncode}").strip()
    except Exception as exc:
        return f"unavailable ({type(exc).__name__})"


def db_rows(query: str, params: tuple = ()) -> list[tuple]:
    if not DB.exists():
        return []
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def status_text() -> str:
    counts = dict(db_rows(
        "SELECT status,COUNT(*) FROM osho_autopilot_state GROUP BY status"
    ))
    autopilot = command(["systemctl", "is-active", "osho-autopilot.service"])
    worker = "unavailable"
    try:
        with urllib.request.urlopen("http://127.0.0.1:8800/health", timeout=4) as r:
            worker = str(json.loads(r.read().decode()).get("status", "ok"))
    except Exception:
        pass
    return (
        "📊 **Project Osho status**\n"
        f"Autopilot: **{autopilot}** | Worker: **{worker}**\n"
        f"Published: **{counts.get('published', 0)}** | Processing: **{counts.get('processing', 0)}** | "
        f"Queued: **{counts.get('pending', 0)}** | Skipped: **{counts.get('skipped', 0)}** | "
        f"Failed: **{counts.get('failed', 0)}**"
    )


def progress_text() -> str:
    rows = db_rows(
        "SELECT source_id,status,job_id,note,updated_at FROM osho_autopilot_state "
        "WHERE status='processing' ORDER BY updated_at DESC LIMIT 1"
    )
    if not rows:
        return "⏸️ **Osho progress:** no source is currently marked processing."
    sid, status, job_id, note, updated = rows[0]
    title = db_rows("SELECT title FROM discourses WHERE source_id=? LIMIT 1", (sid,))
    title_text = title[0][0] if title and title[0][0] else sid
    # Dashboard has richer live phase/progress telemetry when available.
    stage = "processing"
    pct = "?"
    try:
        with urllib.request.urlopen("http://192.168.0.88:8787/api/dashboard", timeout=4) as r:
            d = json.loads(r.read().decode())
            cur = d.get("current_job") or {}
            if str(cur.get("id", "")).endswith(str(sid)):
                stage = str(cur.get("stage") or status)
                p = cur.get("progress")
                pct = f"{float(p):.1f}%" if p is not None else "?"
    except Exception:
        pass
    details = note or ""
    return (
        f"🔵 **Osho progress — {sid}**\n"
        f"**{title_text}**\nStage: **{stage}** | Progress: **{pct}**\n"
        f"Updated: {updated}" + (f"\n{details}" if details else "")
    )


def growth_text() -> str:
    helper = command(["sudo", "-n", "/usr/local/sbin/p2ops-osho-render-patch", "status"])
    growth_count = 0
    newest: tuple[float, pathlib.Path] | None = None
    if METADATA.is_dir():
        for p in METADATA.glob("*.json"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "osho-growth-v1" in text:
                growth_count += 1
                mt = p.stat().st_mtime
                if newest is None or mt > newest[0]:
                    newest = (mt, p)
    applied = "yes" if "GROWTH_TEMPLATE=yes" in helper else "unknown"
    artifact = newest[1].name if newest else "none yet"
    return (
        "🎬 **Growth V1**\n"
        f"Renderer applied: **{applied}**\n"
        f"Growth metadata artifacts: **{growth_count}**\n"
        f"Newest Growth artifact: **{artifact}**"
    )


def gpu_text() -> str:
    gpu = command([
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ])
    return "🖥️ **compute-01 GPU**\n```\n" + gpu[:1500] + "\n```"


def help_text() -> str:
    return (
        "🤖 **Project Osho Discord commands**\n"
        "`!osho status` — pipeline totals and health\n"
        "`!osho progress` — current source/stage/progress\n"
        "`!osho growth` — Growth V1 deployment/artifact proof\n"
        "`!osho gpu` — compute-01 GPU snapshot\n"
        "`!osho help` — this list\n\n"
        "Inbound commands are read-only; no restart/stop/publish controls are exposed."
    )


def handle(content: str) -> str | None:
    text = " ".join(content.strip().lower().split())
    if text == "!osho" or text == "!osho help":
        return help_text()
    if text == "!osho status":
        return status_text()
    if text == "!osho progress":
        return progress_text()
    if text == "!osho growth":
        return growth_text()
    if text == "!osho gpu":
        return gpu_text()
    return None


def load_state() -> dict:
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def main() -> int:
    state = load_state()
    last_id = str(state.get("last_message_id", ""))
    me = api("GET", "/users/@me")
    my_id = str(me.get("id", "")) if isinstance(me, dict) else ""
    post("🟢 **Project Osho two-way bridge online**\nTry `!osho progress` or `!osho growth`.")
    while True:
        try:
            suffix = "?limit=25"
            if last_id:
                suffix += "&after=" + urllib.parse.quote(last_id)
            messages = api("GET", f"/channels/{CHANNEL_ID}/messages{suffix}")
            if not isinstance(messages, list):
                time.sleep(3)
                continue
            for msg in sorted(messages, key=lambda m: int(m.get("id", 0))):
                mid = str(msg.get("id", ""))
                if mid:
                    last_id = mid
                author = msg.get("author") or {}
                author_id = str(author.get("id", ""))
                if author_id == my_id or (BOT_USER_ID and author_id == BOT_USER_ID):
                    continue
                if ALLOWED_USER_ID and author_id != ALLOWED_USER_ID:
                    continue
                response = handle(str(msg.get("content") or ""))
                if response:
                    post(response)
            state["last_message_id"] = last_id
            save_state(state)
            time.sleep(3)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"bridge error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(8)


if __name__ == "__main__":
    raise SystemExit(main())
