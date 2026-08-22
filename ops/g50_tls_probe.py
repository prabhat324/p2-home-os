#!/usr/bin/env python3
from __future__ import annotations
import subprocess
from pathlib import Path

openssl = Path.home()/'.local/libexec/p2-home-os/openssl-1.1.1w/install/bin/openssl'
cmd = [str(openssl),'s_client','-connect','192.168.0.236:443','-tls1_1','-cipher','DES-CBC3-SHA:@SECLEVEL=0','-brief']
try:
    p = subprocess.run(cmd,input='',text=True,capture_output=True,timeout=8)
    print(f'rc={p.returncode}')
    lines=((p.stderr or '')+'\n'+(p.stdout or '')).splitlines()
    for line in lines[:30]:
        # No credentials/request body are used by this probe.
        print(line[:300])
except subprocess.TimeoutExpired as exc:
    print('timeout=true')
    out=(exc.stderr or '')
    if isinstance(out,bytes): out=out.decode('utf-8','replace')
    for line in out.splitlines()[:30]: print(line[:300])
