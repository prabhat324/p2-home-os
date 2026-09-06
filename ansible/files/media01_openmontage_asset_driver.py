#!/usr/bin/env python3
"""Generate sandboxed BeSquare visual assets with OpenMontage in asset-only mode.

This driver can create standalone PNG/MOV visual elements and an OpenMontage
VideoCompose preview. It never reads or writes the production timeline/master.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path('/srv/media-production')
OM_REPO = Path('/home/p2ops/openmontage-lab/OpenMontage')
OM_PYTHON = OM_REPO / '.venv/bin/python'
JOB_RE = re.compile(r'^[A-Za-z0-9._-]{1,80}$')
ALLOWED_KINDS = {
    'title_card', 'stat_card', 'source_card', 'chart', 'diagram',
    'lower_third', 'transition', 'callout', 'quote_card'
}


def run(cmd, *, cwd=None, capture=False):
    p = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    if p.returncode:
        if capture:
            print((p.stdout or '')[-4000:], file=sys.stderr)
            print((p.stderr or '')[-4000:], file=sys.stderr)
        raise RuntimeError(f'command failed ({p.returncode}): {cmd[0]}')
    return p


def ensure_pillow():
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        run([str(OM_PYTHON), '-m', 'pip', 'install', '--quiet', 'Pillow'])


def font_path(bold=False):
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    raise RuntimeError('No supported system font found')


def fit_font(draw, text, width, start, floor, bold=False):
    from PIL import ImageFont
    path = font_path(bold)
    for size in range(start, floor - 1, -2):
        f = ImageFont.truetype(path, size)
        if draw.textbbox((0, 0), text, font=f)[2] <= width:
            return f
    return ImageFont.truetype(path, floor)


def make_asset(req, png_path):
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1920, 1080
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bold = font_path(True)
    regular = font_path(False)

    kind = req['kind']
    title = str(req.get('title') or req.get('headline') or '').strip()
    value = str(req.get('value') or '').strip()
    subtitle = str(req.get('subtitle') or req.get('body') or '').strip()
    source_label = str(req.get('source_label') or '').strip()
    side = str(req.get('side') or 'right').lower()
    width = int(req.get('width') or (920 if kind == 'chart' else 840))
    width = max(560, min(width, 1120))
    height = int(req.get('height') or (500 if kind == 'chart' else 320))
    height = max(220, min(height, 650))
    x = 72 if side == 'left' else W - width - 72
    y = int(req.get('y') or 92)
    y = max(40, min(y, H - height - 80))

    # V6.1-derived restrained panel language: navy, cyan structure, yellow key value.
    d.rounded_rectangle((x + 12, y + 16, x + width + 12, y + height + 16), radius=32, fill=(0, 0, 0, 90))
    d.rounded_rectangle((x, y, x + width, y + height), radius=32,
                        fill=(10, 21, 38, 238), outline=(72, 214, 224, 235), width=3)
    d.rectangle((x, y, x + 10, y + height), fill=(72, 214, 224, 255))

    eyebrow = str(req.get('eyebrow') or kind.replace('_', ' ')).upper()
    d.text((x + 42, y + 28), eyebrow, font=ImageFont.truetype(bold, 22), fill=(99, 230, 238, 255))

    if title:
        tf = fit_font(d, title, width - 84, 44, 27, bold=True)
        d.text((x + 42, y + 73), title, font=tf, fill=(248, 250, 252, 255))

    cursor = y + 140
    if value:
        vf = fit_font(d, value, width - 84, 64, 36, bold=True)
        d.text((x + 42, cursor), value, font=vf, fill=(250, 204, 21, 255))
        cursor += 82

    bars = req.get('bars') or req.get('data')
    if kind == 'chart' and isinstance(bars, list) and bars:
        pairs = []
        for item in bars[:6]:
            if isinstance(item, dict):
                label = str(item.get('label') or item.get('name') or '')
                try: val = float(item.get('value'))
                except Exception: continue
                pairs.append((label, val))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                try: pairs.append((str(item[0]), float(item[1])))
                except Exception: pass
        if pairs:
            maxv = max(abs(v) for _, v in pairs) or 1.0
            label_w = 250
            bx = x + 42 + label_w
            max_bw = width - label_w - 155
            by = max(cursor, y + 158)
            for label, val in pairs:
                d.text((x + 42, by + 4), label, font=ImageFont.truetype(regular, 22), fill=(226, 232, 240, 255))
                bw = max(5, int(max_bw * abs(val) / maxv))
                d.rounded_rectangle((bx, by, bx + bw, by + 30), radius=11, fill=(72, 214, 224, 230))
                d.text((min(bx + bw + 10, x + width - 110), by + 1), f'{val:g}',
                       font=ImageFont.truetype(bold, 20), fill=(250, 204, 21, 255))
                by += 55
            cursor = by + 3

    if subtitle:
        lines = textwrap.wrap(subtitle, width=52)
        d.multiline_text((x + 42, min(cursor, y + height - 92)), '\n'.join(lines[:3]),
                         font=ImageFont.truetype(regular, 23), fill=(203, 213, 225, 255), spacing=5)

    if source_label:
        d.text((x + 42, y + height - 42), f'Source: {source_label}',
               font=ImageFont.truetype(regular, 16), fill=(148, 163, 184, 245))
    d.text((x + width - 205, y + height - 42), 'BeSquare by pSquare',
           font=ImageFont.truetype(bold, 15), fill=(148, 163, 184, 235))

    img.save(png_path)


def make_alpha_motion(png, mov, duration, side):
    # Standalone alpha animation. The main editor decides if/how to place it.
    direction = 1 if side == 'right' else -1
    dx = 70 * direction
    fade = min(0.4, max(0.2, duration / 8.0))
    x = f"if(lt(t,{fade:.3f}),{dx}-{dx}*t/{fade:.3f},if(gt(t,{duration-fade:.3f}),{dx}*(t-{duration-fade:.3f})/{fade:.3f},0))"
    fc = (
        f"color=c=black@0.0:s=1920x1080:r=30:d={duration:.3f},format=rgba[base];"
        f"movie={str(png).replace(':', r'\:')},format=rgba[ov];"
        f"[base][ov]overlay=x='{x}':y=0:format=auto,format=yuva444p10le[out]"
    )
    # ProRes 4444 is broadly useful in DaVinci and preserves alpha.
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-filter_complex', fc,
        '-map', '[out]', '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le',
        '-an', str(mov)
    ])


def openmontage_preview(png, preview, duration):
    base = preview.with_name(preview.stem + '-base.mp4')
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
        '-i', f'color=c=0x172033:s=1920x1080:r=30:d={duration:.3f}',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(base)
    ])
    sys.path.insert(0, str(OM_REPO))
    os.chdir(OM_REPO)
    from tools.video.video_compose import VideoCompose
    result = VideoCompose().execute({
        'operation': 'overlay',
        'input_path': str(base),
        'output_path': str(preview),
        'overlays': [{
            'asset_path': str(png), 'x': 0, 'y': 0,
            'start_seconds': 0, 'end_seconds': duration
        }],
        'codec': 'libx264', 'crf': 24,
    })
    base.unlink(missing_ok=True)
    if not result.success or not preview.exists():
        raise RuntimeError(f'OpenMontage VideoCompose preview failed: {result.error}')
    return {'success': True, 'data': result.data, 'error': result.error}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', required=True)
    ap.add_argument('--standard', type=Path, required=True)
    args = ap.parse_args()
    if not JOB_RE.fullmatch(args.job):
        raise SystemExit('invalid job name')
    standard = json.loads(args.standard.read_text(encoding='utf-8'))
    if standard.get('openmontage', {}).get('production_role') != 'asset_only':
        raise RuntimeError('BeSquare standard does not authorize OpenMontage asset-only mode')

    job_dir = ROOT / 'inbox' / args.job
    req_path = job_dir / standard['openmontage'].get('request_filename', 'openmontage-assets.json')
    if not req_path.is_file():
        raise RuntimeError(f'asset request file missing: {req_path}')
    request = json.loads(req_path.read_text(encoding='utf-8'))
    if request.get('ready') is not True or request.get('purpose') != 'asset_only':
        raise RuntimeError('OpenMontage request must have ready=true and purpose=asset_only')
    requests = request.get('requests')
    if not isinstance(requests, list) or not requests or len(requests) > 20:
        raise RuntimeError('OpenMontage asset request requires 1-20 requests')

    if not OM_PYTHON.exists() or not OM_REPO.exists():
        raise RuntimeError('official OpenMontage installation is missing')
    remote = subprocess.check_output(['git', '-C', str(OM_REPO), 'remote', 'get-url', 'origin'], text=True).strip()
    if remote != 'https://github.com/calesthio/OpenMontage.git':
        raise RuntimeError(f'unexpected OpenMontage remote: {remote}')

    ensure_pillow()
    work = ROOT / 'work' / args.job / 'openmontage-assets'
    review = ROOT / 'review' / args.job / 'openmontage-assets'
    work.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)

    results = []
    seen = set()
    for i, req in enumerate(requests):
        if not isinstance(req, dict):
            raise RuntimeError(f'asset request {i} is not an object')
        asset_id = str(req.get('id') or f'asset-{i+1:02d}')
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', asset_id) or asset_id in seen:
            raise RuntimeError(f'invalid/duplicate asset id: {asset_id}')
        seen.add(asset_id)
        kind = str(req.get('kind') or '').lower()
        if kind not in ALLOWED_KINDS:
            raise RuntimeError(f'unsupported asset kind {kind}; allowed={sorted(ALLOWED_KINDS)}')
        if kind in {'stat_card', 'source_card', 'chart'} and not req.get('source_label'):
            raise RuntimeError(f'{asset_id}: factual asset kind {kind} requires source_label')
        duration = float(req.get('duration_seconds') or 5.0)
        if not 1.0 <= duration <= 12.0:
            raise RuntimeError(f'{asset_id}: duration must be 1-12 seconds')
        side = str(req.get('side') or 'right').lower()
        if side not in {'left', 'right'}:
            raise RuntimeError(f'{asset_id}: side must be left or right')

        adir = work / asset_id
        adir.mkdir(parents=True, exist_ok=True)
        png = adir / f'{asset_id}.png'
        mov = adir / f'{asset_id}-alpha.mov'
        preview = review / f'{asset_id}-openmontage-preview.mp4'
        make_asset(req, png)
        make_alpha_motion(png, mov, duration, side)
        om = openmontage_preview(png, preview, min(duration, 6.0))
        results.append({
            'id': asset_id, 'kind': kind, 'png': str(png), 'alpha_mov': str(mov),
            'openmontage_preview': str(preview), 'source_label': req.get('source_label'),
            'duration_seconds': duration, 'openmontage_video_compose': om,
            'production_insertion': 'NOT_AUTOMATIC_REVIEW_AND_INSERT_WITH_MAIN_EDITOR'
        })

    report = {
        'status': 'complete',
        'purpose': 'asset_only',
        'job': args.job,
        'standard_id': standard.get('standard_id'),
        'openmontage_remote': remote,
        'generated_at_epoch': time.time(),
        'asset_count': len(results),
        'assets': results,
        'guardrail': 'No production master/timeline was read, rendered, overwritten, or modified.'
    }
    report_path = review / 'openmontage-assets.report.json'
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))


if __name__ == '__main__':
    main()
