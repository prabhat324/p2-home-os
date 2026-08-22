#!/usr/bin/env python3
"""Push sanitized APC G50 electrical telemetry to the P2 dashboard.

Device credentials stay in the existing mode-0600 core-01 store. Only voltage,
frequency, current and watts are sent over the LAN. No outlet/control writes are
performed.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request

import g50_manager_v3 as g

DASHBOARD = "http://192.168.0.88:8787/api/power/g50/ingest"
DEVICES = (
    ("p2-g50-01", "192.168.0.236"),
    ("p2-g50-02", "192.168.0.240"),
)

VOLTAGE = re.compile(r"Line\s+Voltage:\s*([0-9.]+)\s*VAC", re.I)
FREQUENCY = re.compile(r"Line\s+Frequency:\s*([0-9.]+)\s*Hz", re.I)
CURRENT = re.compile(r"Output\s+Current:\s*([0-9.]+)\s*Amps?", re.I)
POWER = re.compile(r"Output\s+Power:\s*([0-9.]+)\s*Watts?", re.I)


def number(pattern, text):
    match = pattern.search(text)
    return float(match.group(1)) if match else None


def read_device(device: str, host: str):
    entry = g.load_store().get(device)
    if not entry:
        return None, "no-managed-secret"
    try:
        g.wait_unlocked(host, timeout=20)
        apc, _, _, _ = g.login_detect(host, entry, wait=False)
    except Exception as exc:
        return None, f"login-{type(exc).__name__}"
    try:
        page = apc.get("olstatus.htm")
    except Exception as exc:
        return None, f"status-{type(exc).__name__}"
    finally:
        apc.logout()

    watts = number(POWER, page)
    if watts is None:
        return None, "power-missing"
    payload = {
        "device": device,
        "watts": watts,
        "current_a": number(CURRENT, page),
        "voltage_v": number(VOLTAGE, page),
        "frequency_hz": number(FREQUENCY, page),
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return payload, "ok"


def push(payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        DASHBOARD,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "P2-G50-Telemetry/1.0"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        return response.status


def main():
    failures = 0
    for device, host in DEVICES:
        payload, state = read_device(device, host)
        if payload is None:
            # Deliberately contains no secret values.
            print(f"G50_PUSH device={device} state={state}")
            continue
        try:
            status = push(payload)
        except urllib.error.HTTPError as exc:
            print(f"G50_PUSH device={device} state=dashboard-http-{exc.code}")
            failures += 1
            continue
        except Exception as exc:
            print(f"G50_PUSH device={device} state=dashboard-{type(exc).__name__}")
            failures += 1
            continue
        print(
            f"G50_PUSH device={device} state=ok http={status} "
            f"watts={payload['watts']:.0f} current_a={payload.get('current_a')} "
            f"voltage_v={payload.get('voltage_v')} frequency_hz={payload.get('frequency_hz')}"
        )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
