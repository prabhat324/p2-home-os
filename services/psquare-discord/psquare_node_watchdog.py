#!/usr/bin/env python3
"""Proactive P² Home OS node availability watchdog.

Runs on core-01 and posts Discord alerts only on confirmed state changes.
Compute nodes are checked on SSH/22; storage-01 is checked on QTS/8080.
Three consecutive failures are required before declaring a node offline.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import socket
import time
import urllib.error
import urllib.request

HOME = pathlib.Path.home()
CONFIG = HOME / ".config" / "psquare-discord.env"
STATE_DIR = HOME / ".local" / "state"
STATE_FILE = STATE_DIR / "psquare-node-watchdog.json"
API = "https://discord.com/api/v10"
CHECK_INTERVAL_SECONDS = 60
FAILURE_THRESHOLD = 3

NODES = {
    "compute-01": {"ip": "192.168.0.31", "port": 22, "role": "primary-compute", "probe": "SSH"},
    "compute-02": {"ip": "192.168.0.88", "port": 22, "role": "orchestration", "probe": "SSH"},
    "compute-03": {"ip": "192.168.0.158", "port": 22, "role": "gpu-worker", "probe": "SSH"},
    "compute-04": {"ip": "192.168.0.177", "port": 22, "role": "light-gpu-worker", "probe": "SSH"},
    "storage-01": {"ip": "192.168.0.53", "port": 8080, "role": "QNAP NAS", "probe": "QTS"},
}


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat(timespec="seconds")


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"):
        if not values.get(key):
            raise SystemExit(f"missing {key} in {CONFIG}")
    return values


def discord_post(token: str, channel_id: str, text: str) -> None:
    payload = json.dumps({"content": text[:1900], "allowed_mentions": {"parse": []}}).encode("utf-8")
    req = urllib.request.Request(
        API + f"/channels/{channel_id}/messages",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "pSquare-Home-OS-Node-Watchdog/1.0",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                response.read()
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                try:
                    wait = float(json.loads(exc.read().decode("utf-8")).get("retry_after", 1.0))
                except Exception:
                    wait = 2.0
                time.sleep(min(max(wait, 1.0), 30.0))
                continue
            raise
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def tcp_up(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=2.0):
            return True
    except OSError:
        return False


def probe_all() -> dict[str, bool]:
    return {name: tcp_up(str(info["ip"]), int(info["port"])) for name, info in NODES.items()}


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def duration_text(start_iso: str | None) -> str:
    if not start_iso:
        return "unknown duration"
    try:
        start = dt.datetime.fromisoformat(start_iso)
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt.timezone.utc)
        seconds = max(0, int((utcnow() - start).total_seconds()))
    except Exception:
        return "unknown duration"
    if seconds < 120:
        return f"about {seconds} seconds"
    minutes = seconds // 60
    if minutes < 120:
        return f"about {minutes} minutes"
    hours, rem = divmod(minutes, 60)
    return f"about {hours}h {rem}m"


def update_state(state: dict, results: dict[str, bool], token: str, channel_id: str) -> None:
    nodes = state.setdefault("nodes", {})
    for name, is_up in results.items():
        info = NODES[name]
        item = nodes.setdefault(name, {"status": "unknown", "failures": 0, "down_since": None})
        previous = str(item.get("status") or "unknown")

        if is_up:
            item["failures"] = 0
            item["last_ok"] = iso_now()
            if previous == "offline":
                down_since = item.get("down_since")
                discord_post(
                    token,
                    channel_id,
                    f"🟢 **P² node recovered: {name}**\n"
                    f"{info['role']} is reachable again at `{info['ip']}` via {info['probe']}.\n"
                    f"Detected outage duration: **{duration_text(down_since)}**.",
                )
            item["status"] = "online"
            item["down_since"] = None
            continue

        item["failures"] = int(item.get("failures") or 0) + 1
        item["last_failure"] = iso_now()
        if previous != "offline" and item["failures"] >= FAILURE_THRESHOLD:
            item["status"] = "offline"
            item["down_since"] = item.get("down_since") or iso_now()
            discord_post(
                token,
                channel_id,
                f"🔴 **P² node offline: {name}**\n"
                f"{info['role']} at `{info['ip']}` failed **{FAILURE_THRESHOLD} consecutive {info['probe']} checks**.\n"
                f"The watchdog will keep checking and will send a recovery message automatically.",
            )
        elif previous == "offline":
            item["status"] = "offline"

    state["last_check"] = iso_now()
    save_state(state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="print a probe snapshot and exit without alerting")
    args = parser.parse_args()

    if args.once:
        print(json.dumps({name: {**NODES[name], "online": up} for name, up in probe_all().items()}, sort_keys=True))
        return 0

    cfg = load_config()
    state = load_state()
    token = cfg["DISCORD_BOT_TOKEN"]
    channel_id = cfg["DISCORD_CHANNEL_ID"]

    while True:
        try:
            update_state(state, probe_all(), token, channel_id)
        except Exception as exc:
            print(f"node-watchdog error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
