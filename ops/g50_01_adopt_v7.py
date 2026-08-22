#!/usr/bin/env python3
"""Enable 3DES in the private OpenSSL 1.1 build, then run G50 #1 adoption."""
from __future__ import annotations

import os
import shutil
import subprocess

import g50_01_adopt_v5 as v5
import g50_01_adopt_v6 as v6


def has_3des() -> bool:
    if not v5.OPENSSL.exists():
        return False
    try:
        p = subprocess.run([str(v5.OPENSSL), 'ciphers', 'DES-CBC3-SHA'],
                           text=True, capture_output=True, timeout=5)
        return p.returncode == 0 and 'DES-CBC3-SHA' in (p.stdout or '')
    except Exception:
        return False


def ensure_weak_openssl() -> None:
    if has_3des():
        v5.log('legacy_openssl=weak_cipher_cache_ready')
        return

    v5.log('legacy_openssl=weak_cipher_rebuild_start')
    v5.BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    if not v5.SRC.exists():
        subprocess.run([
            'git','clone','--quiet','--depth','1','--branch',v5.TAG,
            'https://github.com/openssl/openssl.git',str(v5.SRC)
        ], check=True, timeout=120)
    else:
        subprocess.run(['make','clean'], cwd=v5.SRC, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60)
    if v5.PREFIX.exists():
        shutil.rmtree(v5.PREFIX)

    subprocess.run([
        './config','no-shared','no-tests','enable-weak-ssl-ciphers',
        f'--prefix={v5.PREFIX}',f'--openssldir={v5.PREFIX / "ssl"}'
    ], cwd=v5.SRC, check=True, stdout=subprocess.DEVNULL,
       stderr=subprocess.STDOUT, timeout=90)
    jobs=max(1,min(4,os.cpu_count() or 2))
    subprocess.run(['make',f'-j{jobs}'], cwd=v5.SRC, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                   timeout=360)
    subprocess.run(['make','install_sw'], cwd=v5.SRC, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                   timeout=120)
    if not has_3des():
        raise RuntimeError('private OpenSSL rebuild still lacks DES-CBC3-SHA')
    v5.log('legacy_openssl=weak_cipher_rebuild_ready')


def main() -> int:
    v5.ensure_legacy_openssl = ensure_weak_openssl
    return v6.main()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'G50_01_ERROR={type(exc).__name__}:{exc}', file=__import__('sys').stderr)
        raise SystemExit(1)
