#!/usr/bin/env python3
"""Recover and adopt APC G50 #1 without touching outlet power.

G50 #1 runs an AOS 5.1-era TLS stack (TLS 1.1 + 3DES).  Modern OpenSSL on
core-01 no longer negotiates it.  This helper builds a private, unprivileged
OpenSSL 1.1.1w under the p2runner home directory, uses it only for the one-time
management-web recovery, reboots the *management interface* through the APC
confirmation flow, then hands control to the normal P2 G50 adopter.

No credential is placed in argv, Git, or workflow output.  Outlet / ProAV power
settings are never read-modify-written by this helper.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse

import g50_01_adopt as adopter

TAG = "OpenSSL_1_1_1w"
BUILD_ROOT = Path.home() / ".local" / "libexec" / "p2-home-os" / "openssl-1.1.1w"
SRC = BUILD_ROOT / "src"
PREFIX = BUILD_ROOT / "install"
OPENSSL = PREFIX / "bin" / "openssl"


class Forms(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self.cur: dict | None = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag.lower() == "form":
            self.cur = {"action": a.get("action", ""), "inputs": []}
            self.forms.append(self.cur)
        elif tag.lower() == "input" and self.cur is not None:
            self.cur["inputs"].append(a)
    def handle_endtag(self, tag):
        if tag.lower() == "form":
            self.cur = None


def log(s: str) -> None:
    print(s, flush=True)


def read_secret(path: Path) -> str | None:
    try:
        v = path.read_text().rstrip("\r\n")
        return v or None
    except Exception:
        pass
    try:
        p = subprocess.run(["sudo", "-n", "cat", str(path)], text=True,
                           capture_output=True, timeout=5)
        if p.returncode == 0:
            v = (p.stdout or "").rstrip("\r\n")
            return v or None
    except Exception:
        pass
    return None


def stage_secret() -> tuple[str, Path]:
    dest = adopter.TEMP_PASSWORD_FILE
    candidates = [dest]
    try:
        for d in Path("/home").iterdir():
            p = d / ".config" / "p2-home-os" / "g50-01-temp-password"
            if p not in candidates:
                candidates.append(p)
    except Exception:
        pass
    for source in candidates:
        try:
            exists = source.exists()
        except Exception:
            exists = False
        if not exists:
            continue
        secret = read_secret(source)
        if not secret:
            continue
        if source != dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(dest.parent, 0o700)
            tmp = dest.with_suffix(".tmp")
            tmp.write_text(secret)
            os.chmod(tmp, 0o600)
            tmp.replace(dest)
            os.chmod(dest, 0o600)
            log("temporary_password_source=alternate_local_account")
        else:
            log("temporary_password_source=runner_account")
        return secret, source
    raise RuntimeError("staged temporary password was not found/readable by the runner")


def authenticated_http_works(password: str) -> bool:
    if not adopter.port_open(adopter.HOST, 80):
        return False
    a = adopter.APC(adopter.HOST)
    try:
        a.login(adopter.ADMIN_USER, password)
        a.get("home.htm")
        return True
    except Exception:
        return False
    finally:
        try: a.logout()
        except Exception: pass


def ensure_legacy_openssl() -> None:
    if OPENSSL.exists():
        try:
            p = subprocess.run([str(OPENSSL), "version"], text=True,
                               capture_output=True, timeout=5)
            if p.returncode == 0 and "OpenSSL 1.1.1" in p.stdout:
                log("legacy_openssl=cache_ready")
                return
        except Exception:
            pass

    log("legacy_openssl=build_start")
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    if SRC.exists():
        shutil.rmtree(SRC)
    if PREFIX.exists():
        shutil.rmtree(PREFIX)

    subprocess.run([
        "git", "clone", "--quiet", "--depth", "1", "--branch", TAG,
        "https://github.com/openssl/openssl.git", str(SRC)
    ], check=True, timeout=120)

    subprocess.run([
        "./config", "no-shared", "no-tests", f"--prefix={PREFIX}",
        f"--openssldir={PREFIX / 'ssl'}"
    ], cwd=SRC, check=True, stdout=subprocess.DEVNULL,
       stderr=subprocess.STDOUT, timeout=90)

    jobs = max(1, min(4, os.cpu_count() or 2))
    subprocess.run(["make", f"-j{jobs}"], cwd=SRC, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                   timeout=360)
    subprocess.run(["make", "install_sw"], cwd=SRC, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                   timeout=120)
    if not OPENSSL.exists():
        raise RuntimeError("private OpenSSL build completed without openssl binary")
    p = subprocess.run([str(OPENSSL), "version"], text=True,
                       capture_output=True, timeout=5, check=True)
    if "OpenSSL 1.1.1" not in p.stdout:
        raise RuntimeError("unexpected private OpenSSL version")
    log("legacy_openssl=build_ready")


def raw_https(method: str, path: str, data: dict | None = None,
              timeout: int = 12) -> tuple[int | None, dict[str,str], str]:
    body = urlencode(data or {}) if data is not None else ""
    headers = [
        f"{method} {path} HTTP/1.1",
        f"Host: {adopter.HOST}",
        "User-Agent: p2-home-os-g50-legacy/1.0",
        "Connection: close",
    ]
    if data is not None:
        b = body.encode("ascii")
        headers += [
            "Content-Type: application/x-www-form-urlencoded",
            f"Content-Length: {len(b)}",
        ]
    req = "\r\n".join(headers) + "\r\n\r\n" + body
    cmd = [str(OPENSSL), "s_client", "-quiet", "-connect",
           f"{adopter.HOST}:443", "-tls1_1", "-cipher", "DES-CBC3-SHA"]
    try:
        p = subprocess.run(cmd, input=req, text=True, capture_output=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("latin-1", "replace")
        text = out
    else:
        text = p.stdout or ""
    # Never include stderr in errors/logs: OpenSSL diagnostics are irrelevant and
    # request bodies (credentials) are never echoed by this function.
    m = re.search(r"HTTP/\d(?:\.\d)?\s+(\d{3})", text)
    status = int(m.group(1)) if m else None
    head, sep, body_text = text.partition("\r\n\r\n")
    if not sep:
        head, sep, body_text = text.partition("\n\n")
    h: dict[str,str] = {}
    for line in head.splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            h[k.strip().lower()] = v.strip()
    return status, h, body_text


def login_legacy(password: str) -> str:
    status, headers, _ = raw_https("POST", "/Forms/login1", {
        "login_username": adopter.ADMIN_USER,
        "login_password": password,
        "submit": "Log On",
    })
    log(f"legacy_login_status={status if status is not None else 'none'}")
    if status != 303:
        raise RuntimeError("legacy HTTPS credential was not accepted")
    loc = headers.get("location", "")
    path = urlparse(loc).path
    m = re.match(r"(.*/NMC/[^/]+)/home\.htm$", path)
    if not m:
        raise RuntimeError("legacy login returned unexpected APC session path")
    log("legacy_login=session_acquired")
    return m.group(1)


def parse_forms(html: str) -> list[dict]:
    p = Forms()
    p.feed(html)
    return p.forms


def select_reboot(form_html: str) -> tuple[str,str] | None:
    low = form_html.lower()
    for m in re.finditer(r"<input\b[^>]*>", form_html, re.I | re.S):
        tag = m.group(0)
        ctx = low[max(0, m.start()-220):min(len(low), m.end()+260)]
        if "reboot" not in ctx or "management" not in ctx:
            continue
        nm = re.search(r"\bname=[\"']?([^\"'\s>]+)", tag, re.I)
        val = re.search(r"\bvalue=[\"']?([^\"'\s>]+)", tag, re.I)
        if nm and val:
            return nm.group(1), val.group(1)
    return None


def form_payload(form: dict) -> dict[str,str]:
    out: dict[str,str] = {}
    for inp in form.get("inputs", []):
        name = inp.get("name")
        if not name:
            continue
        typ = (inp.get("type") or "text").lower()
        value = inp.get("value", "")
        if typ == "hidden":
            out[name] = value
        elif typ in ("submit", "button"):
            if value.lower() in ("apply", "yes", "ok", "confirm") or name.lower() == "submit":
                out[name] = value or "Apply"
    if "submit" not in out:
        out["submit"] = "Apply"
    return out


def normalize_action(base: str, action: str, default_form: str) -> str:
    if not action:
        return base + "/Forms/" + default_form
    if action.startswith("http://") or action.startswith("https://"):
        return urlparse(action).path
    if action.startswith("/"):
        return action
    if action.startswith("Forms/"):
        return base + "/" + action
    return base + "/Forms/" + action


def switch_http_and_reboot(password: str) -> None:
    ensure_legacy_openssl()
    base = login_legacy(password)

    status, _, _ = raw_https("POST", base + "/Forms/webserv1", {
        "webModeEnableDisable": "HTTP",
        "HTTPPort": "80",
        "HTTPSPort": "443",
        "submit": "Apply",
    })
    log(f"http_mode_apply={status if status is not None else 'connection_dropped'}")

    # Keep using the authenticated HTTPS session token to execute the actual APC
    # management-interface reboot.  The reset page itself tells us the correct
    # field/value; this avoids hard-coding firmware-specific radio values.
    status, _, reset_html = raw_https("GET", base + "/genreset.htm")
    if status != 200:
        raise RuntimeError("could not read APC management reset page")
    reboot = select_reboot(reset_html)
    if not reboot:
        raise RuntimeError("could not identify Reboot Management Interface control")
    name, value = reboot
    log(f"management_reboot_control={name}")

    status, headers, confirm_html = raw_https("POST", base + "/Forms/genreset1", {
        name: value,
        "submit": "Apply",
    })
    log(f"management_reboot_stage1={status if status is not None else 'connection_dropped'}")

    # Some AOS releases redirect to the confirmation page; fetch it if needed.
    if status in (301, 302, 303, 307, 308) and headers.get("location"):
        cpath = urlparse(headers["location"]).path
        status, _, confirm_html = raw_https("GET", cpath)
        log(f"management_reboot_confirm_page={status if status is not None else 'none'}")

    forms = parse_forms(confirm_html)
    chosen = None
    for form in forms:
        action = (form.get("action") or "").lower()
        if "genreset" in action or "confirm" in confirm_html.lower():
            chosen = form
            break
    if not chosen and forms:
        chosen = forms[0]
    if chosen:
        action = normalize_action(base, chosen.get("action", ""), "genreset1")
        payload = form_payload(chosen)
        status, _, _ = raw_https("POST", action, payload, timeout=8)
        log(f"management_reboot_confirm={status if status is not None else 'connection_dropped'}")
    else:
        # A few releases accept the second identical Apply rather than presenting
        # a separately named form.
        status, _, _ = raw_https("POST", base + "/Forms/genreset1", {
            name: value, "submit": "Apply"
        }, timeout=8)
        log(f"management_reboot_confirm_fallback={status if status is not None else 'connection_dropped'}")

    deadline = time.time() + 150
    saw_down = False
    while time.time() < deadline:
        up80 = adopter.port_open(adopter.HOST, 80, timeout=1.0)
        up443 = adopter.port_open(adopter.HOST, 443, timeout=1.0)
        if not up80 and not up443:
            saw_down = True
        if up80 and authenticated_http_works(password):
            log(f"http_recovery=confirmed;saw_management_down={str(saw_down).lower()};https443={'open' if up443 else 'closed'}")
            return
        time.sleep(3)
    raise RuntimeError("APC management interface did not return with authenticated HTTP")


def cleanup_source(source: Path) -> None:
    if source == adopter.TEMP_PASSWORD_FILE:
        return
    try:
        source.unlink(missing_ok=True)
    except Exception:
        try:
            subprocess.run(["sudo", "-n", "rm", "-f", str(source)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
        except Exception:
            pass


def main() -> int:
    password, source = stage_secret()
    if authenticated_http_works(password):
        log("http_recovery=already_available")
    else:
        switch_http_and_reboot(password)

    # HTTP is now authenticated.  The original adopter's legacy-TLS escape step
    # is no longer needed; skip only that transport step, not any security or
    # verification work.
    adopter.recover_http = lambda _password: log("legacy_https_recovery=precompleted")
    rc = adopter.main()
    if rc == 0:
        cleanup_source(source)
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"G50_01_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise SystemExit(1)
