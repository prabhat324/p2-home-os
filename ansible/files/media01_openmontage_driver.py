#!/usr/bin/env python3
"""Create a six-minute OpenMontage proof cut on media-01.

The original 18:46 4K master remains read-only. This proof intentionally limits
scope to 0:00-6:00 so visual direction can be validated before a full-length pass.
OpenMontage is used for local video understanding and its VideoCompose overlay
capability is exercised as a smoke test. The proof master is rendered at 1080p
with NVIDIA NVENC, corrected captions, restrained motion graphics, and QC frames.
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
MASTER = Path('/srv/media-production/work/openmontage-besquare-demo-01/input/master.mp4')
PROJECT = Path('/srv/media-production/work/openmontage-besquare-demo-01')
ANALYSIS = PROJECT / 'analysis-6m-proof'
ASSETS = PROJECT / 'assets-6m-proof'
OUTPUT = PROJECT / 'output-6m-proof'
REVIEW = Path('/srv/media-production/review/openmontage-besquare-demo-01')
SOURCE_ASS = Path('/srv/media-production/review/besquare-demo-01/speaker-captions.ass')
FIXED_ASS = ASSETS / 'captions-corrected-6m.ass'
PROOF_SOURCE = OUTPUT / 'source-6m-1080p.mp4'
FINAL = REVIEW / 'OpenMontage-Wasaga-6m-Proof-V1.mp4'
REPORT = REVIEW / 'OpenMontage-Wasaga-6m-Proof-V1.report.json'
PROBE = REVIEW / 'OpenMontage-Wasaga-6m-Proof-V1.ffprobe.json'
PINNED_COMMIT = 'cd9f3c1f03368be87b140af494914b8ee4e3c7a4'
OFFICIAL_REMOTE = 'https://github.com/calesthio/OpenMontage.git'
PROOF_SECONDS = 360.0


def run(cmd, *, cwd=None, capture=False, log_path=None, check=True):
    print('+', ' '.join(map(str, cmd)), flush=True)
    if log_path:
        with open(log_path, 'w', encoding='utf-8') as log:
            p = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True)
    else:
        p = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    if check and p.returncode != 0:
        if capture:
            print((p.stdout or '')[-4000:], file=sys.stderr)
            print((p.stderr or '')[-4000:], file=sys.stderr)
        raise RuntimeError(f'command failed ({p.returncode}): {cmd[0]}')
    return p


def capture(cmd, *, cwd=None):
    return run(cmd, cwd=cwd, capture=True).stdout.strip()


def ensure_dirs():
    for p in (ANALYSIS, ASSETS, OUTPUT, REVIEW):
        p.mkdir(parents=True, exist_ok=True)


def preflight():
    if not MASTER.is_file() or MASTER.stat().st_size < 8_000_000_000:
        raise RuntimeError(f'isolated 4K source missing or unexpectedly small: {MASTER}')
    if not OM_PYTHON.exists():
        raise RuntimeError(f'OpenMontage venv missing: {OM_PYTHON}')
    remote = capture(['git', '-C', str(OM_REPO), 'remote', 'get-url', 'origin'])
    commit = capture(['git', '-C', str(OM_REPO), 'rev-parse', 'HEAD'])
    if remote != OFFICIAL_REMOTE:
        raise RuntimeError(f'unexpected OpenMontage remote: {remote}')
    if commit != PINNED_COMMIT:
        raise RuntimeError(f'unexpected OpenMontage revision: {commit}')
    source_probe = json.loads(capture([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration,size',
        '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate',
        '-of', 'json', str(MASTER)
    ]))
    gpu = capture(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'])
    return {'remote': remote, 'commit': commit, 'source_probe': source_probe, 'gpu': gpu}


def make_proof_source():
    if PROOF_SOURCE.exists():
        try:
            dur = float(capture(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(PROOF_SOURCE)]))
            if 358.0 <= dur <= 362.0 and PROOF_SOURCE.stat().st_size > 100_000_000:
                print('REUSE_PROOF_SOURCE', PROOF_SOURCE, flush=True)
                return
        except Exception:
            pass
    run([
        'ffmpeg', '-hide_banner', '-y', '-i', str(MASTER), '-t', str(PROOF_SECONDS),
        '-vf', 'scale=1920:1080:flags=lanczos',
        '-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr',
        '-cq', '18', '-b:v', '14M', '-maxrate', '22M', '-bufsize', '28M',
        '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(PROOF_SOURCE)
    ], log_path=ANALYSIS / 'proof-source-encode.log')
    if not PROOF_SOURCE.exists() or PROOF_SOURCE.stat().st_size < 100_000_000:
        raise RuntimeError('six-minute proof source was not created correctly')


def openmontage_understand():
    out = ANALYSIS / 'openmontage-video-understanding-6m.json'
    script = OM_REPO / '.agents/skills/video-understand/scripts/understand_video.py'
    cmd = [
        str(OM_PYTHON), str(script), str(PROOF_SOURCE), '--mode', 'interval',
        '--max-frames', '18', '--whisper-model', 'tiny', '--quiet', '--output', str(out)
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
    except Exception:
        run([str(OM_PYTHON), '-m', 'pip', 'install', '--quiet', 'Pillow'])


def build_cards():
    ensure_pillow()
    from PIL import Image, ImageDraw, ImageFont

    FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

    def ff(path, size):
        return ImageFont.truetype(path, size)

    events = [
        dict(id='opening', start=2.5, end=8.5, side='right', eyebrow='BESQUARE EXPLAINER',
             title="WASAGA BEACH: WHAT'S REALLY HAPPENING?", value='FACTS • FUNDING • TRADE-OFFS',
             subtitle='A source-led look at the transformation'),
        dict(id='destination', start=76, end=88, side='right', eyebrow='DESTINATION WASAGA',
             title='A MASTER PLAN, NOT A BLANK CHEQUE', value='COMMUNITY-LED PLANNING',
             subtitle='Long-term waterfront and downtown vision'),
        dict(id='parkland', start=130, end=143, side='left', eyebrow='PUBLIC LAND',
             title='PROPOSED LAND TRANSFER', value='< 60 HECTARES  •  ~3%',
             subtitle='Published statements say the beach remains public'),
        dict(id='investment', start=212, end=224, side='right', eyebrow='INVESTMENT',
             title='PUBLIC + PRIVATE PROJECTS', value='$506 MILLION',
             subtitle='Town-reported commitments since 2023'),
        dict(id='mix', start=224, end=244, side='left', eyebrow='WHERE THE $506M COMES FROM',
             title='REPORTED FUNDING MIX', subtitle='Public funding + private-sector commitments',
             bars=[('Provincial', 202.8), ('Federal', 3.1), ('County + grants', 0.158), ('Private sector', 300.0)]),
        dict(id='ontario', start=281, end=301, side='right', eyebrow='ONTARIO FUNDING',
             title='DESTINATION WASAGA ANNOUNCEMENTS', value='$37.9 MILLION',
             subtitle='Nancy Island + Beach Drive/roads + planning',
             bars=[('Nancy Island', 25.0), ('Beach Drive / roads', 10.9), ('Planning', 2.0)]),
        dict(id='beachdrive', start=304, end=318, side='left', eyebrow='BEACH DRIVE',
             title='FLOOD-RESILIENCE REBUILD', value='+5 FT  •  ~1.5 M',
             subtitle='Published elevation increase along the corridor'),
    ]

    def rounded(draw, box, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def fit(draw, text, box_width, start_size, min_size=24, bold=True):
        path = BOLD if bold else FONT
        for size in range(start_size, min_size - 1, -2):
            f = ff(path, size)
            if draw.textbbox((0, 0), text, font=f)[2] <= box_width:
                return f
        return ff(path, min_size)

    manifest = []
    for ev in events:
        img = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        chart = 'bars' in ev
        w = 860 if not chart else 940
        h = 300 if not chart else 455
        x = 1920 - w - 72 if ev['side'] == 'right' else 72
        y = 92
        rounded(d, (x + 12, y + 16, x + w + 12, y + h + 16), 32, (0, 0, 0, 90))
        rounded(d, (x, y, x + w, y + h), 32, (10, 21, 38, 238), (72, 214, 224, 235), 3)
        d.rectangle((x, y, x + 11, y + h), fill=(72, 214, 224, 255))
        d.text((x + 42, y + 29), ev['eyebrow'], font=ff(BOLD, 22), fill=(99, 230, 238, 255))
        d.text((x + 42, y + 72), ev['title'], font=fit(d, ev['title'], w - 84, 42, 26), fill=(248, 250, 252, 255))
        cursor = y + 132
        if ev.get('value'):
            d.text((x + 42, cursor), ev['value'], font=fit(d, ev['value'], w - 84, 62, 34), fill=(250, 204, 21, 255))
            cursor += 80
        if chart:
            vals = ev['bars']
            maxv = max(v for _, v in vals) or 1
            by = y + 154
            labelw = 235
            barx = x + 42 + labelw
            maxbw = w - labelw - 130
            for label, val in vals:
                d.text((x + 42, by + 4), label, font=ff(FONT, 23), fill=(226, 232, 240, 255))
                bw = max(6, int(maxbw * val / maxv))
                rounded(d, (barx, by, barx + bw, by + 30), 12, (72, 214, 224, 230))
                txt = f'{val:g}M' if val >= 1 else f'{val * 1000:.0f}K'
                d.text((min(barx + bw + 10, x + w - 92), by + 1), txt, font=ff(BOLD, 20), fill=(250, 204, 21, 255))
                by += 57
            cursor = by + 2
        subtitle = ev.get('subtitle', '')
        if subtitle:
            lines = textwrap.wrap(subtitle, width=48)
            d.multiline_text((x + 42, min(cursor, y + h - 70)), '\n'.join(lines[:2]),
                             font=ff(FONT, 24), fill=(203, 213, 225, 255), spacing=4)
        d.text((x + w - 205, y + h - 35), 'BeSquare by pSquare', font=ff(BOLD, 15), fill=(148, 163, 184, 235))
        path = ASSETS / f"{ev['id']}.png"
        img.save(path)
        manifest.append({**ev, 'asset_path': str(path)})

    bug = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(bug)
    rounded(d, (58, 42, 392, 104), 18, (8, 18, 34, 185), (72, 214, 224, 175), 2)
    d.text((80, 58), 'BeSquare by pSquare', font=ff(BOLD, 24), fill=(248, 250, 252, 245))
    bug_path = ASSETS / 'brand-bug.png'
    bug.save(bug_path)
    manifest.insert(0, dict(id='brand', start=0.0, end=PROOF_SECONDS, side='left', asset_path=str(bug_path)))

    (ANALYSIS / 'overlay-manifest-6m.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def openmontage_smoke(manifest):
    src = OUTPUT / 'om-smoke-source.mp4'
    out = OUTPUT / 'openmontage-video-compose-smoke.mp4'
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', '126', '-i', str(PROOF_SOURCE),
        '-t', '10', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '27',
        '-c:a', 'aac', '-b:a', '128k', str(src)
    ])
    sys.path.insert(0, str(OM_REPO))
    os.chdir(OM_REPO)
    from tools.video.video_compose import VideoCompose
    asset = next(e['asset_path'] for e in manifest if e['id'] == 'parkland')
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


def render_proof(manifest, captions_path):
    inputs = ['ffmpeg', '-hide_banner', '-y', '-i', str(PROOF_SOURCE)]
    for ev in manifest:
        inputs += ['-loop', '1', '-framerate', '1', '-i', ev['asset_path']]

    if captions_path and captions_path.exists():
        ass = str(captions_path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
        parts = [f"[0:v]subtitles='{ass}'[base]"]
    else:
        parts = ['[0:v]null[base]']

    prev = 'base'
    for i, ev in enumerate(manifest):
        inp = i + 1
        start = float(ev['start'])
        end = min(float(ev['end']), PROOF_SECONDS)
        direction = 1 if ev.get('side') == 'right' else -1
        dx = 56 * direction
        if ev['id'] == 'brand':
            xexpr = '0'
        else:
            xexpr = (
                f"if(lt(t,{start + 0.35:.3f}),{dx}-{dx}*(t-{start:.3f})/0.35,"
                f"if(gt(t,{end - 0.35:.3f}),{dx}*(t-{end - 0.35:.3f})/0.35,0))"
            )
        parts.append(f'[{inp}:v]format=rgba[ov{i}]')
        out = f'v{i}'
        parts.append(f"[{prev}][ov{i}]overlay=x='{xexpr}':y=0:format=auto:enable='between(t,{start:.3f},{end:.3f})'[{out}]")
        prev = out
    parts.append(f'[{prev}]format=yuv420p[vout]')
    fc = ';'.join(parts)
    (ANALYSIS / 'filter-complex-6m.txt').write_text(fc + '\n', encoding='utf-8')

    cmd = inputs + [
        '-filter_complex', fc, '-map', '[vout]', '-map', '0:a:0?', '-t', str(PROOF_SECONDS),
        '-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr',
        '-cq', '18', '-b:v', '14M', '-maxrate', '22M', '-bufsize', '28M',
        '-c:a', 'copy', '-movflags', '+faststart', str(FINAL),
    ]
    import shlex
    (ANALYSIS / 'ffmpeg-command-6m.txt').write_text(' '.join(shlex.quote(x) for x in cmd) + '\n', encoding='utf-8')
    log = ANALYSIS / 'render-6m.log'
    run(cmd, log_path=log)
    if not FINAL.exists() or FINAL.stat().st_size < 100_000_000:
        tail = log.read_text(errors='replace')[-6000:] if log.exists() else ''
        raise RuntimeError('six-minute proof render failed\n' + tail)


def qc(understanding, manifest, preflight_data):
    probe = json.loads(capture([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration,size,bit_rate',
        '-show_entries', 'stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels',
        '-of', 'json', str(FINAL)
    ]))
    PROBE.write_text(json.dumps(probe, indent=2), encoding='utf-8')

    qdir = REVIEW / 'qc-frames-6m-proof'
    if qdir.exists():
        shutil.rmtree(qdir)
    qdir.mkdir(parents=True)
    times = [4, 80, 135, 216, 232, 289, 309, 350]
    for sec in times:
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(sec), '-i', str(FINAL),
             '-frames:v', '1', '-q:v', '2', str(qdir / f'frame-{sec}.jpg')])

    report = {
        'status': 'complete',
        'scope': '0:00-6:00 validation proof only',
        'generated_at_epoch': time.time(),
        'pipeline': 'OpenMontage official repo + video-understand + OpenMontage VideoCompose smoke + agent-directed graphics + NVENC 1080p proof',
        'official_remote': OFFICIAL_REMOTE,
        'official_commit': PINNED_COMMIT,
        'source_master': str(MASTER),
        'proof_source': str(PROOF_SOURCE),
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
    make_proof_source()
    print('PROOF_SOURCE_READY', str(PROOF_SOURCE), flush=True)
    understanding = openmontage_understand()
    print('OPENMONTAGE_UNDERSTAND_OK', json.dumps({
        'duration': understanding.get('duration'),
        'frame_count': understanding.get('frame_count'),
        'transcript_segments': len(understanding.get('transcript') or [])
    }), flush=True)
    captions = prepare_captions()
    manifest = build_cards()
    print('GRAPHICS_READY', len(manifest), flush=True)
    smoke = openmontage_smoke(manifest)
    print('OPENMONTAGE_VIDEO_COMPOSE_SMOKE_OK', json.dumps(smoke, default=str), flush=True)
    render_proof(manifest, captions)
    print('PROOF_RENDER_OK', str(FINAL), flush=True)
    report = qc(understanding, manifest, pre)
    print('QC_COMPLETE', json.dumps({
        'status': report['status'], 'final': report['final'],
        'overlay_count': report['overlay_count'],
        'duration': report['ffprobe'].get('format', {}).get('duration'),
        'size': report['ffprobe'].get('format', {}).get('size')
    }), flush=True)


if __name__ == '__main__':
    main()
