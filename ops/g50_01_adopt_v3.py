#!/usr/bin/env python3
"""Finish G50 #1 adoption using legacy-tolerant local transports.

The APC management card uses obsolete TLS 1.1/3DES. Modern OpenSSL on core-01
cannot negotiate it, so this wrapper first tries GNU wget/GnuTLS locally. If
that works it logs in without putting the password on argv, switches management
to HTTP, then hands off to the normal safe adopter. FTP is retained only as a
read-only diagnostic fallback. Outlet/ProAV power settings are never changed.
"""
from __future__ import annotations

import ftplib
import io
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

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
        try: a.logout()
        except Exception: pass


def wget_request(url: str, data: dict | None = None, timeout: int = 12) -> tuple[int | None, str]:
    """Use wget/GnuTLS with legacy variants; secrets go through a mode-0600 file."""
    variants = [
        ["--secure-protocol=TLSv1_1", "--ciphers=NORMAL:+3DES-CBC:+RSA"],
        ["--secure-protocol=TLSv1_1", "--ciphers=NORMAL:+3DES-CBC"],
        ["--secure-protocol=TLSv1_1"],
        ["--secure-protocol=auto", "--ciphers=NORMAL:+3DES-CBC:+RSA"],
    ]
    post_path = None
    try:
        if data is not None:
            adopter.STATE_ROOT.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix="legacy-post-", dir=str(adopter.STATE_ROOT))
            post_path = Path(name)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(urlencode(data))
        last = ""
        for extra in variants:
            cmd = ["wget", "--no-check-certificate", "--server-response", "--max-redirect=0",
                   "--timeout", str(timeout), "-O", "/dev/null", *extra]
            if post_path:
                cmd += ["--header=Content-Type: application/x-www-form-urlencoded",
                        f"--post-file={post_path}"]
            cmd.append(url)
            p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 5)
            text = (p.stderr or "") + (p.stdout or "")
            last = text
            m = re.search(r"HTTP/\S+\s+(\d{3})", text)
            if m:
                return int(m.group(1)), text
        return None, last
    finally:
        if post_path:
            try: post_path.unlink(missing_ok=True)
            except Exception: pass


def recover_http_with_wget(password: str) -> bool:
    code, text = wget_request(f"https://{adopter.HOST}/")
    if code is None:
        print("legacy_wget_probe=failed", flush=True)
        return False
    print(f"legacy_wget_probe=http_{code}", flush=True)

    code, text = wget_request(
        f"https://{adopter.HOST}/Forms/login1",
        {"login_username": adopter.ADMIN_USER, "login_password": password, "submit": "Log On"},
    )
    if code != 303:
        print(f"legacy_wget_login=http_{code if code is not None else 'none'}", flush=True)
        return False
    loc = None
    for line in text.splitlines():
        m = re.search(r"Location:\s*(\S+)", line, re.I)
        if m:
            loc = m.group(1).strip()
            break
    if not loc:
        print("legacy_wget_login=no_location", flush=True)
        return False
    path = urlparse(loc).path
    m = re.match(r"(.*/NMC/[^/]+)/home\.htm$", path)
    if not m:
        print("legacy_wget_login=unexpected_location", flush=True)
        return False
    base = m.group(1)
    print("legacy_wget_login=session_acquired", flush=True)

    code, _ = wget_request(
        f"https://{adopter.HOST}{base}/Forms/webserv1",
        {"webModeEnableDisable": "HTTP", "HTTPPort": "80", "HTTPSPort": "443", "submit": "Apply"},
    )
    print(f"legacy_wget_http_switch=http_{code if code is not None else 'connection_dropped'}", flush=True)

    # Release the single-session lock if the device is already accepting HTTP.
    try:
        a = adopter.APC(adopter.HOST)
        status, _, _ = a.req("GET", base + "/logout.htm", timeout=3)
        print(f"legacy_wget_logout=http_{status}", flush=True)
    except Exception:
        pass

    deadline = time.time() + 45
    while time.time() < deadline:
        if authenticated_http_works(password):
            print("legacy_wget_http_recovery=confirmed", flush=True)
            return True
        time.sleep(3)
    print("legacy_wget_http_recovery=not_confirmed", flush=True)
    return False


def ftp_config_probe(password: str) -> Path:
    print("ftp_recovery=starting", flush=True)
    buf = io.BytesIO()
    ftp = ftplib.FTP(timeout=12)
    ftp.connect(adopter.HOST, 21)
    ftp.login(adopter.ADMIN_USER, password)
    ftp.retrbinary("RETR config.ini", buf.write)
    try: ftp.quit()
    except Exception: ftp.close()
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
    return path


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
        print("http_recovery=confirmed", flush=True)
    else:
        print("http_recovery=not_confirmed", flush=True)
        if not recover_http_with_wget(password):
            # Read-only diagnostic only; never modify config.ini over FTP here.
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
