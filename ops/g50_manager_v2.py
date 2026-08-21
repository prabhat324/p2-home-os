#!/usr/bin/env python3
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

DEFAULT_USER = "apc"
DEFAULT_PASSWORD = "apc"
SECRETS_PATH = Path.home() / ".config" / "p2-home-os" / "g50-secrets.json"
STATE_ROOT = Path.home() / ".local" / "state" / "p2-home-os" / "g50"


class G50Error(RuntimeError):
    pass


def rand(n=24):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def load_store():
    if not SECRETS_PATH.exists():
        return {}
    return json.loads(SECRETS_PATH.read_text())


def save_store(data):
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(SECRETS_PATH)
    os.chmod(SECRETS_PATH, 0o600)


def source_ip(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def port_open(host, port, timeout=1.2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class APC:
    def __init__(self, host):
        self.host = host
        self.session = None

    def req(self, method, path, data=None, timeout=6):
        body = None
        headers = {"User-Agent": "p2-home-os-g50/2.0"}
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
        status, headers, _ = self.req("POST", "/Forms/login1", {
            "login_username": user,
            "login_password": password,
            "submit": "Log On",
        })
        if status != 303:
            raise G50Error(f"login failed HTTP {status}")
        loc = headers.get("Location") or headers.get("location")
        if not loc:
            raise G50Error("login returned no Location")
        path = urlparse(loc).path
        m = re.match(r"(.*/NMC/[^/]+)/home\.htm$", path)
        if not m:
            raise G50Error(f"unexpected session path {path}")
        self.session = m.group(1)
        status, _, _ = self.req("GET", self.session + "/home.htm")
        if status != 200:
            raise G50Error(f"session validation failed HTTP {status}")

    def get(self, page):
        if not self.session:
            raise G50Error("not logged in")
        status, _, body = self.req("GET", self.session + "/" + page)
        if status != 200:
            raise G50Error(f"GET {page} failed HTTP {status}")
        return body.decode("utf-8", "replace")

    def post(self, form, data):
        if not self.session:
            raise G50Error("not logged in")
        status, _, body = self.req("POST", self.session + "/Forms/" + form, data)
        if status not in (200, 303):
            raise G50Error(f"POST {form} failed HTTP {status}")
        time.sleep(0.5)
        return body

    def logout(self):
        if not self.session:
            return
        old = self.session
        try:
            self.req("GET", old + "/logout.htm", timeout=3)
        except Exception:
            pass
        self.session = None


def backup(apc, device):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = STATE_ROOT / device / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    pages = ["home.htm", "adminusr.htm", "tcpv4cfg.htm", "webserv.htm", "console.htm",
             "ftpserv.htm", "snmp.htm", "snmpu.htm", "snmpusrs.htm", "snmpusra.htm",
             "genid.htm", "dateman.htm", "datentp.htm", "genreset.htm", "factinfo.htm"]
    for page in pages:
        try:
            (dest / page).write_text(apc.get(page))
        except Exception as exc:
            (dest / (page + ".error.txt")).write_text(str(exc) + "\n")
    print(f"backup={dest}")


def wait_login_page(host, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            c = http.client.HTTPConnection(host, 80, timeout=3)
            c.request("GET", "/logon.htm")
            r = c.getresponse()
            body = r.read().decode("utf-8", "replace")
            c.close()
            if r.status == 200:
                return
            if r.status == 403 and "Someone is currently logged" not in body:
                time.sleep(3)
            else:
                time.sleep(3)
        except Exception:
            time.sleep(3)
    raise G50Error("management login page did not become available")


def factory_reset_keep_ip(apc):
    old_session = apc.session
    apc.post("genreset1", {
        "resetSelect": "ResetDefaults",
        "resetAllExcludeTCPIP": "on",
        "submit": "Apply",
    })
    # This firmware can keep the existing web session alive after Reset All.
    # Explicitly release the single-login lock before reconnecting.
    if old_session:
        try:
            apc.req("GET", old_session + "/logout.htm", timeout=3)
        except Exception:
            pass
    apc.session = None
    time.sleep(3)
    wait_login_page(apc.host)


def selected(html, name, value=None):
    if value is None:
        pat = rf'<input[^>]*name="{re.escape(name)}"[^>]*checked'
    else:
        pat = rf'<input[^>]*name="{re.escape(name)}"[^>]*value="{re.escape(value)}"[^>]*checked'
    return bool(re.search(pat, html, re.I))


def value_is(html, name, value):
    return bool(re.search(rf'name="{re.escape(name)}"[^>]*value="{re.escape(value)}"', html, re.I))


def configure(apc, device, entry, nms_ip, current_password):
    apc.post("webserv1", {"webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"})
    apc.post("console1", {"consoleModeEnableDisable": "Disable", "ConsolePort": "23", "ConsoleSSHPort": "22", "submit": "Apply"})
    apc.post("ftpserv1", {"ftpPort": "21", "submit": "Apply"})
    apc.post("snmp1", {"submit": "Apply"})
    apc.post("snmpucfg1", {
        "i1usmUserName": entry["snmp_user"],
        "i2usmUserAuthPassphrase": entry["snmp_auth"],
        "i2usmUserCryptPassphrase": entry["snmp_priv"],
        "authProtocol": "authSHA",
        "privProtocol": "privAES",
        "submit": "Apply",
    })
    apc.post("snmpccfg1", {
        "i1usmUserAccessEnable": "on",
        "i1usmUserAccessMapping": entry["snmp_user"],
        "i1usmUserAccessAddr": nms_ip,
        "submit": "Apply",
    })
    apc.post("snmpu1", {"arak_snmpAccess": "on", "submit": "Apply"})
    apc.post("genid1", {
        "arak_sysName": device,
        "arak_sysContact": "psquare",
        "arak_sysLocation": "P2 Home OS rack",
        "submit": "Apply",
    })
    now = dt.datetime.now(ZoneInfo("America/Toronto"))
    apc.post("dateman1", {
        "timeZone": "07000000",
        "date_time_mode": "AddCert",
        "manualDate": now.strftime("%m/%d/%Y"),
        "manualTime": now.strftime("%H:%M:%S"),
        "submit": "Apply",
    })
    apc.post("datentp1", {"DSTSelectChoice": "Continental_United_States", "submit": "Apply"})
    apc.post("adminusr1", {
        "arak_adminusername": entry["username"],
        "arak_password": current_password,
        "arak_newPassword": entry["password"],
        "arak_confirmPassword": entry["password"],
        "submit": "Apply",
    })


def verify(apc, device, entry, nms_ip):
    problems = []
    web = apc.get("webserv.htm")
    console = apc.get("console.htm")
    ftp = apc.get("ftpserv.htm")
    v1 = apc.get("snmp.htm")
    v3 = apc.get("snmpu.htm")
    profile = apc.get("snmpucfg.htm?user=0")
    access = apc.get("snmpccfg.htm?user=0")
    ident = apc.get("genid.htm")
    dst = apc.get("datentp.htm")
    if not selected(web, "webModeEnableDisable", "HTTP"): problems.append("HTTP not selected")
    if not selected(console, "consoleModeEnableDisable", "Disable"): problems.append("console not disabled")
    if selected(ftp, "ftpEnable"): problems.append("FTP enabled")
    if selected(v1, "arak_snmpAccess"): problems.append("SNMPv1 enabled")
    if not selected(v3, "arak_snmpAccess"): problems.append("SNMPv3 disabled")
    if not value_is(profile, "i1usmUserName", entry["snmp_user"]): problems.append("SNMPv3 user mismatch")
    if not selected(profile, "authProtocol", "authSHA"): problems.append("SNMPv3 SHA not selected")
    if not selected(profile, "privProtocol", "privAES"): problems.append("SNMPv3 AES not selected")
    if not selected(access, "i1usmUserAccessEnable"): problems.append("SNMPv3 access not enabled")
    if not value_is(access, "i1usmUserAccessAddr", nms_ip): problems.append("NMS address mismatch")
    if not value_is(ident, "arak_sysName", device): problems.append("system name mismatch")
    if not selected(dst, "DSTSelectChoice", "Continental_United_States"): problems.append("DST profile mismatch")
    return problems


def provision(device, host, mac, factory_clean):
    store = load_store()
    entry = store.get(device)
    if entry:
        host = entry.get("host", host)
        apc = APC(host)
        apc.login(entry["username"], entry["password"])
        nms_ip = source_ip(host)
        configure(apc, device, entry, nms_ip, entry["password"])
        apc.logout()
    else:
        apc = APC(host)
        apc.login(DEFAULT_USER, DEFAULT_PASSWORD)
        backup(apc, device)
        if factory_clean:
            factory_reset_keep_ip(apc)
            print(f"post_reset_ip={host}")
            apc = APC(host)
            apc.login(DEFAULT_USER, DEFAULT_PASSWORD)
        entry = {
            "host": host,
            "mac": mac.lower(),
            "username": "psquare",
            "password": rand(28),
            "snmp_user": "p2mon",
            "snmp_auth": rand(24),
            "snmp_priv": rand(24),
            "factory_cleaned": bool(factory_clean),
            "verified": False,
            "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        store[device] = entry
        save_store(store)
        nms_ip = source_ip(host)
        configure(apc, device, entry, nms_ip, DEFAULT_PASSWORD)
        apc.logout()
        wait_login_page(host, timeout=45)

    check = APC(host)
    check.login(entry["username"], entry["password"])
    nms_ip = source_ip(host)
    problems = verify(check, device, entry, nms_ip)
    home = check.get("home.htm")
    no_alarms = "No Alarms" in home or "No alarms present" in home
    check.logout()
    ports = {p: port_open(host, p) for p in (21, 22, 23, 80, 443)}
    if not ports[80]: problems.append("HTTP 80 closed")
    for p in (21, 22, 23):
        if ports[p]: problems.append(f"legacy port {p} open")

    store = load_store()
    entry.update({"host": host, "nms_ip": nms_ip, "verified": not problems,
                  "no_alarms": no_alarms, "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
    store[device] = entry
    save_store(store)

    print(f"device={device}")
    print(f"host={host}")
    print(f"mac={mac.lower()}")
    print(f"nms_ip={nms_ip}")
    print(f"no_alarms={str(no_alarms).lower()}")
    print("ports=" + ",".join(f"{p}:{'open' if v else 'closed'}" for p, v in ports.items()))
    print(f"secrets_file={SECRETS_PATH}")
    if problems:
        for p in problems: print(f"VERIFY_FAIL={p}")
        return 2
    print("G50_PROVISION_OK")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--mac", required=True)
    p.add_argument("--factory-clean", action="store_true")
    a = p.parse_args()
    try:
        return provision(a.device, a.host, a.mac, a.factory_clean)
    except Exception as exc:
        print(f"G50_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
