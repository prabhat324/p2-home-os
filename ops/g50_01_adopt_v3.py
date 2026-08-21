#!/usr/bin/env python3
"""Finish G50 #1 adoption, with FTP diagnostics for legacy-web recovery.

This wrapper never changes outlet/ProAV power settings. If authenticated HTTP
is not available and the local OpenSSL stack cannot negotiate the device's
obsolete HTTPS service, it retrieves config.ini over FTP using the staged
administrator credential. The configuration is stored only on core-01 and only
sanitized web/management settings are printed to the workflow log.
"""
from __future__ import annotations

import ftplib
import io
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import g50_01_adopt as adopter


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


def candidate_paths() -> list[Path]:
    paths = [adopter.TEMP_PASSWORD_FILE]
    try:
        for d in Path("/home").iterdir():
            if d.is_dir():
                p = d / ".config" / "p2-home-os" / "g50-01-temp-password"
                if p not in paths:
                    paths.append(p)
    except Exception:
        pass
    return paths


def stage_secret() -> tuple[str, Path]:
    dest = adopter.TEMP_PASSWORD_FILE
    source = None
    secret = None
    for candidate in candidate_paths():
        try:
            if not candidate.exists():
                continue
        except Exception:
            continue
        secret = read_secret(candidate)
        if secret:
            source = candidate
            break
    if not secret or source is None:
        raise RuntimeError("staged temporary password was not found/readable by the runner")
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
        try:
            a.logout()
        except Exception:
            pass


def management_reboot(password: str) -> None:
    print("stage=management_interface_reboot", flush=True)
    adopter.wait_unlocked(adopter.HOST, timeout=120)
    a = adopter.APC(adopter.HOST)
    a.login(adopter.ADMIN_USER, password)
    try:
        try:
            status, _, _ = a.post("genreset1", {
                "resetSelect": "Reboot",
                "submit": "Apply",
            }, timeout=4)
            if status not in (200, 303):
                raise RuntimeError(f"management reboot returned HTTP {status}")
        except (TimeoutError, socket.timeout, ConnectionError):
            pass
    finally:
        a.base = None

    deadline = time.time() + 120
    saw_down = False
    while time.time() < deadline:
        up = adopter.port_open(adopter.HOST, 80, timeout=1.0)
        if not up:
            saw_down = True
        if saw_down and up:
            break
        time.sleep(2)
    adopter.wait_unlocked(adopter.HOST, timeout=120)
    print("stage=management_interface_reboot_complete", flush=True)


def ftp_config_probe(password: str) -> Path:
    print("ftp_recovery=starting", flush=True)
    buf = io.BytesIO()
    ftp = ftplib.FTP(timeout=12)
    ftp.connect(adopter.HOST, 21)
    ftp.login(adopter.ADMIN_USER, password)
    ftp.retrbinary("RETR config.ini", buf.write)
    try:
        ftp.quit()
    except Exception:
        ftp.close()

    data = buf.getvalue()
    if not data:
        raise RuntimeError("FTP config.ini was empty")

    outdir = adopter.STATE_ROOT / "ftp-recovery"
    outdir.mkdir(parents=True, exist_ok=True)
    os.chmod(outdir, 0o700)
    path = outdir / "config-before-recovery.ini"
    path.write_bytes(data)
    os.chmod(path, 0o600)
    print(f"ftp_config_saved={path}", flush=True)

    text = data.decode("latin-1", errors="replace")
    interesting = re.compile(r"(web|http|https|ssl|ftp|telnet|ssh|console|snmp)", re.I)
    sensitive = re.compile(r"(pass|password|community|secret|auth|priv|key|phrase)", re.I)
    section = ""
    print("ftp_config_sanitized_begin", flush=True)
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            if interesting.search(section):
                print(section, flush=True)
            continue
        if not line or line.startswith(";"):
            continue
        if interesting.search(section) or interesting.search(line):
            if "=" in line:
                k, v = line.split("=", 1)
                if sensitive.search(k):
                    line = f"{k}=<redacted>"
            print(line[:240], flush=True)
    print("ftp_config_sanitized_end", flush=True)
    return path


def cleanup_original(source: Path) -> None:
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
    print("original_temporary_password_file_cleanup=attempted", flush=True)


def main() -> int:
    password, source = stage_secret()

    if authenticated_http_works(password):
        print("http_recovery=confirmed", flush=True)
        if adopter.port_open(adopter.HOST, 443):
            print("legacy_https_listener=still_open", flush=True)
            management_reboot(password)
            print("legacy_https_listener_after_reboot=" +
                  ("open" if adopter.port_open(adopter.HOST, 443) else "closed"), flush=True)
    else:
        print("http_recovery=not_confirmed", flush=True)
        ftp_config_probe(password)
        print("G50_01_FTP_PROBE_OK", flush=True)
        return 3

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
