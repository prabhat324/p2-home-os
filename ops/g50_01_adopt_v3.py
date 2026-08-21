#!/usr/bin/env python3
"""Finish G50 #1 adoption after the one-time HTTPS->HTTP recovery.

This wrapper is intentionally conservative: it never changes outlet/ProAV power
settings. If authenticated HTTP already works but the legacy HTTPS listener is
still present, it reboots only the APC management interface so the protocol
change takes effect, then hands control to the existing safe adopter.
"""
from __future__ import annotations

import os
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
    oldbase = a.base
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

    # Management card only: wait for HTTP to disappear/reappear. Outlet power is
    # controlled independently and is not altered by this action.
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
        print("http_recovery=not_confirmed_falling_back", flush=True)

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
