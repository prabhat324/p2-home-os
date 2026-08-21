#!/usr/bin/env python3
"""Locate the locally staged G50 #1 credential and run the safe adopter.

This exists because the interactive shell account used to stage the temporary
password may differ from the self-hosted GitHub runner account. The password is
never printed, passed on argv, or committed to Git.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import g50_01_adopt as adopter


def read_secret(path: Path) -> str | None:
    try:
        value = path.read_text().rstrip("\r\n")
        return value or None
    except Exception:
        pass
    # If the staging file belongs to the interactive admin account and the
    # runner has an approved passwordless sudo path, read it without exposing it.
    try:
        p = subprocess.run(
            ["sudo", "-n", "cat", str(path)],
            text=True,
            capture_output=True,
            timeout=5,
        )
        if p.returncode == 0:
            value = (p.stdout or "").rstrip("\r\n")
            return value or None
    except Exception:
        pass
    return None


def candidate_paths() -> list[Path]:
    paths = [adopter.TEMP_PASSWORD_FILE]
    home_root = Path("/home")
    try:
        for d in home_root.iterdir():
            if d.is_dir():
                p = d / ".config" / "p2-home-os" / "g50-01-temp-password"
                if p not in paths:
                    paths.append(p)
    except Exception:
        pass
    return paths


def main() -> int:
    dest = adopter.TEMP_PASSWORD_FILE
    source = None
    secret = None
    for candidate in candidate_paths():
        try:
            exists = candidate.exists()
        except Exception:
            exists = False
        if not exists:
            continue
        secret = read_secret(candidate)
        if secret:
            source = candidate
            break

    if not secret or source is None:
        print("G50_01_ERROR=staged temporary password was not found/readable by the runner", file=sys.stderr)
        return 1

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

    rc = adopter.main()

    # adopter.main removes the runner-side staging file only after successful
    # verification. Also clean the original staging file when possible.
    if rc == 0 and source != dest:
        try:
            source.unlink(missing_ok=True)
        except Exception:
            try:
                subprocess.run(["sudo", "-n", "rm", "-f", str(source)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5, check=False)
            except Exception:
                pass
        print("original_temporary_password_file_cleanup=attempted", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
