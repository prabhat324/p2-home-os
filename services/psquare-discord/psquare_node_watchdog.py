#!/usr/bin/env python3
"""Proactive P² Home OS availability and compute-04 power watchdog.

Runs on core-01 and posts Discord alerts only on confirmed state changes.
Compute nodes are checked on SSH/22; storage-01 is checked on QTS/8080.
Three consecutive failures are required before declaring a node offline.
compute-04 is also queried for external-power and battery state so power loss
is reported before the machine reaches its graceful low-battery shutdown.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import socket
import subprocess
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
LOW_BATTERY_PERCENT = 30
BATTERY_RESET_PERCENT = 35
COMPUTE04_SSH_USER = "p2ops"
COMPUTE04_SSH_KEY = HOME / ".ssh" / "id_ed25519_p2homeos"

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
            "User-Agent": "pSquare-Home-OS-Node-Watchdog/1.1",
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


def probe_compute04_power() -> dict:
    """Return compute-04 power state; never raises when the host is unavailable."""
    remote = '''for p in /sys/class/power_supply/*; do
  [ -d "$p" ] || continue
  n="$(basename "$p")"
  t="$(cat "$p/type" 2>/dev/null || true)"
  o="$(cat "$p/online" 2>/dev/null || true)"
  s="$(cat "$p/status" 2>/dev/null || true)"
  c="$(cat "$p/capacity" 2>/dev/null || true)"
  printf '%s|%s|%s|%s|%s\n' "$n" "$t" "$o" "$s" "$c"
done
'''
    cmd = [
        "ssh",
        "-i", str(COMPUTE04_SSH_KEY),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "ConnectionAttempts=1",
        f"{COMPUTE04_SSH_USER}@{NODES['compute-04']['ip']}",
        "bash", "-s",
    ]
    try:
        proc = subprocess.run(cmd, input=remote, text=True, capture_output=True, timeout=12, check=False)
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__}
    if proc.returncode != 0:
        return {"available": False, "error": f"ssh_rc_{proc.returncode}"}

    supplies: list[dict] = []
    for raw in proc.stdout.splitlines():
        parts = raw.split("|", 4)
        if len(parts) != 5:
            continue
        name, kind, online, status, capacity = parts
        supplies.append({
            "name": name,
            "type": kind,
            "online": online == "1",
            "status": status,
            "capacity": int(capacity) if capacity.isdigit() else None,
        })

    battery = next((p for p in supplies if p["type"].lower() == "battery"), None)
    external = any(
        p["online"] and p["type"].lower() in {"mains", "usb", "usb_c", "usb-pd", "usb_pd"}
        for p in supplies
    )
    return {
        "available": True,
        "external_power": external,
        "battery_percent": battery.get("capacity") if battery else None,
        "battery_status": battery.get("status") if battery else "unknown",
    }


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


def update_node_state(state: dict, results: dict[str, bool], token: str, channel_id: str) -> None:
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


def update_compute04_power_state(state: dict, power: dict, token: str, channel_id: str) -> None:
    if not power.get("available"):
        return

    root = state.setdefault("power", {})
    item = root.setdefault("compute-04", {})
    external = bool(power.get("external_power"))
    battery = power.get("battery_percent")
    battery_status = str(power.get("battery_status") or "unknown")
    previous_external = item.get("external_power")

    if previous_external is True and not external:
        item["power_lost_since"] = iso_now()
        discord_post(
            token,
            channel_id,
            f"⚡ **P² power alert: compute-04 lost external power**\n"
            f"The node is still online, but it is now running from battery"
            + (f" at **{battery}%**." if isinstance(battery, int) else ".")
            + "\nPlease check its AC/USB-C power connection before the battery reaches shutdown level.",
        )
    elif previous_external is False and external:
        lost_since = item.get("power_lost_since")
        discord_post(
            token,
            channel_id,
            f"🔌 **P² power recovered: compute-04**\n"
            f"External power is available again"
            + (f"; battery is **{battery}%** ({battery_status})." if isinstance(battery, int) else ".")
            + (f"\nPower interruption lasted **{duration_text(lost_since)}**." if lost_since else ""),
        )
        item["power_lost_since"] = None
        item["low_battery_alerted"] = False
    elif previous_external is None and not external:
        item["power_lost_since"] = iso_now()
        discord_post(
            token,
            channel_id,
            f"⚡ **P² power alert: compute-04 has no external power**\n"
            f"The watchdog started while compute-04 was on battery"
            + (f" at **{battery}%**." if isinstance(battery, int) else "."),
        )

    low_risk = isinstance(battery, int) and battery <= LOW_BATTERY_PERCENT and (
        not external or battery_status.lower() == "discharging"
    )
    if low_risk and not bool(item.get("low_battery_alerted")):
        discord_post(
            token,
            channel_id,
            f"🪫 **P² low-battery warning: compute-04 at {battery}%**\n"
            f"Battery is {battery_status.lower()} and has reached the **{LOW_BATTERY_PERCENT}% warning threshold**.\n"
            "The machine will retain its normal graceful low-battery shutdown protection.",
        )
        item["low_battery_alerted"] = True
    elif isinstance(battery, int) and battery >= BATTERY_RESET_PERCENT:
        item["low_battery_alerted"] = False

    item["external_power"] = external
    item["battery_percent"] = battery
    item["battery_status"] = battery_status
    item["last_power_check"] = iso_now()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="print a probe snapshot and exit without alerting")
    args = parser.parse_args()

    if args.once:
        print(json.dumps({
            "nodes": {name: {**NODES[name], "online": up} for name, up in probe_all().items()},
            "compute04_power": probe_compute04_power(),
        }, sort_keys=True))
        return 0

    cfg = load_config()
    state = load_state()
    token = cfg["DISCORD_BOT_TOKEN"]
    channel_id = cfg["DISCORD_CHANNEL_ID"]

    while True:
        try:
            results = probe_all()
            update_node_state(state, results, token, channel_id)
            if results.get("compute-04"):
                update_compute04_power_state(state, probe_compute04_power(), token, channel_id)
            state["last_check"] = iso_now()
            save_state(state)
        except Exception as exc:
            print(f"node-watchdog error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
