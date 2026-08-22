#!/usr/bin/env python3
"""Report G50 management-store/backups metadata without reading secret values."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

ROOTS = [Path.home()]
try:
    ROOTS += [p for p in Path('/home').iterdir() if p.is_dir() and p not in ROOTS]
except Exception:
    pass

print(f"G50_CONTEXT uid={os.getuid()} user={os.environ.get('USER','?')} home={Path.home()}")

for root in ROOTS:
    store = root / '.config' / 'p2-home-os' / 'g50-secrets.json'
    try:
        st = store.stat()
        mode = stat.S_IMODE(st.st_mode)
        print(f"G50_STORE path={store} exists=true uid={st.st_uid} mode={mode:04o} readable={os.access(store, os.R_OK)}")
    except FileNotFoundError:
        continue
    except PermissionError:
        print(f"G50_STORE path={store} exists=unknown permission=denied")

    state = root / '.local' / 'state' / 'p2-home-os' / 'g50'
    try:
        for device in sorted(state.iterdir()):
            if not device.is_dir():
                continue
            backups = device / 'backups'
            latest = None
            if backups.is_dir():
                dirs = sorted([p for p in backups.iterdir() if p.is_dir()])
                latest = dirs[-1] if dirs else None
            print(f"G50_BACKUP device={device.name} root={device} latest={latest or '-'}")
            if latest:
                names = sorted(p.name for p in latest.iterdir() if p.is_file())
                print(f"G50_BACKUP_FILES device={device.name} files={','.join(names[:80])}")
                for filename in ('home.htm','status.htm','device.htm','load.htm','power.htm','outlets.htm','outletstat.htm','devstat.htm','proav.htm','proavstat.htm','measure.htm','meter.htm'):
                    page = latest / filename
                    if not page.is_file() or not os.access(page, os.R_OK):
                        continue
                    try:
                        body = page.read_text(errors='replace')
                    except Exception:
                        continue
                    # Only show sanitized table-ish rows containing electrical terms.
                    for frag in re.findall(r'<(?:tr|div|p|li)\b[^>]*>(.*?)</(?:tr|div|p|li)>', body, re.I|re.S):
                        text = re.sub(r'<[^>]+>', ' ', frag)
                        text = re.sub(r'\s+', ' ', text).strip()
                        if re.search(r'\b(?:watt|power|amp|current|volt|load|energy|kwh|hz|output)\w*\b', text, re.I) and re.search(r'\d', text):
                            text = re.sub(r'\b[A-Za-z0-9+/=_-]{32,}\b', '[redacted-token]', text)[:400]
                            print(f"G50_BACKUP_TELEMETRY device={device.name} page={filename} row={text}")
    except (FileNotFoundError, PermissionError):
        pass
