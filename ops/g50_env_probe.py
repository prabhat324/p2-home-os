#!/usr/bin/env python3
from __future__ import annotations
import shutil, subprocess

names = ['docker','podman','gcc','cc','make','perl','git','wget','gnutls-cli','openssl']
for name in names:
    print(f'which_{name}={shutil.which(name) or "missing"}')

checks = [
    ['docker','version','--format','client={{.Client.Version}} server={{.Server.Version}}'],
    ['sudo','-n','docker','version','--format','client={{.Client.Version}} server={{.Server.Version}}'],
    ['docker','run','--rm','curlimages/curl:7.78.0','--version'],
    ['sudo','-n','docker','run','--rm','curlimages/curl:7.78.0','--version'],
]
for cmd in checks:
    label = '_'.join(x.replace('/','_') for x in cmd[:3])
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        out = ((p.stdout or '') + (p.stderr or '')).strip().replace('\n',' | ')
        print(f'{label}_rc={p.returncode}')
        print(f'{label}_out={out[:500]}')
    except Exception as exc:
        print(f'{label}_error={type(exc).__name__}')

for cmd in [['gcc','--version'],['make','--version'],['perl','-v']]:
    try:
        p=subprocess.run(cmd,text=True,capture_output=True,timeout=10)
        first=((p.stdout or '')+(p.stderr or '')).splitlines()[:2]
        print(f'{cmd[0]}_rc={p.returncode}; {" | ".join(first)}')
    except Exception as exc:
        print(f'{cmd[0]}_error={type(exc).__name__}')
