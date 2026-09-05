#!/usr/bin/env python3
"""Evidence clips, proxies, chapter handoff and approved visual event rendering."""
import argparse,json,math,subprocess
from pathlib import Path
from runtime import atomic,read

def run(cmd):subprocess.run(list(map(str,cmd)),check=True,timeout=14400)
def info(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)],text=True))
def metadata(p):
    x=info(p);v=next(s for s in x['streams'] if s['codec_type']=='video');a,b=map(int,v['avg_frame_rate'].split('/'));return float(x['format']['duration']),a/b

def evidence(source,out):
    report=read(out/'analysis/content-report.json',{})
    result=[];dest=out/'duplicate-evidence';dest.mkdir(exist_ok=True)
    for i,item in enumerate(report.get('probable_repeated_spoken_sections',[])[:10]):
        row=dict(item);row['clips']=[]
        for k in ['first_second','repeat_second']:
            target=dest/f'{i+1:02d}-{k}.mp4'
            run(['ffmpeg','-nostdin','-y','-v','error','-ss',max(0,item[k]-3),'-i',source,'-t','18','-vf','scale=1280:-2','-c:v','h264_nvenc','-preset','p4','-c:a','aac',target]);row['clips'].append(str(target))
        result.append(row)
    atomic(dest/'index.json',result)
    (dest/'README.txt').write_text('Compare both clips with the original timeline. Matching speech is not proof of a duplicated edit. Do not delete speech automatically.\n')

def validate(t,duration):
    last=0
    for e in sorted(t.get('events',[]),key=lambda x:x['start']):
        if e.get('approved') is not True:raise ValueError('Every timeline event requires explicit editorial approval')
        if not 0<=e['start']<e['end']<=duration or e['start']<last:raise ValueError('Events must be non-overlapping and inside source duration')
        last=e['end']
        if e['kind'] not in ['broll','graph','zoom']:raise ValueError('Unsupported event kind')
        if e['kind']=='zoom' and (e['end']-e['start']<3 or not 1<=e.get('scale',1.04)<=1.08 or not e.get('crop_reviewed')):raise ValueError('Zoom needs reviewed crop, >=3 seconds and scale <=1.08')
        if e['kind']=='graph' and (not e.get('source') or not e.get('unit') or not e.get('data') or not e.get('title')):raise ValueError('Graph needs real labeled data, units, title and source')
        if e['kind']=='broll' and (not e.get('asset') or not e.get('source')):raise ValueError('B-roll needs asset and source/license reference')

def handoff(source,out,t):
    duration,fps=metadata(source);validate(t,duration)
    import opentimelineio as otio
    rate=otio.opentime.RationalTime
    timeline=otio.schema.Timeline(name=source.parent.name)
    track=otio.schema.Track(name='Original picture and linked sound')
    clip=otio.schema.Clip(name=source.name,media_reference=otio.schema.ExternalReference(target_url=str(source.resolve())),source_range=otio.opentime.TimeRange(rate(0,fps),rate(round(duration*fps),fps)))
    track.append(clip);timeline.tracks.append(track)
    for chapter in t.get('chapters',[]):
        sec=float(chapter['start'])
        if not 0<=sec<duration:raise ValueError('Chapter outside source')
        clip.markers.append(otio.schema.Marker(name=chapter['title'],marked_range=otio.opentime.TimeRange(rate(round(sec*fps),fps),rate(0,fps))))
    timeline.metadata['media01']={'events':t.get('events',[]),'manual_review_required':True,'event_rendering':'JSON events are custom; OTIO contains source and chapter markers only'}
    otio.adapters.write_to_file(timeline,str(out/'source-timeline.otio'))
    restored=otio.adapters.read_from_file(str(out/'source-timeline.otio'))
    if restored.tracks[0][0].media_reference.target_url!=str(source.resolve()):raise RuntimeError('OTIO round trip failed')
    atomic(out/'timeline.json',t)
    (out/'chapters.txt').write_text('\n'.join(f"{int(c['start'])//60:02d}:{int(c['start'])%60:02d} {c['title']}" for c in t.get('chapters',[])))
    (out/'HANDOFF.txt').write_text('Original source preserved. Relink source media on the Mac. OTIO source clip and chapter markers verified by library round trip; DaVinci import must be checked on the Mac. Custom events are rendered by media01 and are not native Resolve effects. Captions are sidecar SRT. Full timeline, political neutrality, spelling and source review are required.\n')

