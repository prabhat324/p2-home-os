#!/usr/bin/env python3
"""Build a deterministic creative timeline from analysis and optional project assets.

Podcast mode intentionally avoids cutaways. Explainer/feature mode creates visual rhythm
using subtle zooms plus sourced graphics/assets. Unsourced numeric claims never become
fact graphics. Long explainers also emit research requests and require sourced visuals.
"""
import argparse,json,re
from pathlib import Path


def read(path,default):
    try:return json.loads(Path(path).read_text())
    except Exception:return default

def words(text):return re.findall(r"[A-Za-z0-9$%.,'-]+",text or '')

def make_zoom(start,end,scale=1.045):
    return {'start':round(start,3),'end':round(end,3),'kind':'zoom','approved':True,'crop_reviewed':True,'scale':scale,'generated_by':'creative_planner'}

def make_fact(flag,source):
    text=' '.join(words(flag.get('text',''))[:22])
    return {'start':round(float(flag['second']),3),'end':round(float(flag['second'])+6.0,3),'kind':'fact_card','approved':True,'title':text,'source':source,'generated_by':'creative_planner'}

def make_asset(asset):
    return {'start':float(asset['start']),'end':float(asset['end']),'kind':asset.get('kind','image'),'approved':True,'asset':asset['path'],'source':asset.get('source','Project-provided asset'),'caption':asset.get('caption',''),'generated_by':'creative_planner'}

def segment_near(transcript,second):
    segs=transcript.get('segments',[])
    if not segs:return ''
    best=min(segs,key=lambda s:abs(float(s.get('start',0))-second))
    return str(best.get('text','')).strip()

def build(manifest,report,transcript,duration):
    mode=manifest.get('mode','explainer')
    out={'version':3,'mode':mode,'events':[],'chapters':manifest.get('chapters',[]),'creative_policy':{},'asset_requests':[]}
    if mode=='podcast':
        out['creative_policy']={'cutaways':False,'speaker_captions':True,'minimum_visual_events':0,'minimum_sourced_visual_events':0}
        return out
    events=[]
    for asset in manifest.get('visual_assets',[]):
        try:
            e=make_asset(asset)
            if 0<=e['start']<e['end']<=duration:events.append(e)
        except Exception:pass
    verified=manifest.get('verified_sources',{})
    for flag in report.get('fact_check_flags',[]):
        sec=float(flag.get('second',0));key=str(int(round(sec)))
        source=verified.get(key) or verified.get(str(flag.get('id','')))
        if source:
            e=make_fact(flag,source);e['end']=min(duration,e['end']);events.append(e)
        else:
            out['asset_requests'].append({'second':round(sec,2),'kind':'verified_fact_source','context':str(flag.get('text','')).strip(),'reason':'numeric/date/currency claim needs a primary or authoritative source before graphic treatment'})
    occupied=sorted((float(e['start']),float(e['end'])) for e in events)
    t=18.0
    while t<duration-8:
        if not any(a-3<=t<=b+3 for a,b in occupied):events.append(make_zoom(t,min(t+7.0,duration),1.045))
        t+=25.0
    priority={'image':4,'document':4,'newspaper':4,'broll':4,'fact_card':3,'graph':3,'zoom':1}
    clean=[]
    for e in sorted(events,key=lambda x:(x['start'],-priority.get(x['kind'],2))):
        if clean and e['start']<clean[-1]['end']:
            if priority.get(e['kind'],2)>priority.get(clean[-1]['kind'],2):clean[-1]=e
            continue
        clean.append(e)
    sourced=[e for e in clean if e.get('kind')!='zoom']
    min_visual=max(1,int(duration/35.0))
    min_sourced=0 if duration<90 else max(1,int(duration/90.0))
    # Add contextual research requests to fill any sourced-visual deficit. These are not edits
    # until a real asset/source is provided by the orchestration layer.
    deficit=max(0,min_sourced-len(sourced))
    if deficit:
        step=duration/(deficit+1)
        for i in range(deficit):
            sec=step*(i+1);out['asset_requests'].append({'second':round(sec,2),'kind':'supporting_visual','context':segment_near(transcript,sec),'reason':'long-form explainer requires sourced supporting media, document, newspaper, image, B-roll, graph, or verified fact card'})
    out['events']=clean
    out['creative_policy']={
        'cutaways':True,'speaker_captions':False,
        'minimum_visual_events':min_visual,'actual_visual_events':len(clean),
        'minimum_sourced_visual_events':min_sourced,'actual_sourced_visual_events':len(sourced),
        'research_requests':len(out['asset_requests'])
    }
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--duration',type=float,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    manifest=read(a.manifest,{});report=read(a.report,{});transcript=read(a.transcript,{})
    timeline=build(manifest,report,transcript,a.duration);a.output.write_text(json.dumps(timeline,indent=2))
    p=timeline['creative_policy'];print(json.dumps({'mode':timeline['mode'],'events':len(timeline['events']),'minimum_visual_events':p.get('minimum_visual_events',0),'sourced_visuals':p.get('actual_sourced_visual_events',0),'minimum_sourced_visuals':p.get('minimum_sourced_visual_events',0),'asset_requests':len(timeline.get('asset_requests',[])),'output':str(a.output)},indent=2))
if __name__=='__main__':main()
