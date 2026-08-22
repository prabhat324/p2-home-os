#!/usr/bin/env python3
"""G50 #1 adopter with OpenSSL 1.1 security level lowered for TLS1.1/3DES."""
from __future__ import annotations

import re
import subprocess
from urllib.parse import urlencode

import g50_01_adopt_v5 as v5


def raw_https_sec0(method: str, path: str, data: dict | None = None,
                   timeout: int = 12):
    body = urlencode(data or {}) if data is not None else ""
    headers = [
        f"{method} {path} HTTP/1.1",
        f"Host: {v5.adopter.HOST}",
        "User-Agent: p2-home-os-g50-legacy/1.1",
        "Connection: close",
    ]
    if data is not None:
        b = body.encode("ascii")
        headers += [
            "Content-Type: application/x-www-form-urlencoded",
            f"Content-Length: {len(b)}",
        ]
    req = "\r\n".join(headers) + "\r\n\r\n" + body
    cmd = [str(v5.OPENSSL), "s_client", "-quiet", "-connect",
           f"{v5.adopter.HOST}:443", "-tls1_1", "-cipher",
           "DES-CBC3-SHA:@SECLEVEL=0"]
    try:
        p = subprocess.run(cmd, input=req, text=True, capture_output=True,
                           timeout=timeout)
        text = p.stdout or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("latin-1", "replace")
        text = out
    m = re.search(r"HTTP/\d(?:\.\d)?\s+(\d{3})", text)
    status = int(m.group(1)) if m else None
    head, sep, body_text = text.partition("\r\n\r\n")
    if not sep:
        head, sep, body_text = text.partition("\n\n")
    h = {}
    for line in head.splitlines()[1:]:
        if ":" in line:
            k, val = line.split(":", 1)
            h[k.strip().lower()] = val.strip()
    return status, h, body_text


def main() -> int:
    v5.raw_https = raw_https_sec0
    return v5.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"G50_01_ERROR={type(exc).__name__}:{exc}", file=__import__('sys').stderr)
        raise SystemExit(1)
