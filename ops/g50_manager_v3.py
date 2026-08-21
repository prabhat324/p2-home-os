#!/usr/bin/env python3
"""Reconcile an APC G50NETB2 into the P2 Home OS managed state.

Designed for the old AOS/proav2 web stack: it is single-login, some Apply
operations may transiently drop HTTP, and HTTPS is intentionally not used
because this firmware negotiates obsolete TLS. No credentials are printed or
stored in Git; managed secrets live only on core-01 under a mode-0600 file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
import re
import secrets
import socket
import string
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

STORE = Path.home() / ".config" / "p2-home-os" / "g50-secrets.json"
DEFAULT_USER = "apc"
DEFAULT_PASS = "apc"


class Err(RuntimeError):
    pass


def log(msg):
    print(msg, flush=True)


def rand(n=26):
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(n))


def load_store():
    if not STORE.exists():
        return {}
    return json.loads(STORE.read_text())


def save_store(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(STORE)
    os.chmod(STORE, 0o600)


def port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def source_ip(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


class APC:
    def __init__(self, host):
        self.host = host
        self.base = None

    def req(self, method, path, data=None, timeout=5):
        headers = {"User-Agent": "p2-home-os-g50/3.0"}
        body = None
        if data is not None:
            body = urlencode(data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        c = http.client.HTTPConnection(self.host, 80, timeout=timeout)
        try:
            c.request(method, path, body=body, headers=headers)
            r = c.getresponse()
            payload = r.read()
            return r.status, dict(r.getheaders()), payload
        finally:
            c.close()

    def login(self, user, password):
        status, headers, body = self.req("POST", "/Forms/login1", {
            "login_username": user,
            "login_password": password,
            "submit": "Log On",
        })
        if status == 403 and b"Someone is currently logged" in body:
            raise Err("web interface locked by another session")
        if status != 303:
            raise Err(f"login failed HTTP {status}")
        loc = headers.get("Location") or headers.get("location")
        if not loc:
            raise Err("login returned no session URL")
        path = urlparse(loc).path
        m = re.match(r"(.*/NMC/[^/]+)/home\.htm$", path)
        if not m:
            raise Err("unexpected APC session URL")
        self.base = m.group(1)
        status, _, _ = self.req("GET", self.base + "/home.htm")
        if status != 200:
            raise Err(f"session validation failed HTTP {status}")

    def get(self, page):
        if not self.base:
            raise Err("not logged in")
        status, _, body = self.req("GET", self.base + "/" + page)
        if status != 200:
            raise Err(f"GET {page} failed HTTP {status}")
        return body.decode("utf-8", "replace")

    def post(self, form, data, timeout=5):
        if not self.base:
            raise Err("not logged in")
        return self.req("POST", self.base + "/Forms/" + form, data, timeout=timeout)

    def logout(self):
        old = self.base
        self.base = None
        if not old:
            return
        try:
            self.req("GET", old + "/logout.htm", timeout=3)
        except Exception:
            pass


def wait_unlocked(host, timeout=240):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            c = http.client.HTTPConnection(host, 80, timeout=3)
            c.request("GET", "/logon.htm")
            r = c.getresponse()
            body = r.read().decode("utf-8", "replace")
            c.close()
            if r.status == 200:
                return
            if r.status == 403 and "Someone is currently logged" in body:
                last = "single-login lock"
            else:
                last = f"HTTP {r.status}"
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(4)
    raise Err(f"login page remained unavailable ({last})")


def checked(html, name, value=None):
    if value is None:
        pattern = rf'<input[^>]*name="{re.escape(name)}"[^>]*checked'
    else:
        pattern = rf'<input[^>]*name="{re.escape(name)}"[^>]*value="{re.escape(value)}"[^>]*checked'
    return re.search(pattern, html, re.I) is not None


def value_is(html, name, value):
    return re.search(rf'name="{re.escape(name)}"[^>]*value="{re.escape(value)}"', html, re.I) is not None


def credential_candidates(entry):
    out = []
    if entry:
        out.append((entry["username"], entry["password"], "managed"))
    out.append((DEFAULT_USER, DEFAULT_PASS, "default"))
    return out


def login_detect(host, entry, wait=True):
    if wait:
        wait_unlocked(host)
    errors = []
    for user, password, label in credential_candidates(entry):
        a = APC(host)
        try:
            a.login(user, password)
            log(f"credential_state={label}")
            return a, user, password, label
        except Exception as exc:
            errors.append(f"{label}:{type(exc).__name__}")
    raise Err("no known credential set can log in (" + ",".join(errors) + ")")


def apply_setting(host, entry, stage, page, desired, form, data, credential_override=None):
    log(f"stage={stage}:check")
    a, user, password, label = login_detect(host, entry)
    try:
        before = a.get(page)
        if desired(before):
            log(f"stage={stage}:already_ok")
            return label
        log(f"stage={stage}:apply")
        oldbase = a.base
        timed_out = False
        try:
            status, _, _ = a.post(form, data, timeout=4)
            if status not in (200, 303):
                raise Err(f"{stage} apply HTTP {status}")
        except (TimeoutError, socket.timeout, http.client.RemoteDisconnected):
            timed_out = True
            log(f"stage={stage}:apply_connection_dropped")
        finally:
            # Release the APC single-web-login lock even if Apply dropped the connection.
            if oldbase:
                try:
                    a.req("GET", oldbase + "/logout.htm", timeout=3)
                except Exception:
                    pass
            a.base = None
        if timed_out:
            deadline = time.time() + 45
            while time.time() < deadline and not port_open(host, 80):
                time.sleep(2)
        wait_unlocked(host, timeout=90)
        # For admin credential change, caller verifies separately with managed credentials.
        if credential_override == "defer_verify":
            log(f"stage={stage}:submitted")
            return label
        b, _, _, _ = login_detect(host, entry, wait=False)
        try:
            after = b.get(page)
            if not desired(after):
                raise Err(f"{stage} verification failed")
        finally:
            b.logout()
        log(f"stage={stage}:ok")
        return label
    finally:
        a.logout()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--mac", required=True)
    args = p.parse_args()
    host, device, mac = args.host, args.device, args.mac.lower()

    try:
        store = load_store()
        entry = store.get(device)
        if not entry:
            entry = {
                "host": host,
                "mac": mac,
                "username": "psquare",
                "password": rand(28),
                "snmp_user": "p2mon",
                "snmp_auth": rand(24),
                "snmp_priv": rand(24),
                "factory_cleaned": True,
                "verified": False,
                "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            store[device] = entry
            save_store(store)
            log("local_secret_state=created")
        else:
            log("local_secret_state=present")

        entry["host"] = host
        entry["mac"] = mac
        nms = source_ip(host)
        log(f"device={device}")
        log(f"host={host}")
        log(f"nms_ip={nms}")

        # First recover from any abandoned APC single-login session.
        log("stage=session_wait")
        wait_unlocked(host)
        log("stage=session_available")

        # Do not touch Web Access when it is already HTTP; this firmware can drop
        # management connections when protocol settings are re-applied.
        apply_setting(host, entry, "web_http", "webserv.htm",
                      lambda h: checked(h, "webModeEnableDisable", "HTTP"),
                      "webserv1", {"webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"})

        apply_setting(host, entry, "console_off", "console.htm",
                      lambda h: checked(h, "consoleModeEnableDisable", "Disable"),
                      "console1", {"consoleModeEnableDisable": "Disable", "ConsolePort": "23", "ConsoleSSHPort": "22", "submit": "Apply"})

        apply_setting(host, entry, "ftp_off", "ftpserv.htm",
                      lambda h: not checked(h, "ftpEnable"),
                      "ftpserv1", {"ftpPort": "21", "submit": "Apply"})

        apply_setting(host, entry, "snmpv1_off", "snmp.htm",
                      lambda h: not checked(h, "arak_snmpAccess"),
                      "snmp1", {"submit": "Apply"})

        apply_setting(host, entry, "snmpv3_profile", "snmpucfg.htm?user=0",
                      lambda h: value_is(h, "i1usmUserName", entry["snmp_user"]) and checked(h, "authProtocol", "authSHA") and checked(h, "privProtocol", "privAES"),
                      "snmpucfg1", {"i1usmUserName": entry["snmp_user"], "i2usmUserAuthPassphrase": entry["snmp_auth"], "i2usmUserCryptPassphrase": entry["snmp_priv"], "authProtocol": "authSHA", "privProtocol": "privAES", "submit": "Apply"})

        apply_setting(host, entry, "snmpv3_acl", "snmpccfg.htm?user=0",
                      lambda h: checked(h, "i1usmUserAccessEnable") and value_is(h, "i1usmUserAccessAddr", nms),
                      "snmpccfg1", {"i1usmUserAccessEnable": "on", "i1usmUserAccessMapping": entry["snmp_user"], "i1usmUserAccessAddr": nms, "submit": "Apply"})

        apply_setting(host, entry, "snmpv3_on", "snmpu.htm",
                      lambda h: checked(h, "arak_snmpAccess"),
                      "snmpu1", {"arak_snmpAccess": "on", "submit": "Apply"})

        apply_setting(host, entry, "identity", "genid.htm",
                      lambda h: value_is(h, "arak_sysName", device),
                      "genid1", {"arak_sysName": device, "arak_sysContact": "psquare", "arak_sysLocation": "P2 Home OS rack", "submit": "Apply"})

        now = dt.datetime.now(ZoneInfo("America/Toronto"))
        apply_setting(host, entry, "time_eastern", "dateman.htm",
                      lambda h: 'value=07000000 selected="true"' in h or 'value="07000000" selected' in h,
                      "dateman1", {"timeZone": "07000000", "date_time_mode": "AddCert", "manualDate": now.strftime("%m/%d/%Y"), "manualTime": now.strftime("%H:%M:%S"), "submit": "Apply"})

        apply_setting(host, entry, "dst", "datentp.htm",
                      lambda h: checked(h, "DSTSelectChoice", "Continental_United_States"),
                      "datentp1", {"DSTSelectChoice": "Continental_United_States", "submit": "Apply"})

        # Admin last. If managed credentials already work, skip; otherwise change
        # from default to the locally generated managed password.
        a, active_user, active_pass, label = login_detect(host, entry)
        try:
            if label == "default":
                log("stage=admin_credentials:apply")
                oldbase = a.base
                try:
                    a.post("adminusr1", {"arak_adminusername": entry["username"], "arak_password": active_pass,
                                           "arak_newPassword": entry["password"], "arak_confirmPassword": entry["password"], "submit": "Apply"}, timeout=4)
                except (TimeoutError, socket.timeout, http.client.RemoteDisconnected):
                    log("stage=admin_credentials:apply_connection_dropped")
                finally:
                    if oldbase:
                        try: a.req("GET", oldbase + "/logout.htm", timeout=3)
                        except Exception: pass
                    a.base = None
                wait_unlocked(host, timeout=90)
            else:
                log("stage=admin_credentials:already_ok")
        finally:
            a.logout()

        final = APC(host)
        final.login(entry["username"], entry["password"])
        home = final.get("home.htm")
        final.logout()
        no_alarms = "No Alarms" in home or "No alarms present" in home
        ports = {x: port_open(host, x) for x in (21, 22, 23, 80, 443)}
        problems = []
        if ports[21]: problems.append("FTP/21 open")
        if ports[22]: problems.append("SSH/22 open")
        if ports[23]: problems.append("Telnet/23 open")
        if not ports[80]: problems.append("HTTP/80 closed")

        entry.update({"host": host, "nms_ip": nms, "verified": not problems,
                      "no_alarms": no_alarms, "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        store = load_store(); store[device] = entry; save_store(store)

        log(f"no_alarms={str(no_alarms).lower()}")
        log("ports=" + ",".join(f"{p}:{'open' if v else 'closed'}" for p, v in ports.items()))
        log(f"secrets_file={STORE}")
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
