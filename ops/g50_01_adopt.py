#!/usr/bin/env python3
"""Adopt the primary APC G50 into P2 Home OS without disturbing outlet power.

The primary G50 is already carrying production load, so this helper does NOT
factory-reset the device or change ProAV/outlet settings. It uses the temporary
administrator password placed locally on core-01, backs up management pages,
recovers the web UI from obsolete TLS 1.1/3DES to LAN-only HTTP, and then
normalizes the same management/security settings used by G50 #2.

No password or SNMP secret is printed or stored in Git.
"""
from __future__ import annotations

import datetime as dt
import http.client
import os
import re
import secrets
import socket
import string
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

from g50_manager_v3 import (
    APC,
    STORE,
    apply_setting,
    checked,
    load_store,
    port_open,
    rand,
    save_store,
    source_ip,
    value_is,
    wait_unlocked,
)

DEVICE = "p2-g50-01"
HOST = "192.168.0.236"
MAC = "28:29:86:19:72:b8"
ADMIN_USER = "psquare"
TEMP_PASSWORD_FILE = Path.home() / ".config" / "p2-home-os" / "g50-01-temp-password"
STATE_ROOT = Path.home() / ".local" / "state" / "p2-home-os" / "g50" / DEVICE


class AdoptError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def http_status(host: str, path: str = "/logon.htm", timeout: float = 4.0) -> int | None:
    try:
        c = http.client.HTTPConnection(host, 80, timeout=timeout)
        c.request("GET", path, headers={"User-Agent": "p2-home-os-g50-adopt/1.0"})
        r = c.getresponse()
        r.read()
        status = r.status
        c.close()
        return status
    except Exception:
        return None


def legacy_curl(url: str, method: str = "GET", data: dict | None = None, timeout: int = 15) -> tuple[int, str]:
    """Talk to the old TLS 1.1/3DES stack without placing secrets in argv."""
    variants = [
        ["--tls-max", "1.1", "--ciphers", "DES-CBC3-SHA:@SECLEVEL=0"],
        ["--tlsv1.1", "--tls-max", "1.1", "--ciphers", "DEFAULT:@SECLEVEL=0"],
        ["--tls-max", "1.1", "--ciphers", "DES-CBC3-SHA"],
        ["--tlsv1.1", "--tls-max", "1.1"],
    ]
    body = urlencode(data or {}) if data is not None else None
    last = ""
    for tls_args in variants:
        cmd = [
            "curl", "-sS", "-k", "--connect-timeout", "5", "--max-time", str(timeout),
            *tls_args, "-D", "-", "-o", "/dev/null", "-w", "\nP2_HTTP_CODE=%{http_code}\n",
        ]
        if method != "GET":
            cmd += ["-X", method]
        if body is not None:
            cmd += ["-H", "Content-Type: application/x-www-form-urlencoded", "--data-binary", "@-"]
        cmd.append(url)
        p = subprocess.run(cmd, input=body, text=True, capture_output=True, timeout=timeout + 5)
        combined = (p.stdout or "") + (p.stderr or "")
        last = combined
        m = re.search(r"P2_HTTP_CODE=(\d{3})", combined)
        if m and int(m.group(1)) != 0:
            return int(m.group(1)), combined
    raise AdoptError("core-01 could not negotiate the legacy HTTPS session")


def legacy_login(password: str) -> str:
    deadline = time.time() + 120
    last = ""
    while time.time() < deadline:
        code, out = legacy_curl(
            f"https://{HOST}/Forms/login1",
            "POST",
            {"login_username": ADMIN_USER, "login_password": password, "submit": "Log On"},
        )
        last = out
        if code == 303:
            loc = None
            for line in out.splitlines():
                if line.lower().startswith("location:"):
                    loc = line.split(":", 1)[1].strip()
                    break
            if not loc:
                raise AdoptError("legacy HTTPS login returned no session location")
            path = urlparse(loc).path
            m = re.match(r"(.*/NMC/[^/]+)/home\.htm$", path)
            if not m:
                raise AdoptError("legacy HTTPS login returned an unexpected APC session path")
            return m.group(1)
        if code == 403:
            time.sleep(5)
            continue
        raise AdoptError(f"legacy HTTPS login failed with HTTP {code}")
    raise AdoptError("legacy HTTPS interface remained locked")


