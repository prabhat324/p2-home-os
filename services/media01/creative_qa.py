#!/usr/bin/env python3
"""Creative completeness gate. Prevents technically clean but editorially empty renders."""
import argparse,json
from pathlib import Path


def read(p,d):
    try:return json.loads(Path(p).read_text())
    except Exception:return d

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--timeline',type=Path,required=True);ap.add_argument('--assignments',type=Path);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args()
    manifest=read(a.manifest,{});timeline=read(a.timeline,{});mode=manifest.get('mode','explainer');fail=[];warn=[];metrics={'mode':mode}
    if mode=='podcast':
        cfg=manifest.get('podcast_captions',{})
        if not cfg.get('enabled',True):fail.append('Podcast captions are disabled')
        assignments=read(a.assignments,{}) if a.assignments else {}
        cues=assignments.get('cues',[]);left=sum(x.get('side')=='left' for x in cues);right=sum(x.get('side')=='right' for x in cues)
        metrics.update({'caption_cues':len(cues),'left_cues':left,'right_cues':right})
        if len(cues)<5:fail.append('Too few speaker-aware caption cues were generated')
        if left==0 or right==0:fail.append('Two-speaker podcast requires captions assigned to both left and right speakers')
        low=sum(float(x.get('speaker_confidence',0))<float(cfg.get('confidence_threshold',0.055)) for x in cues);metrics['low_confidence_cues']=low
        if cues and low/len(cues)>.65:warn.append('Most speaker assignments used continuity fallback; review speaker attribution')
    else:
        events=timeline.get('events',[]);policy=timeline.get('creative_policy',{});minimum=int(policy.get('minimum_visual_events',1));sourced=[e for e in events if e.get('kind')!='zoom'];min_sourced=int(policy.get('minimum_sourced_visual_events',0))
        metrics.update({'visual_events':len(events),'minimum_visual_events':minimum,'sourced_visual_events':len(sourced),'minimum_sourced_visual_events':min_sourced,'research_requests':len(timeline.get('asset_requests',[]))})
        if len(events)<minimum:fail.append(f'Creative timeline too sparse: {len(events)} visual events, minimum {minimum}')
        if len(sourced)<min_sourced:fail.append(f'Not enough sourced supporting visuals: {len(sourced)} present, minimum {min_sourced}. Resolve timeline asset_requests before final review.')
        kinds={e.get('kind') for e in events};metrics['event_kinds']=sorted(k for k in kinds if k)
        if not kinds:fail.append('No visual treatment events were generated')
        if events and kinds=={'zoom'}:warn.append('Timeline contains only zooms and is not allowed to finish when sourced visuals are required')
    status='PASS' if not fail else 'FAIL';payload={'status':status,'failures':fail,'warnings':warn,'metrics':metrics};a.report.write_text(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2));return 0 if status=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
