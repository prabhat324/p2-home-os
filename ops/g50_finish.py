#!/usr/bin/env python3
"""Finish G50 reconciliation after the disruptive management-protocol changes.
Imports the v3 helper so generated secrets remain local to core-01 only.
"""
import argparse
import datetime as dt
import http.client
import socket
import time
from zoneinfo import ZoneInfo

import g50_manager_v3 as g


def log(s):
    print(s, flush=True)


def get_retry(apc, page, attempts=6):
    last = None
    for i in range(attempts):
        try:
            return apc.get(page)
        except (TimeoutError, socket.timeout, http.client.RemoteDisconnected) as exc:
            last = exc
            log(f"get_retry={page}:{i+1}")
            time.sleep(3)
    raise g.Err(f"GET {page} remained unavailable: {last}")


def apply_one(host, entry, stage, page, desired, form, data, settle=4):
    log(f"stage={stage}:check")
    g.wait_unlocked(host)
    apc, _, _, label = g.login_detect(host, entry, wait=False)
    try:
        before = get_retry(apc, page)
        if desired(before):
            log(f"stage={stage}:already_ok")
            return
        log(f"stage={stage}:apply")
        old = apc.base
        try:
            status, _, _ = apc.post(form, data, timeout=4)
            if status not in (200, 303):
                raise g.Err(f"{stage} apply HTTP {status}")
        except (TimeoutError, socket.timeout, http.client.RemoteDisconnected):
            log(f"stage={stage}:connection_dropped_expected")
        finally:
            if old:
                try:
                    apc.req("GET", old + "/logout.htm", timeout=3)
                except Exception:
                    pass
            apc.base = None
    finally:
        apc.logout()

    time.sleep(settle)
    g.wait_unlocked(host, timeout=120)
    check, _, _, _ = g.login_detect(host, entry, wait=False)
    try:
        after = get_retry(check, page)
        if not desired(after):
            raise g.Err(f"{stage} verification failed")
    finally:
        check.logout()
    log(f"stage={stage}:ok")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--mac", required=True)
    a = p.parse_args()
    try:
        store = g.load_store()
        entry = store.get(a.device)
        if not entry:
            raise g.Err("managed secret entry is missing on core-01")
        host = a.host
        nms = g.source_ip(host)
        log(f"device={a.device}")
        log(f"host={host}")
        log(f"nms_ip={nms}")

        apply_one(host, entry, "snmpv3_on", "snmpu.htm",
                  lambda h: g.checked(h, "arak_snmpAccess"),
                  "snmpu1", {"arak_snmpAccess": "on", "submit": "Apply"}, settle=10)

        apply_one(host, entry, "identity", "genid.htm",
                  lambda h: g.value_is(h, "arak_sysName", a.device),
                  "genid1", {"arak_sysName": a.device, "arak_sysContact": "psquare", "arak_sysLocation": "P2 Home OS rack", "submit": "Apply"})

        now = dt.datetime.now(ZoneInfo("America/Toronto"))
        apply_one(host, entry, "timezone", "dateman.htm",
                  lambda h: ('value=07000000 selected="true"' in h or 'value="07000000" selected' in h),
                  "dateman1", {"timeZone": "07000000", "date_time_mode": "AddCert", "manualDate": now.strftime("%m/%d/%Y"), "manualTime": now.strftime("%H:%M:%S"), "submit": "Apply"})

        apply_one(host, entry, "dst", "datentp.htm",
                  lambda h: g.checked(h, "DSTSelectChoice", "Continental_United_States"),
                  "datentp1", {"DSTSelectChoice": "Continental_United_States", "submit": "Apply"})

        # Change admin credentials only if the unit is still accepting defaults.
        g.wait_unlocked(host)
        apc, active_user, active_pass, label = g.login_detect(host, entry, wait=False)
        try:
            if label == "default":
                log("stage=admin_credentials:apply")
                old = apc.base
                try:
                    apc.post("adminusr1", {
                        "arak_adminusername": entry["username"],
                        "arak_password": active_pass,
                        "arak_newPassword": entry["password"],
                        "arak_confirmPassword": entry["password"],
                        "submit": "Apply",
                    }, timeout=4)
                except (TimeoutError, socket.timeout, http.client.RemoteDisconnected):
                    log("stage=admin_credentials:connection_dropped_expected")
                finally:
                    if old:
                        try: apc.req("GET", old + "/logout.htm", timeout=3)
                        except Exception: pass
                    apc.base = None
                time.sleep(6)
            else:
                log("stage=admin_credentials:already_ok")
        finally:
            apc.logout()

        g.wait_unlocked(host, timeout=120)
        final = g.APC(host)
        final.login(entry["username"], entry["password"])
        home = get_retry(final, "home.htm")
        ident = get_retry(final, "genid.htm")
        v3 = get_retry(final, "snmpu.htm")
        final.logout()

        no_alarms = "No Alarms" in home or "No alarms present" in home
        ports = {x: g.port_open(host, x) for x in (21, 22, 23, 80, 443)}
        problems = []
        if ports[21]: problems.append("FTP/21 open")
        if ports[22]: problems.append("SSH/22 open")
        if ports[23]: problems.append("Telnet/23 open")
        if not ports[80]: problems.append("HTTP/80 closed")
        if not g.checked(v3, "arak_snmpAccess"): problems.append("SNMPv3 not enabled")
        if not g.value_is(ident, "arak_sysName", a.device): problems.append("identity mismatch")

        entry.update({
            "host": host,
            "mac": a.mac.lower(),
            "nms_ip": nms,
            "verified": not problems,
            "no_alarms": no_alarms,
            "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        store = g.load_store(); store[a.device] = entry; g.save_store(store)

        log(f"no_alarms={str(no_alarms).lower()}")
        log("ports=" + ",".join(f"{p}:{'open' if v else 'closed'}" for p, v in ports.items()))
        log(f"secrets_file={g.STORE}")
        if problems:
            for x in problems: log(f"VERIFY_FAIL={x}")
            return 2
        log("G50_PROVISION_OK")
        return 0
    except Exception as exc:
        log(f"G50_ERROR={type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