def recover_http(password: str) -> None:
    if not port_open(HOST, 443):
        log("legacy_https=not_open")
        return
    log("legacy_https=detected")
    base = legacy_login(password)
    log("legacy_https=session_acquired")
    # Switching protocol can drop the response; a timeout is acceptable if HTTP returns.
    try:
        legacy_curl(
            f"https://{HOST}{base}/Forms/webserv1",
            "POST",
            {"webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"},
            timeout=8,
        )
    except Exception:
        pass

    deadline = time.time() + 90
    while time.time() < deadline:
        if port_open(HOST, 80) and http_status(HOST) in (200, 403):
            # 403 can be the transient single-session lock; protocol recovery still succeeded.
            log("legacy_https=http_recovered")
            return
        time.sleep(3)
    raise AdoptError("HTTP management did not return after legacy HTTPS recovery")


def backup_pages(a: APC) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = STATE_ROOT / "backups" / stamp
    out.mkdir(parents=True, exist_ok=True)
    pages = [
        "home.htm", "adminusr.htm", "devusr.htm", "readusr.htm", "authmgt.htm", "radius.htm",
        "tcpv4cfg.htm", "tcpv6cfg.htm", "webserv.htm", "console.htm", "ftpserv.htm",
        "snmp.htm", "snmpacc.htm", "snmpu.htm", "snmpusrs.htm", "snmpusra.htm",
        "genid.htm", "dateman.htm", "datentp.htm", "eventind.htm", "genreset.htm", "factinfo.htm",
    ]
    for page in pages:
        try:
            (out / page.replace("?", "_")).write_text(a.get(page))
        except Exception as exc:
            (out / (page.replace("?", "_") + ".error.txt")).write_text(type(exc).__name__ + "\n")
    return out


