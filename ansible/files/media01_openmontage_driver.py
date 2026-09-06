#!/usr/bin/env python3
"""Run the isolated OpenMontage Wasaga 18-minute comparison pass on media-01.

This script intentionally keeps the source read-only. It uses the pinned official
OpenMontage checkout for local video-understanding and a direct video_compose
smoke test, then performs the delivery encode with NVIDIA NVENC because the
current OpenMontage overlay helper emits libx264-style CRF arguments that are
not appropriate for NVENC.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

OM_REPO = Path('/home/p2ops/openmontage-lab/OpenMontage')
OM_PYTHON = OM_REPO / '.venv/bin/python'
SOURCE = Path('/srv/media-production/work/openmontage-besquare-demo-01/input/master.mp4')
PROJECT = Path('/srv/media-production/work/openmontage-besquare-demo-01')
ANALYSIS = PROJECT / 'analysis'
ASSETS = PROJECT / 'assets'
OUTPUT = PROJECT / 'output'
REVIEW = Path('/srv/media-production/review/openmontage-besquare-demo-01')
SOURCE_ASS = Path('/srv/media-production/review/besquare-demo-01/speaker-captions.ass')
FIXED_ASS = ASSETS / 'captions-corrected.ass'
FINAL = REVIEW / 'OpenMontage-Wasaga-18m-V1.mp4'
REPORT = REVIEW / 'OpenMontage-Wasaga-18m-V1.report.json'
PROBE = REVIEW / 'OpenMontage-Wasaga-18m-V1.ffprobe.json'
PINNED_COMMIT = 'cd9f3c1f03368be87b140af494914b8ee4e3c7a4'
OFFICIAL_REMOTE = 'https://github.com/calesthio/OpenMontage.git'


def run(cmd, *, cwd=None, capture=False, log_path=None, check=True):
    print('+', ' '.join(map(str, cmd)), flush=True)
    if log_path:
        with open(log_path, 'w', encoding='utf-8') as log:
            p = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True)
    else:
        p = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    if check and p.returncode != 0:
        if capture:
            print(p.stdout[-4000:] if p.stdout else '', file=sys.stderr)
            print(p.stderr[-4000:] if p.stderr else '', file=sys.stderr)
        raise RuntimeError(f'command failed ({p.returncode}): {cmd[0]}')
    return p


def capture(cmd, *, cwd=None):
    return run(cmd, cwd=cwd, capture=True).stdout.strip()


def ensure_dirs():
    for p in (ANALYSIS, ASSETS, OUTPUT, REVIEW):
        p.mkdir(parents=True, exist_ok=True)


def preflight():
    if not SOURCE.is_file() or SOURCE.stat().st_size < 8_000_000_000:
        raise RuntimeError(f'isolated source missing or unexpectedly small: {SOURCE}')
    if not OM_PYTHON.exists():
        raise RuntimeError(f'OpenMontage venv missing: {OM_PYTHON}')
    remote = capture(['git', '-C', str(OM_REPO), 'remote', 'get-url', 'origin'])
    commit = capture(['git', '-C', str(OM_REPO), 'rev-parse', 'HEAD'])
    if remote != OFFICIAL_REMOTE:
        raise RuntimeError(f'unexpected OpenMontage remote: {remote}')
    if commit != PINNED_COMMIT:
        raise RuntimeError(f'unexpected OpenMontage revision: {commit}')
    probe = json.loads(capture([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration,size',
        '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate',
        '-of', 'json', str(SOURCE)
    ]))
    gpu = capture(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'])
    return {'remote': remote, 'commit': commit, 'source_probe': probe, 'gpu': gpu}


def openmontage_understand():
    out = ANALYSIS / 'openmontage-video-understanding.json'
    script = OM_REPO / '.agents/skills/video-understand/scripts/understand_video.py'
    # The official helper gracefully continues without transcription if Whisper
    # is not installed; frame sampling and technical understanding still run.
    cmd = [
        str(OM_PYTHON), str(script), str(SOURCE), '--mode', 'interval',
        '--max-frames', '24', '--whisper-model', 'tiny', '--quiet', '--output', str(out)
    ]
    run(cmd, cwd=OM_REPO)
    return json.loads(out.read_text(encoding='utf-8'))


def prepare_captions():
    if not SOURCE_ASS.exists():
        return None
    text = SOURCE_ASS.read_text(encoding='utf-8')
    replacements = {
        'Visaga': 'Wasaga', 'visaga': 'Wasaga', 'B square': 'BeSquare',
        'P square': 'pSquare', 'broad walks': 'boardwalks',
    }
    for wrong, right in replacements.items():
        text = text.replace(wrong, right)
    out = []
    for line in text.splitlines():
        if line.startswith('Style: Left,') or line.startswith('Style: Right,'):
            parts = line.split(',')
            # ASS style columns: Name,Fontname,Fontsize,Primary,Secondary,Outline,...
            if len(parts) > 6:
                parts[3] = '&H00FFFFFF'
                parts[4] = '&H00FFFFFF'
                parts[5] = '&H0095FF7D' if line.startswith('Style: Left,') else '&H00FFD983'
                line = ','.join(parts)
        out.append(line)
    FIXED_ASS.write_text('\n'.join(out) + '\n', encoding='utf-8')
    return FIXED_ASS


def ensure_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        return
    except Exception:
        run([str(OM_PYTHON), '-m', 'pip', 'install', '--quiet', 'Pillow'])


def build_cards():
    ensure_pillow()
    from PIL import Image, ImageDraw, ImageFont

    FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

    def f(path, size):
        return ImageFont.truetype(path, size)

    events = [
        dict(id='opening', start=2.5, end=8.0, side='right', eyebrow='BESQUARE EXPLAINER',
             title="WASAGA BEACH: WHAT'S REALLY HAPPENING?", value='FACTS • FUNDING • TRADE-OFFS',
             subtitle='A source-led look at the transformation'),
        dict(id='destination', start=76, end=87, side='right', eyebrow='DESTINATION WASAGA',
             title='A MASTER PLAN, NOT A BLANK CHEQUE', value='COMMUNITY-LED PLANNING',
             subtitle='Long-term waterfront and downtown vision'),
        dict(id='parkland', start=130, end=141, side='left', eyebrow='PUBLIC LAND',
             title='PROPOSED LAND TRANSFER', value='< 60 HECTARES  •  ~3%',
             subtitle='Published statements say the beach remains public'),
        dict(id='investment', start=212, end=222, side='right', eyebrow='INVESTMENT',
             title='PUBLIC + PRIVATE PROJECTS', value='$506 MILLION',
             subtitle='Town-reported commitments since 2023'),
        dict(id='mix', start=224, end=242, side='left', eyebrow='WHERE THE $506M COMES FROM',
             title='REPORTED FUNDING MIX', subtitle='Public funding + private-sector commitments',
             bars=[('Provincial', 202.8), ('Federal', 3.1), ('County + grants', 0.158), ('Private sector', 300.0)]),
        dict(id='ontario', start=281, end=300, side='right', eyebrow='ONTARIO FUNDING',
             title='DESTINATION WASAGA ANNOUNCEMENTS', value='$37.9 MILLION',
             subtitle='Nancy Island + Beach Drive/roads + planning',
             bars=[('Nancy Island', 25.0), ('Beach Drive / roads', 10.9), ('Planning', 2.0)]),
        dict(id='beachdrive', start=304, end=316, side='left', eyebrow='BEACH DRIVE',
             title='FLOOD-RESILIENCE REBUILD', value='+5 FT  •  ~1.5 M',
             subtitle='Published elevation increase along the corridor'),
        dict(id='ropeway', start=365, end=380, side='right', eyebrow='ROPEWAY / AERIAL ATTRACTIONS',
             title='EXPLORATION, NOT FINAL APPROVAL', value='NO FINAL PROJECT YET',
             subtitle='No final route, design, construction or financing commitment'),
        dict(id='hotel', start=482, end=498, side='left', eyebrow='PRIVATE INVESTMENT',
             title='SUNRAY GROUP HOTEL PROJECT', value='$45M+',
             subtitle='Town announcement also projected 100+ local jobs'),
        dict(id='tax', start=568, end=579, side='right', eyebrow='2026 PROPERTY TAX',
             title='BLENDED TAX CHANGE', value='2.99%',
             subtitle='Town budget release: existing service levels maintained'),
        dict(id='arena', start=617, end=648, side='left', eyebrow='ARENA + LIBRARY',
             title='PUBLISHED FUNDING PLAN', subtitle='Multiple funding sources, not one taxpayer line item',
             bars=[('Debt', 31.70), ('Development charges', 14.22), ('Reserves', 13.58), ('Taxation', 0.38)]),
        dict(id='visitors', start=811, end=822, side='right', eyebrow='TOURISM',
             title='ANNUAL VISITATION', value='2 MILLION+',
             subtitle='Visitors welcomed by Wasaga Beach each year'),
        dict(id='election', start=890, end=915, side='left', eyebrow='2026 MUNICIPAL ELECTION',
             title='ELECTION DAY', value='OCTOBER 26, 2026',
             subtitle='Mayor • Deputy Mayor • Five Councillors'),
    ]

    def rounded(draw, box, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def fit(draw, text, box_width, start_size, min_size=24, bold=True):
        path = BOLD if bold else FONT
        for size in range(start_size, min_size - 1, -2):
            ff = f(path, size)
            if draw.textbbox((0, 0), text, font=ff)[2] <= box_width:
                return ff
        return f(path, min_size)

    manifest = []
    for ev in events:
        img = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        is_chart = 'bars' in ev
        w = 850 if not is_chart else 930
        h = 300 if not is_chart else 455
        x = 1920 - w - 72 if ev['side'] == 'right' else 72
        y = 94
        rounded(d, (x + 10, y + 14, x + w + 10, y + h + 14), 32, (0, 0, 0, 92))
        rounded(d, (x, y, x + w, y + h), 32, (10, 21, 38, 238), (72, 214, 224, 235), 3)
        d.rectangle((x, y, x + 11, y + h), fill=(72, 214, 224, 255))
        d.text((x + 42, y + 30), ev['eyebrow'], font=f(BOLD, 22), fill=(99, 230, 238, 255))
        title_font = fit(d, ev['title'], w - 84, 42, 26, True)
        d.text((x + 42, y + 72), ev['title'], font=title_font, fill=(248, 250, 252, 255))
        cursor = y + 132
        if ev.get('value'):
            value_font = fit(d, ev['value'], w - 84, 62, 34, True)
            d.text((x + 42, cursor), ev['value'], font=value_font, fill=(250, 204, 21, 255))
            cursor += 80
        if is_chart:
            vals = ev['bars']
            maxv = max(v for _, v in vals) or 1
            by = y + 154
            labelw = 230
            barx = x + 42 + labelw
            maxbw = w - labelw - 125
            for label, val in vals:
                d.text((x + 42, by + 4), label, font=f(FONT, 23), fill=(226, 232, 240, 255))
                bw = max(6, int(maxbw * val / maxv))
                rounded(d, (barx, by, barx + bw, by + 30), 12, (72, 214, 224, 230))
                txt = f'{val:g}M' if val >= 1 else f'{val * 1000:.0f}K'
                tx = min(barx + bw + 10, x + w - 92)
                d.text((tx, by + 1), txt, font=f(BOLD, 20), fill=(250, 204, 21, 255))
                by += 57
            cursor = by + 2
        subtitle = ev.get('subtitle', '')
        if subtitle:
            lines = textwrap.wrap(subtitle, width=48)
            d.multiline_text((x + 42, min(cursor, y + h - 70)), '\n'.join(lines[:2]),
                             font=f(FONT, 24), fill=(203, 213, 225, 255), spacing=4)
        d.text((x + w - 205, y + h - 35), 'BeSquare by pSquare',
               font=f(BOLD, 15), fill=(148, 163, 184, 235))
        path = ASSETS / f"{ev['id']}.png"
        img.save(path)
        manifest.append({**ev, 'asset_path': str(path)})

    manifest_path = ANALYSIS / 'overlay-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def openmontage_smoke(manifest):
    src = OUTPUT / 'om-smoke-source.mp4'
    out = OUTPUT / 'openmontage-video-compose-smoke.mp4'
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', '72', '-i', str(SOURCE),
        '-t', '10', '-vf', 'scale=1280:-2', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
        '-c:a', 'aac', '-b:a', '128k', str(src)
    ])
    sys.path.insert(0, str(OM_REPO))
    os.chdir(OM_REPO)
    from tools.video.video_compose import VideoCompose
    # Use a left-side card so it remains visible after the 1280-wide smoke scale.
    asset = next(e['asset_path'] for e in manifest if e['side'] == 'left')
    result = VideoCompose().execute({
        'operation': 'overlay', 'input_path': str(src), 'output_path': str(out),
        'overlays': [{'asset_path': asset, 'x': 0, 'y': 0, 'start_seconds': 0, 'end_seconds': 10}],
        'codec': 'libx264', 'crf': 25,
    })
    data = {'success': bool(result.success), 'data': result.data, 'error': result.error}
    (ANALYSIS / 'openmontage-video-compose-smoke.json').write_text(json.dumps(data, indent=2, default=str), encoding='utf-8')
    if not result.success or not out.exists():
        raise RuntimeError(f'OpenMontage video_compose smoke failed: {result.error}')
    return data


def full_render(manifest, captions_path):
    duration = float(capture(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(SOURCE)]))
    inputs = ['ffmpeg', '-hide_banner', '-y', '-i', str(SOURCE)]
    for ev in manifest:
        inputs += ['-loop', '1', '-framerate', '1', '-i', ev['asset_path']]

    if captions_path and captions_path.exists():
        ass = str(captions_path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
        parts = [f"[0:v]scale=1920:1080:flags=lanczos,subtitles='{ass}'[base]"]
    else:
        parts = ['[0:v]scale=1920:1080:flags=lanczos[base]']

    prev = 'base'
    for i, ev in enumerate(manifest):
        inp = i + 1
        start = float(ev['start'])
        end = float(ev['end'])
        direction = 1 if ev.get('side') == 'right' else -1
        # Smooth 350 ms slide in/out while the PNG itself is only decoded at 1 fps.
        dx = 64 * direction
        xexpr = (
            f"if(lt(t,{start + 0.35:.3f}),{dx}-{dx}*(t-{start:.3f})/0.35,"
            f"if(gt(t,{end - 0.35:.3f}),{dx}*(t-{end - 0.35:.3f})/0.35,0))"
        )
        parts.append(f'[{inp}:v]format=rgba[ov{i}]')
        out = f'v{i}'
        parts.append(
            f"[{prev}][ov{i}]overlay=x='{xexpr}':y=0:format=auto:enable='between(t,{start:.3f},{end:.3f})'[{out}]"
        )
        prev = out
    parts.append(f'[{prev}]format=yuv420p[vout]')
    filter_complex = ';'.join(parts)
    (ANALYSIS / 'filter_complex.txt').write_text(filter_complex + '\n', encoding='utf-8')

    cmd = inputs + [
        '-filter_complex', filter_complex,
        '-map', '[vout]', '-map', '0:a:0?', '-t', f'{duration:.6f}',
        '-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr',
        '-cq', '19', '-b:v', '12M', '-maxrate', '20M', '-bufsize', '24M',
        '-c:a', 'copy', '-movflags', '+faststart', str(FINAL),
    ]
    # Persist a shell-readable representation for reproducibility without using
    # shell parsing for actual execution.
    import shlex
    (ANALYSIS / 'ffmpeg-command.txt').write_text(' '.join(shlex.quote(x) for x in cmd) + '\n', encoding='utf-8')
    render_log = ANALYSIS / 'render.log'
    run(cmd, log_path=render_log)
    if not FINAL.exists() or FINAL.stat().st_size < 100_000_000:
        tail = render_log.read_text(errors='replace')[-6000:] if render_log.exists() else ''
        raise RuntimeError('full render did not produce a valid output\n' + tail)
    return duration


def qc(understanding, manifest, preflight_data):
    probe = json.loads(capture([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration,size,bit_rate',
        '-show_entries', 'stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels',
        '-of', 'json', str(FINAL)
    ]))
    PROBE.write_text(json.dumps(probe, indent=2), encoding='utf-8')

    qdir = REVIEW / 'qc-frames'
    if qdir.exists():
        shutil.rmtree(qdir)
    qdir.mkdir(parents=True)
    times = [4, 80, 135, 216, 232, 289, 309, 372, 490, 573, 630, 816, 900]
    for sec in times:
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(sec), '-i', str(FINAL),
             '-frames:v', '1', '-q:v', '2', str(qdir / f'frame-{sec}.jpg')])

    report = {
        'status': 'complete',
        'generated_at_epoch': time.time(),
        'pipeline': 'OpenMontage official repo + video-understand + OpenMontage video_compose smoke + agent-directed overlay composition + NVENC delivery',
        'official_remote': OFFICIAL_REMOTE,
        'official_commit': PINNED_COMMIT,
        'source': str(SOURCE),
        'final': str(FINAL),
        'preflight': preflight_data,
        'video_understanding': {
            'duration': understanding.get('duration'),
            'resolution': understanding.get('resolution'),
            'frame_count': understanding.get('frame_count'),
            'transcript_segments': len(understanding.get('transcript') or []),
            'text_preview': (understanding.get('text') or '')[:1000],
        },
        'overlay_count': len(manifest),
        'overlay_ids': [e['id'] for e in manifest],
        'ffprobe': probe,
        'qc_frames': sorted(p.name for p in qdir.glob('*.jpg')),
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    ensure_dirs()
    pre = preflight()
    print('PRECHECK_OK', json.dumps({'commit': pre['commit'], 'gpu': pre['gpu']}), flush=True)
    understanding = openmontage_understand()
    print('OPENMONTAGE_UNDERSTAND_OK', json.dumps({
        'duration': understanding.get('duration'), 'frame_count': understanding.get('frame_count'),
        'transcript_segments': len(understanding.get('transcript') or [])
    }), flush=True)
    captions = prepare_captions()
    manifest = build_cards()
    print('GRAPHICS_READY', len(manifest), flush=True)
    smoke = openmontage_smoke(manifest)
    print('OPENMONTAGE_VIDEO_COMPOSE_SMOKE_OK', json.dumps(smoke, default=str), flush=True)
    full_render(manifest, captions)
    print('FULL_RENDER_OK', str(FINAL), flush=True)
    report = qc(understanding, manifest, pre)
    print('QC_COMPLETE', json.dumps({
        'status': report['status'], 'final': report['final'], 'overlay_count': report['overlay_count'],
        'duration': report['ffprobe'].get('format', {}).get('duration'),
        'size': report['ffprobe'].get('format', {}).get('size')
    }), flush=True)


if __name__ == '__main__':
    main()
