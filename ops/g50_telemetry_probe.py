#!/usr/bin/env python3
"""Read-only APC G50 telemetry discovery using the protected core-01 credential store.

The probe performs GET requests only. It never prints credentials, SNMP secrets,
form values, cookies, or full HTML. Output is limited to page names and sanitized
rows that contain electrical telemetry terms.
"""
from __future__ import annotations

import html as html_lib
import re
import sys
from urllib.parse import urlparse

import g50_manager_v3 as g

DEVICES = (
    ("p2-g50-01", "192.168.0.236"),
    ("p2-g50-02", "192.168.0.240"),
)

TERMS = re.compile(r"\b(?:watt(?:s)?|power|amp(?:s|ere|eres)?|current|volt(?:s|age)?|load|energy|kwh|hz|frequency|output)\b", re.I)
UNIT = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?\s*(?:k?W|Watt(?:s)?|A|Amp(?:s|ere|eres)?|V|Volt(?:s)?|Hz|kWh|%)\b", re.I)
HREF = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
ROW = re.compile(r"<(?:tr|div|p|li)\b[^>]*>(.*?)</(?:tr|div|p|li)>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
DROP = re.compile(r"<(?:script|style|input|textarea|select|option)\b.*?</(?:script|style|textarea|select|option)>|<input\b[^>]*>", re.I | re.S)

LIKELY = [
    "home.htm", "status.htm", "device.htm", "load.htm", "power.htm",
    "outlets.htm", "outletstat.htm", "devstat.htm", "proav.htm",
    "proavstat.htm", "measure.htm", "meter.htm", "environment.htm",
]


def clean(fragment: str) -> str:
    fragment = DROP.sub(" ", fragment)
    fragment = TAG.sub(" ", fragment)
    fragment = html_lib.unescape(fragment)
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return fragment[:500]


def safe_page_name(href: str) -> str | None:
    parsed = urlparse(href)
    path = parsed.path
    if not path or path.startswith("/"):
        path = path.rsplit("/", 1)[-1]
    else:
        path = path.rsplit("/", 1)[-1]
    if not path.lower().endswith((".htm", ".html")):
        return None
    if any(x in path.lower() for x in ("logout", "login")):
        return None
    return path + (("?" + parsed.query) if parsed.query else "")


def candidates(home: str) -> list[str]:
    out: list[str] = []
    seen = set()
    for page in LIKELY:
        if page not in seen:
            seen.add(page); out.append(page)
    for href in HREF.findall(home):
        page = safe_page_name(href)
        if page and page not in seen:
            seen.add(page); out.append(page)
    return out[:80]


def emit_hits(device: str, page: str, body: str) -> int:
    hits = []
    for fragment in ROW.findall(body):
        text = clean(fragment)
        if text and TERMS.search(text) and (UNIT.search(text) or re.search(r"\d", text)):
            if text not in hits:
                hits.append(text)
    if not hits:
        # Some old APC pages are table-light. Use bounded text windows only when
        # they include both an electrical keyword and a numeric unit.
        text = clean(body)
        for m in UNIT.finditer(text):
            lo = max(0, m.start() - 90); hi = min(len(text), m.end() + 90)
            window = text[lo:hi].strip()
            if TERMS.search(window) and window not in hits:
                hits.append(window)
    for row in hits[:20]:
        # Never print long opaque tokens even if a page happens to place one
        # next to a telemetry label.
        row = re.sub(r"\b[A-Za-z0-9+/=_-]{32,}\b", "[redacted-token]", row)
        print(f"G50_TELEMETRY device={device} page={page} row={row}")
    return len(hits)


def probe(device: str, host: str) -> None:
    store = g.load_store()
    entry = store.get(device)
    if not entry:
        print(f"G50_PROBE device={device} host={host} state=no-managed-secret")
        return
    try:
        g.wait_unlocked(host, timeout=25)
        apc, _, _, label = g.login_detect(host, entry, wait=False)
    except Exception as exc:
        print(f"G50_PROBE device={device} host={host} state=login-unavailable error={type(exc).__name__}")
        return
    total = 0
    visited = 0
    try:
        home = apc.get("home.htm")
        for page in candidates(home):
            try:
                body = home if page == "home.htm" else apc.get(page)
            except Exception:
                continue
            visited += 1
            total += emit_hits(device, page, body)
    finally:
        apc.logout()
    print(f"G50_PROBE device={device} host={host} credential_state={label} pages={visited} telemetry_rows={total}")


def main() -> int:
    for device, host in DEVICES:
        probe(device, host)
    return 0


if __name__ == "__main__":
    sys.exit(main())
