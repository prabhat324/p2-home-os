#!/usr/bin/env python3
"""Install the BeSquare V6.1 knowledge-video policy into media-01 worker.

Idempotent and assertion-driven: it refuses to patch an unexpected worker
shape. The deployment playbook creates backups before invoking this script.
"""
from __future__ import annotations

import json
import py_compile
from pathlib import Path

APP = Path('/home/p2ops/media01')
ROOT = Path('/srv/media-production')
WORKER = APP / 'media_worker.py'
PROFILE = APP / 'quality-profile.json'
GUARDRAIL = APP / 'besquare_guardrail.py'
STANDARD = ROOT / 'standards/besquare-knowledge-v1/standard.json'
VERIFY = ROOT / 'standards/besquare-knowledge-v1/benchmark-verification.json'


def replace_once(text, old, new, label):
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise RuntimeError(f'{label}: expected one patch anchor, found {count}')
    return text.replace(old, new, 1)


def patch_worker():
    text = WORKER.read_text(encoding='utf-8')
    text = replace_once(
        text,
        "TERMINAL={'BLOCKED_FOR_REVIEW','REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED','QA_REVIEW_REQUIRED','FAILED_FINAL','BLOCKED_STORAGE'}",
        "TERMINAL={'BLOCKED_FOR_REVIEW','REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED','KNOWLEDGE_REVIEW_REQUIRED','QA_REVIEW_REQUIRED','FAILED_FINAL','BLOCKED_STORAGE'}",
        'terminal state',
    )
    text = replace_once(text, 'QA_LOGIC_VERSION=5', 'QA_LOGIC_VERSION=6', 'qa logic version')
    text = replace_once(
        text,
        "qa_logic_stale=state in {'QA_REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED'} and int(previous.get('qa_logic_version',0) or 0)<QA_LOGIC_VERSION",
        "qa_logic_stale=state in {'QA_REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED','KNOWLEDGE_REVIEW_REQUIRED'} and int(previous.get('qa_logic_version',0) or 0)<QA_LOGIC_VERSION",
        'stale-state set',
    )

    function_block = '''\n\ndef knowledge_gate(r,manifest_path,manifest,timeline,review):\n    if mode_for(manifest)=='podcast':return True,{}\n    report=review/'knowledge-standard-qa.json'\n    standard=ROOT/'standards/besquare-knowledge-v1/standard.json'\n    verification=ROOT/'standards/besquare-knowledge-v1/benchmark-verification.json'\n    cmd=[sys.executable,APP/'besquare_guardrail.py','--manifest',manifest_path,'--timeline',timeline,'--standard',standard,'--verification',verification,'--report',report]\n    try:\n        r.run(cmd,'KNOWLEDGE_STANDARD_QA',timeout=180);return True,read(report,{}) or {}\n    except RuntimeError:\n        q=read(report,{}) or {};r.state('KNOWLEDGE_REVIEW_REQUIRED',standard='besquare-knowledge-v1',guardrail=q,failures=q.get('failures',[]),warnings=q.get('warnings',[]));return False,q\n'''
    if 'def knowledge_gate(' not in text:
        marker = '\ndef review_job(job):\n'
        if text.count(marker) != 1:
            raise RuntimeError('knowledge gate insertion anchor missing/ambiguous')
        text = text.replace(marker, function_block + marker, 1)

    call_old = "            timeline=build_timeline(r,job,render_manifest_path,render_manifest,analysis,work,review,duration)\n            assignments=None;subtitle_ass=None"
    call_new = "            timeline=build_timeline(r,job,render_manifest_path,render_manifest,analysis,work,review,duration)\n            knowledge_ok,knowledge=knowledge_gate(r,render_manifest_path,render_manifest,timeline,review)\n            if not knowledge_ok:return\n            assignments=None;subtitle_ass=None"
    text = replace_once(text, call_old, call_new, 'knowledge gate call')
    WORKER.write_text(text, encoding='utf-8')


def patch_profile():
    data = json.loads(PROFILE.read_text(encoding='utf-8'))
    data['profile'] = 'besquare-youtube-4k-v4-v61-standard'
    data['editing_standard'] = {
        'id': 'besquare-knowledge-v1',
        'applies_to_modes': ['explainer', 'feature'],
        'standard_path': str(STANDARD),
        'benchmark_reference': '/srv/media-production/standards/besquare-knowledge-v1/reference/wasaga-report-2026-V6.1-youtube-master.mp4',
        'benchmark_verification': str(VERIFY),
        'pre_render_guardrail_required': True,
        'manual_review_required': True,
    }
    data['openmontage'] = {
        'production_role': 'asset_only',
        'full_video_editor_allowed': False,
        'asset_request_filename': 'openmontage-assets.json',
        'asset_review_required': True,
    }
    creative = data.setdefault('creative', {})
    creative['v61_benchmark_required_for_explainers'] = True
    creative['prefer_high_value_visuals_over_effect_frequency'] = True
    editorial = data.setdefault('editorial', {})
    editorial['v61_gold_reference_required'] = True
    editorial['openmontage_primary_edit_prohibited'] = True
    editorial['no_cropped_faces_or_source_text'] = True
    editorial['repeated_segments_prohibited_unless_intentional'] = True
    editorial['graphs_must_explain_specific_claim'] = True
    PROFILE.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def verify():
    if not STANDARD.is_file() or not VERIFY.is_file() or not GUARDRAIL.is_file():
        raise RuntimeError('standard, verification marker, or guardrail file missing')
    standard = json.loads(STANDARD.read_text(encoding='utf-8'))
    marker = json.loads(VERIFY.read_text(encoding='utf-8'))
    if standard.get('standard_id') != 'besquare-knowledge-v1':
        raise RuntimeError('wrong standard id')
    if marker.get('benchmark_sha256') != standard.get('benchmark', {}).get('sha256'):
        raise RuntimeError('benchmark verification marker does not match standard')
    py_compile.compile(str(WORKER), doraise=True)
    py_compile.compile(str(GUARDRAIL), doraise=True)
    json.loads(PROFILE.read_text(encoding='utf-8'))
    return {
        'worker': str(WORKER),
        'worker_qa_logic_version': 6,
        'standard': str(STANDARD),
        'verification': str(VERIFY),
        'guardrail': str(GUARDRAIL),
        'openmontage_role': 'asset_only',
    }


def main():
    patch_worker()
    patch_profile()
    print(json.dumps(verify(), indent=2))


if __name__ == '__main__':
    main()
