#!/usr/bin/env python3
"""Copy a project to an explicitly configured separate mounted filesystem and verify hashes."""
import argparse,os,shutil
from pathlib import Path
from runtime import fingerprint,atomic,stamp
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
if not a.destination.is_dir():raise SystemExit('Backup destination must already exist')
if a.destination.stat().st_dev==a.source.stat().st_dev:raise SystemExit('Backup must be on a separate mounted filesystem')
files=[x for x in a.source.rglob('*') if x.is_file()]
if shutil.disk_usage(a.destination).free<sum(x.stat().st_size for x in files)+1024**3:raise SystemExit('Insufficient backup capacity')
manifest=[]
for src in files:
 target=a.destination/a.source.name/src.relative_to(a.source);target.parent.mkdir(parents=True,exist_ok=True)
 partial=target.with_name(target.name+'.partial');shutil.copy2(src,partial)
 digest=fingerprint(src)
 if fingerprint(partial)!=digest:raise RuntimeError('Backup checksum mismatch')
 partial.replace(target);manifest.append({'file':str(target),'sha256':digest})
atomic(a.destination/a.source.name/'backup-verification.json',{'at':stamp(),'files':manifest})
