#!/usr/bin/env python3
"""Automated legacy-TLS recovery and P2 adoption for APC G50 #1.

The G50 runs AOS 5.1.x and only negotiates obsolete TLS 1.1/3DES. core-01's
host OpenSSL cannot use that cipher suite, so this wrapper uses an older,
containerized curl *only for the one-time HTTPS recovery*. Credentials are
passed on stdin, never argv or Git. It then switches to HTTP, performs the
management-interface reboot including APC's confirmation step, and hands off
to the normal safe adopter. Outlet/ProAV power settings are never changed.
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

IMAGES = ["curlimages/curl:7.78.0", "curlimages/curl:7.81.0", "curlimages/curl:7.86.0"]


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "form":
            self.current = {"action": attrs.get("action", ""), "inputs": []}
            self.forms.append(self.current)
        elif tag.lower() == "input" and self.current is not None:
            self.current["inputs"].append(attrs)
    def handle_endtag(self, tag):
        if tag.lower() == "form":
            self.current = None


def read_secret(path: Path) -> str | None:
    try:
        value = path.read_text().rstrip("\r\n")
        return value or None
    except Exception:
        pass
    try:
        p = subprocess.run(["sudo", "-n", "cat", str(path)], text=True,
                           capture_output=True, timeout=5)
        if p.returncode == 0:
            value = (p.stdout or "").rstrip("\r\n")
            return value or None
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
            if not source.exists():
                continue
        except Exception:
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
            print("temporary_password_source=alternate_local_account", flush=True)
        else:
            print("temporary_password_source=runner_account", flush=True)
        return secret, source
    raise RuntimeError("staged temporary password was not found/readable by the runner")


def authenticated_http_works(password: str) -> bool:
    if not adopter.port_open(adopter.HOST, 80):
        return False
    a = adopter.APC(adopter.HOST)
    try:
        a.login(adopter.ADMIN_USER, password)
        web = a.get("webserv.htm")
        return adopter.checked(web, "webModeEnableDisable", "HTTP")
    except Exception:
        return False
    finally:
        try: a.logout()
        except Exception: pass


def runtime_candidates():
    out = []
    if shutil.which("docker"):
        out.append(["docker"])
        out.append(["sudo", "-n", "docker"])
    if shutil.which("podman"):
        out.append(["podman"])
    return out


def legacy_request(url: str, data: dict | None = None, timeout: int = 18):
    """Return (status, headers+body text) using old curl in a local container."""
    body = urlencode(data or {}) if data is not None else None
    for runtime in runtime_candidates():
        for image in IMAGES:
            cmd = [*runtime, "run", "--rm", "--network", "host", "-i", image,
                   "curl", "-sS", "-k", "--connect-timeout", "5", "--max-time", str(timeout),
                   "--tls-max", "1.1", "--ciphers", "DES-CBC3-SHA:@SECLEVEL=0",
                   "-D", "-", "-o", "-", "-w", "\nP2_HTTP_CODE=%{http_code}\n"]
            if body is not None:
                cmd += ["-H", "Content-Type: application/x-www-form-urlencoded", "--data-binary", "@-"]
            cmd.append(url)
            try:
                p = subprocess.run(cmd, input=body, text=True, capture_output=True,
                                   timeout=timeout + 90)
            except Exception:
                continue
            text = (p.stdout or "") + (p.stderr or "")
            m = re.search(r"P2_HTTP_CODE=(\d{3})", text)
            if m and int(m.group(1)) != 0:
                print(f"legacy_transport={runtime[-1]}:{image}", flush=True)
                return int(m.group(1)), text
    return None, ""


def location_from(text: str) -> str | None:
    for line in text.splitlines():
        m = re.match(r"Location:\s*(\S+)", line.strip(), re.I)
        if m:
            return m.group(1).strip()
    return None


def html_part(text: str) -> str:
    # Good enough for APC pages: return from first doctype/html tag onward, excluding marker.
    text = re.sub(r"\nP2_HTTP_CODE=\d{3}\s*$", "", text, flags=re.S)
    starts = [x for x in (text.lower().find("<!doctype"), text.lower().find("<html")) if x >= 0]
    return text[min(starts):] if starts else text


def parse_forms(text: str):
    p = FormParser()
    p.feed(html_part(text))
    return p.forms


def choose_reboot_input(page: str):
    """Find the radio/select input whose nearby source text refers to reboot management."""
    low = page.lower()
    for m in re.finditer(r"<input\b[^>]*>", page, re.I | re.S):
        tag = m.group(0)
        ctx = low[max(0, m.start()-180):min(len(low), m.end()+240)]
        if "reboot" not in ctx or "management" not in ctx:
            continue
        name = re.search(r"\bname=[\"']?([^\"'\s>]+)", tag, re.I)
        value = re.search(r"\bvalue=[\"']?([^\"'\s>]+)", tag, re.I)
        if name and value:
            return name.group(1), value.group(1)
    return None


def confirmation_payload(text: str):
    forms = parse_forms(text)
    for form in forms:
        action = form.get("action", "")
        if "genreset" not in action.lower() and "confirm" not in html_part(text).lower():
            continue
        data = {}
        for inp in form["inputs"]:
            name = inp.get("name")
            if not name:
                continue
            typ = (inp.get("type") or "text").lower()
            value = inp.get("value", "")
            if typ == "hidden":
                data[name] = value
            elif typ in ("submit", "button") and (value.lower() in ("apply", "yes", "ok", "confirm") or name.lower() == "submit"):
                data[name] = value or "Apply"
        if data:
            if "submit" not in data:
                data["submit"] = "Apply"
            return action, data
    return None, None


def recover_legacy_https(password: str) -> bool:
    runtimes = runtime_candidates()
    print("legacy_container_runtime=" + (",".join(x[-1] for x in runtimes) if runtimes else "none"), flush=True)
    if not runtimes:
        return False

    code, _ = legacy_request(f"https://{adopter.HOST}/")
    if code is None:
        print("legacy_container_probe=failed", flush=True)
        return False
    print(f"legacy_container_probe=http_{code}", flush=True)

    code, text = legacy_request(
        f"https://{adopter.HOST}/Forms/login1",
        {"login_username": adopter.ADMIN_USER, "login_password": password, "submit": "Log On"},
    )
    if code != 303:
        print(f"legacy_container_login=http_{code if code else 'none'}", flush=True)
        return False
    loc = location_from(text)
    if not loc:
        print("legacy_container_login=no_location", flush=True)
        return False
    path = urlparse(loc).path
    m = re.match(r"(.*/NMC/[^/]+)/home\.htm$", path)
    if not m:
        print("legacy_container_login=unexpected_location", flush=True)
        return False
    base = m.group(1)
    print("legacy_container_login=session_acquired", flush=True)

    code, _ = legacy_request(
        f"https://{adopter.HOST}{base}/Forms/webserv1",
        {"webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"},
    )
    print(f"legacy_container_http_switch=http_{code if code else 'connection_dropped'}", flush=True)

    # APC reset/reboot is a two-step form. Read the actual page so we do not guess
    # the radio value, then submit its confirmation form as returned by the device.
    code, reset_page = legacy_request(f"https://{adopter.HOST}{base}/genreset.htm")
    if code == 200:
        reboot = choose_reboot_input(html_part(reset_page))
        if reboot:
            name, value = reboot
            print(f"management_reboot_field={name}", flush=True)
            code, confirm_page = legacy_request(
                f"https://{adopter.HOST}{base}/Forms/genreset1",
                {name: value, "submit": "Apply"},
            )
            print(f"management_reboot_stage1=http_{code if code else 'connection_dropped'}", flush=True)
            action, payload = confirmation_payload(confirm_page)
            if action and payload:
                if not action.startswith("/"):
                    action = f"{base}/Forms/{action}" if "/" not in action else f"{base}/{action}"
                elif not action.startswith(base):
                    # APC often returns an absolute session-relative form path already.
                    pass
                target = f"https://{adopter.HOST}{action}"
                code, _ = legacy_request(target, payload, timeout=10)
                print(f"management_reboot_confirm=http_{code if code else 'connection_dropped'}", flush=True)
        else:
            print("management_reboot_field=not_found", flush=True)
    else:
        print(f"management_reboot_page=http_{code if code else 'none'}", flush=True)

    # Wait for a management restart or for HTTP authenticated mode to become usable.
    deadline = time.time() + 120
    saw_down = False
    while time.time() < deadline:
        up = adopter.port_open(adopter.HOST, 80, timeout=1.0)
        if not up:
            saw_down = True
        if up and authenticated_http_works(password):
            print(f"legacy_http_recovery=confirmed;saw_management_down={str(saw_down).lower()}", flush=True)
            return True
        time.sleep(3)
    print(f"legacy_http_recovery=not_confirmed;saw_management_down={str(saw_down).lower()}", flush=True)
    return False


def cleanup_original(source: Path) -> None:
    if source == adopter.TEMP_PASSWORD_FILE:
        return
    try: source.unlink(missing_ok=True)
    except Exception:
        try:
            subprocess.run(["sudo", "-n", "rm", "-f", str(source)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
        except Exception: pass
    print("original_temporary_password_file_cleanup=attempted", flush=True)


def main() -> int:
    password, source = stage_secret()
    if authenticated_http_works(password):
        print("http_recovery=already_confirmed", flush=True)
    else:
        print("http_recovery=not_confirmed", flush=True)
        if not recover_legacy_https(password):
            raise RuntimeError("legacy HTTPS recovery could not be completed from core-01")

    rc = adopter.main()
    if rc == 0:
        cleanup_original(source)
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"G50_01_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise SystemExit(1)
