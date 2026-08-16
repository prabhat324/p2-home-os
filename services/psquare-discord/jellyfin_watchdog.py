#!/usr/bin/env python3
"""Critical Jellyfin availability watchdog for P² Home OS.

Runs continuously on core-01 as p2runner. It checks the three dependencies that
make the production Jellyfin service usable: compute-01 reachability, the
Jellyfin public API, and the read-only NFS media mount on compute-01. Alerts are
stateful: two consecutive failed probes trigger one critical Discord ping, and a
single recovery message is sent when all checks become healthy again.
"""
from __future__ import annotations

import argparse
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
STATE_FILE = STATE_DIR / "jellyfin-watchdog-state.json"
INVENTORY = HOME / ".config" / "psquare" / "hosts.yml"
API = "https://discord.com/api/v10"

COMPUTE_IP = "192.168.0.31"
JELLYFIN_URL = f"http://{COMPUTE_IP}:8096/System/Info/Public"
CHECK_INTERVAL = 20
FAILURES_TO_ALERT = 2


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID"):
        if not values.get(key):
            raise SystemExit(f"missing {key}")
    return values


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


def tcp_up(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def jellyfin_api() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(JELLYFIN_URL, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
        if str(data.get("ProductName") or "") != "Jellyfin Server":
            return False, "unexpected response on port 8096"
        return True, str(data.get("Version") or "unknown")
    except Exception as exc:
        return False, f"API unavailable ({type(exc).__name__})"


def media_mount_ok() -> tuple[bool, str]:
    fixed = (
        "set -eu; "
        "timeout 4 ls -1 /mnt/media >/dev/null; "
        "findmnt -T /mnt/media -n -o FSTYPE,SOURCE "
        "| grep -Eq '^nfs4[[:space:]]+192\\.168\\.0\\.203:/mnt/media$'"
    )
    cmd = [
        "ansible", "compute-01", "-i", str(INVENTORY),
        "-m", "shell", "-a", fixed, "-o",
    ]
    env = os.environ.copy()
    env["ANSIBLE_DEPRECATION_WARNINGS"] = "False"
    env["ANSIBLE_LOCALHOST_WARNING"] = "False"
    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            env=env,
            check=False,
        )
        if result.returncode == 0:
            return True, "NFS media mount readable"
        return False, "NFS /mnt/media missing or unreadable"
    except subprocess.TimeoutExpired:
        return False, "NFS /mnt/media probe timed out"
    except Exception as exc:
        return False, f"media probe failed ({type(exc).__name__})"


def probe() -> dict:
    reasons: list[str] = []
    version = "unknown"

    compute_ok = tcp_up(COMPUTE_IP, 22)
    if not compute_ok:
        reasons.append("compute-01 (192.168.0.31) is unreachable")
        return {
            "healthy": False,
            "compute": False,
            "jellyfin": False,
            "media": False,
            "version": version,
            "reasons": reasons,
        }

    api_ok, api_detail = jellyfin_api()
    if api_ok:
        version = api_detail
    else:
        reasons.append(f"Jellyfin {api_detail}")

    media_ok, media_detail = media_mount_ok()
    if not media_ok:
        reasons.append(media_detail)

    return {
        "healthy": compute_ok and api_ok and media_ok,
        "compute": compute_ok,
        "jellyfin": api_ok,
        "media": media_ok,
        "version": version,
        "reasons": reasons,
    }


def discord_post(cfg: dict[str, str], text: str, critical: bool = False) -> None:
    allowed_user = cfg.get("DISCORD_ALLOWED_USER_ID", "")
    content = text
    allowed_mentions: dict[str, object] = {"parse": []}
    if critical and allowed_user:
        content = f"<@{allowed_user}>\n" + content
        allowed_mentions = {"parse": [], "users": [allowed_user]}

    payload = json.dumps({
        "content": content[:1900],
        "allowed_mentions": allowed_mentions,
    }).encode("utf-8")
    req = urllib.request.Request(
        API + f"/channels/{cfg['DISCORD_CHANNEL_ID']}/messages",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bot {cfg['DISCORD_BOT_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "pSquare-Jellyfin-Watchdog/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()


def update_state(cfg: dict[str, str], result: dict, state: dict) -> dict:
    now = int(time.time())
    previous = str(state.get("status") or "unknown")
    failures = int(state.get("failures") or 0)

    if result["healthy"]:
        if previous == "down":
            down_since = int(state.get("down_since") or now)
            minutes = max(1, round((now - down_since) / 60))
            discord_post(
                cfg,
                "✅ **RECOVERED: Jellyfin is back online**\n"
                f"`compute-01` reachable · Jellyfin **{result['version']}** responding · `/mnt/media` readable.\n"
                f"Estimated outage duration: **{minutes} min**.",
            )
        state.update({
            "status": "up",
            "failures": 0,
            "last_ok": now,
            "last_reason": "",
        })
        return state

    failures += 1
    reason = "; ".join(result.get("reasons") or ["unknown failure"])
    state["failures"] = failures
    state["last_reason"] = reason
    state["last_failure"] = now

    if previous != "down" and failures >= FAILURES_TO_ALERT:
        state["status"] = "down"
        state["down_since"] = now
        discord_post(
            cfg,
            "🚨 **CRITICAL: Jellyfin is unavailable**\n"
            f"Detected by `core-01` after **{failures} consecutive checks**.\n"
            f"**Cause:** {reason}\n"
            "Production path: `core-01 media → NFS → compute-01 → Jellyfin :8096`.",
            critical=True,
        )
    elif previous == "down":
        state["status"] = "down"
    else:
        state["status"] = "suspect"

    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run one health probe and print JSON")
    args = parser.parse_args()

    if args.once:
        result = probe()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["healthy"] else 1

    cfg = load_config()
    state = load_state()
    while True:
        try:
            result = probe()
            state = update_state(cfg, result, state)
            save_state(state)
            print(json.dumps({"ts": int(time.time()), **result}), flush=True)
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"watchdog error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