def graph(e,path):
    from PIL import Image,ImageDraw,ImageFont
    im=Image.new('RGB',(3840,2160),'#102132');d=ImageDraw.Draw(im)
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    title=ImageFont.truetype(font,88);body=ImageFont.truetype(font,48)
    rows=e['data']
    if len(rows)>8 or any(not isinstance(x['value'],(int,float)) or x['value']<0 for x in rows):raise ValueError('Graph supports up to 8 nonnegative bars')
    mx=max(x['value'] for x in rows) or 1
    d.text((180,120),e['title'],font=title,fill='white');d.text((180,260),e['unit'],font=body,fill='white')
    for i,x in enumerate(rows):
        y=430+i*160;d.text((180,y),str(x['label'])[:35],font=body,fill='white')
        w=int(1900*x['value']/mx);d.rectangle((1400,y,1400+w,y+70),fill='#44c9c1');d.text((1440+w,y),str(x['value']),font=body,fill='white')
    d.text((180,1950),'Source: '+e['source'][:100],font=body,fill='white');im.save(path)

def render(source,out,t):
    duration,fps=metadata(source);validate(t,duration);events=sorted(t.get('events',[]),key=lambda x:x['start'])
    parts=[];cursor=0
    for e in events:
        if cursor<e['start']:parts.append({'start':cursor,'end':e['start'],'kind':'original'})
        parts.append(e);cursor=e['end']
    if cursor<duration:parts.append({'start':cursor,'end':duration,'kind':'original'})
    chunks=[]
    for i,e in enumerate(parts):
        length=e['end']-e['start'];p=out/f'part-{i:04d}.mp4';chunks.append(p)
        args=['ffmpeg','-nostdin','-y','-v','error'];kind=e['kind']
        if kind=='graph':
            asset=out/f'graph-{i}.png';graph(e,asset);args+=['-loop','1','-i',asset]
        elif kind=='broll':args+=['-stream_loop','-1','-i',e['asset']]
        else:args+=['-ss',e['start'],'-i',source]
        vf='scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2'
        if kind=='zoom':
            # Smooth in and out; original framing restored at both event boundaries.
            n=max(1,round(length*fps)-1);amount=e.get('scale',1.04)-1
            vf+=f",zoompan=z='1+{amount}*pow(sin(PI*on/{n}),2)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=3840x2160:fps={fps}"
        args+=['-t',length,'-an','-vf',vf,'-r',fps,'-c:v','h264_nvenc','-preset','p6','-cq','16','-pix_fmt','yuv420p',p];run(args)
    listing=out/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in chunks))
    run(['ffmpeg','-nostdin','-y','-v','error','-f','concat','-safe','0','-i',listing,'-i',source,'-map','0:v','-map','1:a:0','-c','copy','-t',duration,out/'timeline.partial.mp4'])
    (out/'timeline.partial.mp4').replace(out/'timeline.mp4')

def proxy(source,out):
    run(['ffmpeg','-nostdin','-y','-v','error','-hwaccel','cuda','-hwaccel_output_format','cuda','-i',source,'-vf','scale_cuda=1280:720','-c:v','h264_nvenc','-preset','p4','-cq','25','-c:a','aac','-b:a','128k',out/'proxy.partial.mp4'])
    (out/'proxy.partial.mp4').replace(out/'proxy-720p.mp4')
    duration,_=metadata(source)
    run(['ffmpeg','-nostdin','-y','-v','error','-i',source,'-vf',f'fps=1/{max(1,duration/24)},scale=480:-2,tile=4x6','-frames:v','1',out/'contact-sheet.jpg'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['evidence','handoff','render','proxy']);p.add_argument('source',type=Path);p.add_argument('out',type=Path);p.add_argument('--timeline',type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    t=read(a.timeline,{}) if a.timeline else {}
    if a.action=='evidence':evidence(a.source,a.out)
    elif a.action=='handoff':handoff(a.source,a.out,t)
    elif a.action=='render':render(a.source,a.out,t)
    else:proxy(a.source,a.out)
