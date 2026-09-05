#!/usr/bin/env python3
"""Build a deterministic creative timeline from analysis and optional project assets.

Podcast mode intentionally avoids cutaways. Explainer/feature mode creates a visual rhythm
using subtle zooms, sourced fact cards, and supplied image/document assets. It never invents
facts: unsourced numeric claims are not turned into fact cards.
"""
import argparse,json,re
from pathlib import Path


def read(path,default):
    try:return json.loads(Path(path).read_text())
    except Exception:return default

def clamp(v,a,b):return max(a,min(b,v))
def words(text):return re.findall(r"[A-Za-z0-9$%.,'-]+",text or '')

def make_zoom(start,end,scale=1.045):
    return {'start':round(start,3),'end':round(end,3),'kind':'zoom','approved':True,'crop_reviewed':True,'scale':scale,'generated_by':'creative_planner'}

def make_fact(flag,source):
    text=' '.join(words(flag.get('text',''))[:22])
    return {'start':round(float(flag['second']),3),'end':round(float(flag['second'])+6.0,3),'kind':'fact_card','approved':True,'title':text,'source':source,'generated_by':'creative_planner'}

def make_asset(asset):
    return {'start':float(asset['start']),'end':float(asset['end']),'kind':asset.get('kind','image'),'approved':True,'asset':asset['path'],'source':asset.get('source','Project-provided asset'),'caption':asset.get('caption',''),'generated_by':'creative_planner'}

def build(manifest,report,transcript,duration):
    mode=manifest.get('mode','explainer')
    out={'version':2,'mode':mode,'events':[],'chapters':manifest.get('chapters',[]),'creative_policy':{}}
    if mode=='podcast':
        out['creative_policy']={'cutaways':False,'speaker_captions':True,'minimum_visual_events':0}
        return out
    events=[]
    # Explicit project assets always take precedence. They must carry timing and provenance.
    for asset in manifest.get('visual_assets',[]):
        try:
            e=make_asset(asset)
            if 0<=e['start']<e['end']<=duration:events.append(e)
        except Exception:pass
    # Only convert claims into fact cards when project-level verified_sources maps a nearby second.
    verified=manifest.get('verified_sources',{})
    for flag in report.get('fact_check_flags',[]):
        sec=float(flag.get('second',0));key=str(int(round(sec)))
        source=verified.get(key) or verified.get(str(flag.get('id','')))
        if source:
            e=make_fact(flag,source);e['end']=min(duration,e['end']);events.append(e)
    # Fill talking-head gaps with restrained 4–5% eased zooms roughly every 25 seconds.
    occupied=sorted((float(e['start']),float(e['end'])) for e in events)
    t=18.0
    while t<duration-8:
        if not any(a-3<=t<=b+3 for a,b in occupied):events.append(make_zoom(t,min(t+7.0,duration),1.045))
        t+=25.0
    # Resolve overlaps in favor of explicit assets/fact cards over generated zooms.
    priority={'image':4,'document':4,'newspaper':4,'broll':4,'fact_card':3,'graph':3,'zoom':1}
    clean=[]
    for e in sorted(events,key=lambda x:(x['start'],-priority.get(x['kind'],2))):
        if clean and e['start']<clean[-1]['end']:
            if priority.get(e['kind'],2)>priority.get(clean[-1]['kind'],2):clean[-1]=e
            continue
        clean.append(e)
    out['events']=clean
    target=max(1,int(duration/35.0))
    out['creative_policy']={'cutaways':True,'speaker_captions':False,'minimum_visual_events':target,'actual_visual_events':len(clean)}
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--duration',type=float,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    manifest=read(a.manifest,{});report=read(a.report,{});transcript=read(a.transcript,{})
    timeline=build(manifest,report,transcript,a.duration);a.output.write_text(json.dumps(timeline,indent=2))
    print(json.dumps({'mode':timeline['mode'],'events':len(timeline['events']),'minimum_visual_events':timeline['creative_policy'].get('minimum_visual_events',0),'output':str(a.output)},indent=2))
if __name__=='__main__':main()
