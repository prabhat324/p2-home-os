#!/usr/bin/env python3
"""Manage APC G50NETB2 network settings from the P2 control plane.

No secrets are stored in Git. Device credentials are generated on core-01 and
persisted in ~/.config/p2-home-os/g50-secrets.json with mode 0600.
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
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

DEFAULT_USER = "apc"
DEFAULT_PASSWORD = "apc"
SECRETS_PATH = Path.home() / ".config" / "p2-home-os" / "g50-secrets.json"
STATE_ROOT = Path.home() / ".local" / "state" / "p2-home-os" / "g50"


class G50Error(RuntimeError):
    pass


def random_secret(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def load_secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    return json.loads(SECRETS_PATH.read_text())


def save_secrets(data: dict) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(SECRETS_PATH)
    os.chmod(SECRETS_PATH, 0o600)


def local_source_ip(remote_host: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((remote_host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def normalize_mac(mac: str) -> str:
    return mac.lower().replace("-", ":")


def discover_ip_by_mac(mac: str, subnet_prefix: str = "192.168.0") -> str | None:
    target = normalize_mac(mac)

    def ping_one(i: int) -> None:
        subprocess.run(
            ["ping", "-c", "1", "-W", "1", f"{subnet_prefix}.{i}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=48) as pool:
        list(pool.map(ping_one, range(1, 255)))

    try:
        neigh = subprocess.check_output(["ip", "neigh", "show"], text=True)
    except Exception:
        return None
    for line in neigh.splitlines():
        if target in line.lower():
            return line.split()[0]
    return None


class APCSession:
    def __init__(self, host: str, timeout: float = 6.0):
        self.host = host
        self.timeout = timeout
        self.session_base: str | None = None

    def _request(self, method: str, path: str, data: dict | None = None):
        body = None
        headers = {"User-Agent": "p2-home-os-g50/1.0"}
        if data is not None:
            body = urlencode(data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn = http.client.HTTPConnection(self.host, 80, timeout=self.timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            payload = response.read()
            return response.status, dict(response.getheaders()), payload
        finally:
            conn.close()

    def login(self, username: str, password: str) -> None:
        status, headers, body = self._request(
            "POST",
            "/Forms/login1",
            {"login_username": username, "login_password": password, "submit": "Log On"},
        )
        if status != 303:
            raise G50Error(f"login failed: HTTP {status}")
        location = headers.get("Location") or headers.get("location")
        if not location or "/NMC/" not in location:
            raise G50Error("login did not return an APC session URL")
        parsed = urlparse(location)
        match = re.match(r"(.*/NMC/[^/]+)/home\.htm$", parsed.path)
        if not match:
            raise G50Error(f"unexpected APC session path: {parsed.path}")
        self.session_base = match.group(1)
        status, _, _ = self._request("GET", f"{self.session_base}/home.htm")
        if status != 200:
            raise G50Error(f"session validation failed: HTTP {status}")

    def get(self, page: str) -> str:
        if not self.session_base:
            raise G50Error("not logged in")
        status, _, body = self._request("GET", f"{self.session_base}/{page}")
        if status != 200:
            raise G50Error(f"GET {page} failed: HTTP {status}")
        return body.decode("utf-8", errors="replace")

    def post(self, form: str, data: dict) -> tuple[int, dict, bytes]:
        if not self.session_base:
            raise G50Error("not logged in")
        return self._request("POST", f"{self.session_base}/Forms/{form}", data)

    def apply(self, form: str, data: dict) -> None:
        status, _, _ = self.post(form, data)
        if status not in (200, 303):
            raise G50Error(f"POST {form} failed: HTTP {status}")
        time.sleep(0.4)

    def logout(self) -> None:
        if self.session_base:
            try:
                self._request("GET", f"{self.session_base}/logout.htm")
            except Exception:
                pass
            self.session_base = None


def backup_pages(session: APCSession, device: str) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = STATE_ROOT / device / "backups" / stamp
    out.mkdir(parents=True, exist_ok=True)
    pages = [
        "home.htm", "adminusr.htm", "tcpv4cfg.htm", "webserv.htm", "console.htm",
        "ftpserv.htm", "snmp.htm", "snmpu.htm", "snmpusrs.htm", "snmpusra.htm",
        "genid.htm", "dateman.htm", "datentp.htm", "genreset.htm", "factinfo.htm",
    ]
    for page in pages:
        try:
            (out / page).write_text(session.get(page))
        except Exception as exc:
            (out / f"{page}.error.txt").write_text(str(exc) + "\n")
    return out


def wait_after_reset(host: str, mac: str, timeout: int = 150) -> str:
    deadline = time.time() + timeout
    current = host
    scanned = False
    while time.time() < deadline:
        if tcp_open(current, 80, timeout=1.0):
            try:
                text = http.client.HTTPConnection(current, 80, timeout=3)
                text.request("GET", "/logon.htm")
                resp = text.getresponse()
                resp.read()
                text.close()
                if resp.status in (200, 303):
                    return current
            except Exception:
                pass
        time.sleep(4)
        if not scanned and time.time() > deadline - timeout + 35:
            found = discover_ip_by_mac(mac)
            if found:
                current = found
            scanned = True
    raise G50Error("G50 management interface did not return after reset")


def checked(html: str, name: str, value: str | None = None) -> bool:
    if value is None:
        pattern = rf'<input[^>]*name="{re.escape(name)}"[^>]*checked'
    else:
        pattern = rf'<input[^>]*name="{re.escape(name)}"[^>]*value="{re.escape(value)}"[^>]*checked'
    return re.search(pattern, html, re.I) is not None


def verify_text_value(html: str, name: str, value: str) -> bool:
    pattern = rf'name="{re.escape(name)}"[^>]*value="{re.escape(value)}"'
    return re.search(pattern, html, re.I) is not None


def reset_all_except_tcpip(session: APCSession) -> None:
    status, _, _ = session.post(
        "genreset1",
        {"resetSelect": "ResetDefaults", "resetAllExcludeTCPIP": "on", "submit": "Apply"},
    )
    if status not in (200, 303):
        raise G50Error(f"reset request failed: HTTP {status}")
    session.session_base = None


def desired_config(session: APCSession, device: str, entry: dict, nms_ip: str, current_password: str) -> None:
    # Keep HTTP intentionally: the G50's TLS 1.1/3DES stack is incompatible with modern browsers.
    session.apply("webserv1", {
        "webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"
    })
    session.apply("console1", {
        "consoleModeEnableDisable": "Disable", "ConsolePort": "23", "ConsoleSSHPort": "22", "submit": "Apply"
    })
    session.apply("ftpserv1", {"ftpPort": "21", "submit": "Apply"})
    session.apply("snmp1", {"submit": "Apply"})

    session.apply("snmpucfg1", {
        "i1usmUserName": entry["snmp_user"],
        "i2usmUserAuthPassphrase": entry["snmp_auth"],
        "i2usmUserCryptPassphrase": entry["snmp_priv"],
        "authProtocol": "authSHA",
        "privProtocol": "privAES",
        "submit": "Apply",
    })
    session.apply("snmpccfg1", {
        "i1usmUserAccessEnable": "on",
        "i1usmUserAccessMapping": entry["snmp_user"],
        "i1usmUserAccessAddr": nms_ip,
        "submit": "Apply",
    })
    session.apply("snmpu1", {"arak_snmpAccess": "on", "submit": "Apply"})

    session.apply("genid1", {
        "arak_sysName": device,
        "arak_sysContact": "psquare",
        "arak_sysLocation": "P2 Home OS rack",
        "submit": "Apply",
    })

    now = dt.datetime.now(ZoneInfo("America/Toronto"))
    session.apply("dateman1", {
        "timeZone": "07000000",
        "date_time_mode": "AddCert",
        "manualDate": now.strftime("%m/%d/%Y"),
        "manualTime": now.strftime("%H:%M:%S"),
        "submit": "Apply",
    })
    session.apply("datentp1", {"DSTSelectChoice": "Continental_United_States", "submit": "Apply"})

    # Change local administrator credentials last so all preceding configuration remains recoverable.
    session.apply("adminusr1", {
        "arak_adminusername": entry["username"],
        "arak_password": current_password,
        "arak_newPassword": entry["password"],
        "arak_confirmPassword": entry["password"],
        "submit": "Apply",
    })


def verify_config(session: APCSession, device: str, entry: dict, nms_ip: str) -> list[str]:
    problems: list[str] = []
    web = session.get("webserv.htm")
    console = session.get("console.htm")
    ftp = session.get("ftpserv.htm")
    v1 = session.get("snmp.htm")
    v3 = session.get("snmpu.htm")
    profile = session.get("snmpucfg.htm?user=0")
    access = session.get("snmpccfg.htm?user=0")
    ident = session.get("genid.htm")
    dst = session.get("datentp.htm")

    if not checked(web, "webModeEnableDisable", "HTTP"):
        problems.append("HTTP management is not selected")
    if not checked(console, "consoleModeEnableDisable", "Disable"):
        problems.append("console access is not disabled")
    if checked(ftp, "ftpEnable"):
        problems.append("FTP is still enabled")
    if checked(v1, "arak_snmpAccess"):
        problems.append("SNMPv1 is still enabled")
    if not checked(v3, "arak_snmpAccess"):
        problems.append("SNMPv3 is not enabled")
    if not verify_text_value(profile, "i1usmUserName", entry["snmp_user"]):
        problems.append("SNMPv3 monitoring user does not match")
    if not checked(profile, "authProtocol", "authSHA"):
        problems.append("SNMPv3 SHA authentication is not selected")
    if not checked(profile, "privProtocol", "privAES"):
        problems.append("SNMPv3 AES privacy is not selected")
    if not checked(access, "i1usmUserAccessEnable"):
        problems.append("SNMPv3 access control is not enabled")
    if not verify_text_value(access, "i1usmUserAccessAddr", nms_ip):
        problems.append("SNMPv3 NMS address does not match core-01")
    if not verify_text_value(ident, "arak_sysName", device):
        problems.append("system name does not match")
    if not checked(dst, "DSTSelectChoice", "Continental_United_States"):
        problems.append("daylight saving profile is not enabled")
    return problems


def provision(device: str, host: str, mac: str, factory_clean: bool) -> int:
    data = load_secrets()
    entry = data.get(device)
    if entry:
        host = entry.get("host", host)
        session = APCSession(host)
        session.login(entry["username"], entry["password"])
        nms_ip = local_source_ip(host)
        # Re-enforce configuration without resetting a previously managed unit.
        desired_config(session, device, entry, nms_ip, entry["password"])
        session.logout()
    else:
        session = APCSession(host)
        session.login(DEFAULT_USER, DEFAULT_PASSWORD)
        backup = backup_pages(session, device)
        print(f"backup={backup}")
        if factory_clean:
            reset_all_except_tcpip(session)
            host = wait_after_reset(host, mac)
            print(f"post_reset_ip={host}")
            session = APCSession(host)
            session.login(DEFAULT_USER, DEFAULT_PASSWORD)

        entry = {
            "host": host,
            "mac": normalize_mac(mac),
            "username": "psquare",
            "password": random_secret(28),
            "snmp_user": "p2mon",
            "snmp_auth": random_secret(24),
            "snmp_priv": random_secret(24),
            "factory_cleaned": bool(factory_clean),
            "verified": False,
            "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        # Persist recovery credentials before changing the device administrator password.
        data[device] = entry
        save_secrets(data)
        nms_ip = local_source_ip(host)
        desired_config(session, device, entry, nms_ip, DEFAULT_PASSWORD)
        session.session_base = None

    # Verify with the managed credentials in a fresh session.
    verify = APCSession(host)
    verify.login(entry["username"], entry["password"])
    nms_ip = local_source_ip(host)
    problems = verify_config(verify, device, entry, nms_ip)
    home = verify.get("home.htm")
    no_alarms = "No Alarms" in home or "No alarms present" in home
    verify.logout()

    ports = {p: tcp_open(host, p) for p in (21, 22, 23, 80, 443)}
    if not ports[80]:
        problems.append("HTTP port 80 is not reachable")
    for port in (21, 22, 23):
        if ports[port]:
            problems.append(f"legacy management port {port} is still open")

    entry.update({
        "host": host,
        "nms_ip": nms_ip,
        "verified": not problems,
        "no_alarms": no_alarms,
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    data = load_secrets()
    data[device] = entry
    save_secrets(data)

    print(f"device={device}")
    print(f"host={host}")
    print(f"mac={normalize_mac(mac)}")
    print(f"nms_ip={nms_ip}")
    print(f"no_alarms={str(no_alarms).lower()}")
    print("ports=" + ",".join(f"{p}:{'open' if state else 'closed'}" for p, state in ports.items()))
    print(f"secrets_file={SECRETS_PATH}")
    if problems:
        for problem in problems:
            print(f"VERIFY_FAIL={problem}")
        return 2
    print("G50_PROVISION_OK")
    return 0


def audit(device: str) -> int:
    data = load_secrets()
    if device not in data:
        raise G50Error(f"no managed credentials found for {device}")
    entry = data[device]
    host = entry["host"]
    session = APCSession(host)
    session.login(entry["username"], entry["password"])
    nms_ip = local_source_ip(host)
    problems = verify_config(session, device, entry, nms_ip)
    home = session.get("home.htm")
    session.logout()
    print(f"device={device} host={host} no_alarms={str('No Alarms' in home or 'No alarms present' in home).lower()}")
    if problems:
        for problem in problems:
            print(f"AUDIT_FAIL={problem}")
        return 2
    print("G50_AUDIT_OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("provision")
    p.add_argument("--device", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--mac", required=True)
    p.add_argument("--factory-clean", action="store_true")
    a = sub.add_parser("audit")
    a.add_argument("--device", required=True)
    args = parser.parse_args()
    try:
        if args.command == "provision":
            return provision(args.device, args.host, args.mac, args.factory_clean)
        return audit(args.device)
    except Exception as exc:
        print(f"G50_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
