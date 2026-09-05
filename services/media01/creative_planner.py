#!/usr/bin/env python3
"""Build deterministic creative timelines from analysis plus verified project assets/graphics."""
import argparse,json,re
from pathlib import Path

def read(path,default):
    try:return json.loads(Path(path).read_text())
    except Exception:return default

def words(text):return re.findall(r"[A-Za-z0-9$%.,'’&:/()-]+",text or '')
def normalize_text(text):
    text=str(text or '')
    text=re.sub(r'\b(?:Visaga|Vassaga|Vaseca|Vasaga|Wasega)\s+Beach\b','Wasaga Beach',text,flags=re.I)
    return re.sub(r'\b(?:Visaga|Vassaga|Vaseca|Vasaga|Wasega)\b','Wasaga',text,flags=re.I)
def make_zoom(start,end,scale=1.045):return {'start':round(start,3),'end':round(end,3),'kind':'zoom','approved':True,'crop_reviewed':True,'scale':scale,'generated_by':'creative_planner'}
def make_fact(flag,source):
    text=' '.join(words(normalize_text(flag.get('text','')))[:22]);return {'start':round(float(flag['second']),3),'end':round(float(flag['second'])+6.0,3),'kind':'fact_card','approved':True,'title':text,'source':source,'generated_by':'creative_planner'}
def make_asset(asset):return {'start':float(asset['start']),'end':float(asset['end']),'kind':asset.get('kind','image'),'approved':True,'asset':asset['path'],'source':asset.get('source','Project-provided asset'),'caption':normalize_text(asset.get('caption','')),'generated_by':'creative_planner'}
def make_graphic(item):
    kind=item.get('kind')
    if kind not in {'fact_card','graph','document','newspaper'}:raise ValueError('Unsupported curated graphic kind')
    source=str(item.get('source','')).strip()
    if not source:raise ValueError('Curated graphic requires source')
    e={'start':float(item['start']),'end':float(item['end']),'kind':kind,'approved':True,'source':source,'generated_by':'curated_graphic'}
    if kind=='graph':
        e['title']=normalize_text(item.get('title',''));e['unit']=normalize_text(item.get('unit',''));e['data']=[{'label':normalize_text(x.get('label','')),'value':float(x['value'])} for x in item.get('data',[])]
        if not e['data']:raise ValueError('Graph requires data')
    else:
        e['title']=normalize_text(item.get('title',''))
        if not e['title']:raise ValueError(f'{kind} requires title')
        if item.get('subtitle'):e['subtitle']=normalize_text(item['subtitle'])
        if item.get('excerpt'):e['excerpt']=normalize_text(item['excerpt'])
    return e
def segment_near(transcript,second):
    segs=transcript.get('segments',[])
    if not segs:return ''
    best=min(segs,key=lambda s:abs(float(s.get('start',0))-second));return normalize_text(str(best.get('text','')).strip())
def build(manifest,report,transcript,duration):
    mode=manifest.get('mode','explainer');out={'version':5,'mode':mode,'events':[],'chapters':manifest.get('chapters',[]),'creative_policy':{},'asset_requests':[]}
    if mode=='podcast':out['creative_policy']={'cutaways':False,'speaker_captions':True,'minimum_visual_events':0,'minimum_sourced_visual_events':0};return out
    events=[]
    for asset in manifest.get('visual_assets',[]):
        try:
            e=make_asset(asset)
            if 0<=e['start']<e['end']<=duration:events.append(e)
        except Exception:pass
    for item in manifest.get('graphic_events',[]):
        try:
            e=make_graphic(item)
            if 0<=e['start']<e['end']<=duration:events.append(e)
        except Exception:pass
    verified=manifest.get('verified_sources',{});curated_ranges=[(e['start']-2,e['end']+2) for e in events if e.get('kind')!='zoom']
    for flag in report.get('fact_check_flags',[]):
        sec=float(flag.get('second',0));key=str(int(round(sec)));source=verified.get(key) or verified.get(str(flag.get('id','')))
        if source and not any(a<=sec<=b for a,b in curated_ranges):
            e=make_fact(flag,source);e['end']=min(duration,e['end']);events.append(e)
        elif not source and not any(a<=sec<=b for a,b in curated_ranges):out['asset_requests'].append({'second':round(sec,2),'kind':'verified_fact_source','context':normalize_text(str(flag.get('text','')).strip()),'reason':'numeric/date/currency claim needs a primary or authoritative source before graphic treatment'})
    occupied=sorted((float(e['start']),float(e['end'])) for e in events);t=18.0
    while t<duration-8:
        if not any(a-3<=t<=b+3 for a,b in occupied):events.append(make_zoom(t,min(t+7.0,duration),1.045))
        t+=25.0
    priority={'image':5,'document':5,'newspaper':5,'broll':5,'fact_card':4,'graph':4,'zoom':1};clean=[]
    for e in sorted(events,key=lambda x:(x['start'],-priority.get(x['kind'],2))):
        if clean and e['start']<clean[-1]['end']:
            if priority.get(e['kind'],2)>priority.get(clean[-1]['kind'],2):clean[-1]=e
            continue
        clean.append(e)
    sourced=[e for e in clean if e.get('kind')!='zoom'];min_visual=max(1,int(duration/35.0));min_sourced=0 if duration<90 else max(1,int(duration/90.0));deficit=max(0,min_sourced-len(sourced))
    if deficit:
        step=duration/(deficit+1)
        for i in range(deficit):
            sec=step*(i+1);out['asset_requests'].append({'second':round(sec,2),'kind':'supporting_visual','context':segment_near(transcript,sec),'reason':'long-form explainer requires sourced supporting media, document, newspaper, image, B-roll, graph, or verified fact card'})
    out['events']=clean;out['creative_policy']={'cutaways':True,'speaker_captions':False,'minimum_visual_events':min_visual,'actual_visual_events':len(clean),'minimum_sourced_visual_events':min_sourced,'actual_sourced_visual_events':len(sourced),'research_requests':len(out['asset_requests'])};return out
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--duration',type=float,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();timeline=build(read(a.manifest,{}),read(a.report,{}),read(a.transcript,{}),a.duration);a.output.write_text(json.dumps(timeline,indent=2));p=timeline['creative_policy'];print(json.dumps({'mode':timeline['mode'],'events':len(timeline['events']),'minimum_visual_events':p.get('minimum_visual_events',0),'sourced_visuals':p.get('actual_sourced_visual_events',0),'minimum_sourced_visuals':p.get('minimum_sourced_visual_events',0),'asset_requests':len(timeline.get('asset_requests',[])),'output':str(a.output)},indent=2))
if __name__=='__main__':main()