def main() -> int:
    if not TEMP_PASSWORD_FILE.exists():
        raise AdoptError(f"temporary password file is missing: {TEMP_PASSWORD_FILE}")
    mode = TEMP_PASSWORD_FILE.stat().st_mode & 0o777
    if mode & 0o077:
        raise AdoptError("temporary password file permissions are too broad")
    password = TEMP_PASSWORD_FILE.read_text().rstrip("\r\n")
    if not password:
        raise AdoptError("temporary password file is empty")

    log(f"device={DEVICE}")
    log(f"host={HOST}")
    log(f"mac={MAC}")

    # First escape the TLS 1.1/3DES-only management mode. This does not reboot the
    # outlet controller and does not alter power delivery.
    recover_http(password)
    wait_unlocked(HOST, timeout=180)

    # Confirm the supplied temporary credential before changing anything else.
    a = APC(HOST)
    a.login(ADMIN_USER, password)
    backup = backup_pages(a)
    a.logout()
    log(f"backup={backup}")

    store = load_store()
    old = store.get(DEVICE, {})
    entry = {
        "host": HOST,
        "mac": MAC,
        "username": ADMIN_USER,
        "password": password,
        "snmp_user": old.get("snmp_user", "p2mon1"),
        "snmp_auth": old.get("snmp_auth", rand(24)),
        "snmp_priv": old.get("snmp_priv", rand(24)),
        "factory_cleaned": bool(old.get("factory_cleaned", False)),
        "verified": False,
        "password_rotation_required": True,
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    store[DEVICE] = entry
    save_store(store)
    log("local_secret_state=secured")

    nms = source_ip(HOST)
    log(f"nms_ip={nms}")

    # The entry above makes g50_manager_v3 authenticate as the existing psquare
    # administrator. We intentionally preserve this temporary admin password so
    # the owner can rotate it after the device is fully normalized.
    apply_setting(HOST, entry, "web_http", "webserv.htm",
                  lambda h: checked(h, "webModeEnableDisable", "HTTP"),
                  "webserv1", {"webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"})
    apply_setting(HOST, entry, "console_off", "console.htm",
                  lambda h: checked(h, "consoleModeEnableDisable", "Disable"),
                  "console1", {"consoleModeEnableDisable": "Disable", "ConsolePort": "23", "ConsoleSSHPort": "22", "submit": "Apply"})
    apply_setting(HOST, entry, "ftp_off", "ftpserv.htm",
                  lambda h: not checked(h, "ftpEnable"),
                  "ftpserv1", {"ftpPort": "21", "submit": "Apply"})
    apply_setting(HOST, entry, "snmpv1_off", "snmp.htm",
                  lambda h: not checked(h, "arak_snmpAccess"),
                  "snmp1", {"submit": "Apply"})
    apply_setting(HOST, entry, "snmpv3_profile", "snmpucfg.htm?user=0",
                  lambda h: value_is(h, "i1usmUserName", entry["snmp_user"]) and checked(h, "authProtocol", "authSHA") and checked(h, "privProtocol", "privAES"),
                  "snmpucfg1", {"i1usmUserName": entry["snmp_user"], "i2usmUserAuthPassphrase": entry["snmp_auth"], "i2usmUserCryptPassphrase": entry["snmp_priv"], "authProtocol": "authSHA", "privProtocol": "privAES", "submit": "Apply"})
    apply_setting(HOST, entry, "snmpv3_acl", "snmpccfg.htm?user=0",
                  lambda h: checked(h, "i1usmUserAccessEnable") and value_is(h, "i1usmUserAccessAddr", nms),
                  "snmpccfg1", {"i1usmUserAccessEnable": "on", "i1usmUserAccessMapping": entry["snmp_user"], "i1usmUserAccessAddr": nms, "submit": "Apply"})
    apply_setting(HOST, entry, "snmpv3_on", "snmpu.htm",
                  lambda h: checked(h, "arak_snmpAccess"),
                  "snmpu1", {"arak_snmpAccess": "on", "submit": "Apply"})
    apply_setting(HOST, entry, "identity", "genid.htm",
                  lambda h: value_is(h, "arak_sysName", DEVICE),
                  "genid1", {"arak_sysName": DEVICE, "arak_sysContact": "psquare", "arak_sysLocation": "P2 Home OS rack", "submit": "Apply"})

    now = dt.datetime.now(ZoneInfo("America/Toronto"))
    apply_setting(HOST, entry, "time_eastern", "dateman.htm",
                  lambda h: 'value=07000000 selected="true"' in h or 'value="07000000" selected' in h,
                  "dateman1", {"timeZone": "07000000", "date_time_mode": "AddCert", "manualDate": now.strftime("%m/%d/%Y"), "manualTime": now.strftime("%H:%M:%S"), "submit": "Apply"})
    apply_setting(HOST, entry, "dst", "datentp.htm",
                  lambda h: checked(h, "DSTSelectChoice", "Continental_United_States"),
                  "datentp1", {"DSTSelectChoice": "Continental_United_States", "submit": "Apply"})

    final = APC(HOST)
    final.login(ADMIN_USER, password)
    home = final.get("home.htm")
    web = final.get("webserv.htm")
    console = final.get("console.htm")
    ftp = final.get("ftpserv.htm")
    v1 = final.get("snmp.htm")
    v3 = final.get("snmpu.htm")
    ident = final.get("genid.htm")
    final.logout()

    ports = {p: port_open(HOST, p) for p in (21, 22, 23, 80, 443)}
    problems = []
    if not checked(web, "webModeEnableDisable", "HTTP"): problems.append("HTTP management not selected")
    if not checked(console, "consoleModeEnableDisable", "Disable"): problems.append("console not disabled")
    if checked(ftp, "ftpEnable"): problems.append("FTP enabled")
    if checked(v1, "arak_snmpAccess"): problems.append("SNMPv1 enabled")
    if not checked(v3, "arak_snmpAccess"): problems.append("SNMPv3 disabled")
    if not value_is(ident, "arak_sysName", DEVICE): problems.append("identity mismatch")
    if ports[21]: problems.append("FTP/21 open")
    if ports[22]: problems.append("SSH/22 open")
    if ports[23]: problems.append("Telnet/23 open")
    if not ports[80]: problems.append("HTTP/80 closed")
    if ports[443]: problems.append("legacy HTTPS/443 still open")

    entry.update({
        "nms_ip": nms,
        "verified": not problems,
        "no_alarms": ("No Alarms" in home or "No alarms present" in home),
        "management_protocol": "http",
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    store = load_store()
    store[DEVICE] = entry
    save_store(store)

    log(f"no_alarms={str(entry['no_alarms']).lower()}")
    log("ports=" + ",".join(f"{p}:{'open' if v else 'closed'}" for p, v in ports.items()))
    log(f"secrets_file={STORE}")
    if problems:
        for problem in problems:
            log(f"VERIFY_FAIL={problem}")
        return 2

    # The temporary staging file is no longer needed; the current credential is
    # held in the protected P2 secret store until the owner rotates it.
    TEMP_PASSWORD_FILE.unlink(missing_ok=True)
    log("temporary_password_file=removed")
    log("password_rotation_required=true")
    log("G50_01_ADOPT_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"G50_01_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise SystemExit(1)
