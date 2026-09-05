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
    report=read(out/'analysis/content-report.json',{});result=[];dest=out/'duplicate-evidence';dest.mkdir(exist_ok=True)
    for i,item in enumerate(report.get('probable_repeated_spoken_sections',[])[:10]):
        row=dict(item);row['clips']=[]
        for k in ['first_second','repeat_second']:
            target=dest/f'{i+1:02d}-{k}.mp4';run(['ffmpeg','-nostdin','-y','-v','error','-ss',max(0,item[k]-3),'-i',source,'-t','18','-vf','scale=1280:-2','-c:v','h264_nvenc','-preset','p4','-c:a','aac',target]);row['clips'].append(str(target))
        result.append(row)
    atomic(dest/'index.json',result);(dest/'README.txt').write_text('Compare both clips with the original timeline. Matching speech is not proof of a duplicated edit. Do not delete speech automatically.\n')

def validate(t,duration):
    last=0;supported={'broll','graph','zoom','fact_card','image','document','newspaper'}
    for e in sorted(t.get('events',[]),key=lambda x:x['start']):
        if e.get('approved') is not True:raise ValueError('Every timeline event requires explicit editorial approval')
        if not 0<=e['start']<e['end']<=duration or e['start']<last:raise ValueError('Events must be non-overlapping and inside source duration')
        last=e['end']
        if e['kind'] not in supported:raise ValueError('Unsupported event kind')
        if e['kind']=='zoom' and (e['end']-e['start']<3 or not 1<=e.get('scale',1.04)<=1.08 or not e.get('crop_reviewed')):raise ValueError('Zoom needs reviewed crop, >=3 seconds and scale <=1.08')
        if e['kind']=='graph' and (not e.get('source') or not e.get('unit') or not e.get('data') or not e.get('title')):raise ValueError('Graph needs real labeled data, units, title and source')
        if e['kind']=='fact_card' and (not e.get('source') or not e.get('title')):raise ValueError('Fact card needs title and source')
        if e['kind'] in {'broll','image'} and (not e.get('asset') or not e.get('source')):raise ValueError('Visual asset needs asset path and source/license reference')
        if e['kind'] in {'document','newspaper'} and (not e.get('source') or (not e.get('asset') and not e.get('title'))):raise ValueError('Document/newspaper treatment needs source plus asset or sourced title')

def handoff(source,out,t):
    duration,fps=metadata(source);validate(t,duration)
    import opentimelineio as otio
    rate=otio.opentime.RationalTime;timeline=otio.schema.Timeline(name=source.parent.name);track=otio.schema.Track(name='Original picture and linked sound');clip=otio.schema.Clip(name=source.name,media_reference=otio.schema.ExternalReference(target_url=str(source.resolve())),source_range=otio.opentime.TimeRange(rate(0,fps),rate(round(duration*fps),fps)));track.append(clip);timeline.tracks.append(track)
    for chapter in t.get('chapters',[]):
        sec=float(chapter['start'])
        if not 0<=sec<duration:raise ValueError('Chapter outside source')
        clip.markers.append(otio.schema.Marker(name=chapter['title'],marked_range=otio.opentime.TimeRange(rate(round(sec*fps),fps),rate(0,fps))))
    timeline.metadata['media01']={'events':t.get('events',[]),'manual_review_required':True,'event_rendering':'JSON events are custom; OTIO contains source and chapter markers only'};otio.adapters.write_to_file(timeline,str(out/'source-timeline.otio'));restored=otio.adapters.read_from_file(str(out/'source-timeline.otio'))
    if restored.tracks[0][0].media_reference.target_url!=str(source.resolve()):raise RuntimeError('OTIO round trip failed')
    atomic(out/'timeline.json',t);(out/'chapters.txt').write_text('\n'.join(f"{int(c['start'])//60:02d}:{int(c['start'])%60:02d} {c['title']}" for c in t.get('chapters',[])));(out/'HANDOFF.txt').write_text('Original source preserved. Relink source media on the Mac. OTIO source clip and chapter markers verified by library round trip; DaVinci import must be checked on the Mac. Custom events are rendered by media01 and are not native Resolve effects. Full timeline, political neutrality, spelling and source review are required.\n')

def font(path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',size=48):
    from PIL import ImageFont
    return ImageFont.truetype(path,size)
def wrap(text,limit):
    out=[];line=[]
    for w in str(text).split():
        if len(' '.join(line+[w]))>limit and line:out.append(' '.join(line));line=[w]
        else:line.append(w)
    if line:out.append(' '.join(line))
    return out

def graph(e,path):
    from PIL import Image,ImageDraw
    im=Image.new('RGB',(3840,2160),'#102132');d=ImageDraw.Draw(im);title=font(size=88);body=font(size=48);rows=e['data']
    if len(rows)>8 or any(not isinstance(x['value'],(int,float)) or x['value']<0 for x in rows):raise ValueError('Graph supports up to 8 nonnegative bars')
    mx=max(x['value'] for x in rows) or 1;d.text((180,120),e['title'],font=title,fill='white');d.text((180,260),e['unit'],font=body,fill='white')
    for i,x in enumerate(rows):
        y=430+i*160;d.text((180,y),str(x['label'])[:35],font=body,fill='white');w=int(1900*x['value']/mx);d.rectangle((1400,y,1400+w,y+70),fill='#44c9c1');d.text((1440+w,y),str(x['value']),font=body,fill='white')
    d.text((180,1950),'Source: '+e['source'][:100],font=body,fill='white');im.save(path)

def fact_card(e,path):
    from PIL import Image,ImageDraw
    im=Image.new('RGB',(3840,2160),'#0E1C2A');d=ImageDraw.Draw(im);title=font(size=92);body=font(size=44);d.rounded_rectangle((260,360,3580,1720),radius=60,fill='#152B40',outline='#4A718F',width=4);y=590
    for ln in wrap(e['title'],42)[:4]:d.text((430,y),ln,font=title,fill='white');y+=135
    if e.get('subtitle'):
        for ln in wrap(e['subtitle'],72)[:2]:d.text((430,y+25),ln,font=body,fill='#D7E5EF');y+=70
    d.text((430,1530),'Source: '+str(e['source'])[:105],font=body,fill='#C8D7E4');im.save(path)

def source_card(e,path):
    from PIL import Image,ImageDraw
    paper=e['kind']=='newspaper';bg='#EFE9DC' if paper else '#F4F5F2';ink='#151515';im=Image.new('RGB',(3840,2160),bg);d=ImageDraw.Draw(im);label=font(size=42);headline=font(size=92);body=font(size=48)
    d.rectangle((250,180,3590,1960),outline='#292929',width=5);kicker='SOURCE / ARTICLE' if paper else 'PRIMARY SOURCE / DOCUMENT';d.text((390,300),kicker,font=label,fill='#555555');d.line((390,380,3450,380),fill='#777777',width=3);y=500
    for ln in wrap(e.get('title',''),45)[:4]:d.text((390,y),ln,font=headline,fill=ink);y+=130
    excerpt=e.get('excerpt') or e.get('subtitle') or ''
    if excerpt:
        y+=35
        for ln in wrap(excerpt,90)[:4]:d.text((390,y),ln,font=body,fill='#313131');y+=72
    d.line((390,1710,3450,1710),fill='#888888',width=2);d.text((390,1775),'Source: '+str(e['source'])[:112],font=label,fill='#555555');im.save(path)

def still_card(e,path):
    from PIL import Image,ImageDraw
    src=Path(e['asset']);im=Image.open(src).convert('RGB');im.thumbnail((3280,1640));canvas=Image.new('RGB',(3840,2160),'#101820');x=(3840-im.width)//2;y=(1840-im.height)//2;canvas.paste(im,(x,y));d=ImageDraw.Draw(canvas);body=font(size=42)
    if e.get('caption'):d.text((260,1840),str(e['caption'])[:130],font=body,fill='white')
    label={'newspaper':'Source / article','document':'Source / document','image':'Source / image'}.get(e['kind'],'Source');d.text((260,1940),f"{label}: {str(e['source'])[:110]}",font=body,fill='#C7D5DF');canvas.save(path)

def render(source,out,t):
    duration,fps=metadata(source);validate(t,duration);events=sorted(t.get('events',[]),key=lambda x:x['start']);parts=[];cursor=0
    for e in events:
        if cursor<e['start']:parts.append({'start':cursor,'end':e['start'],'kind':'original'})
        parts.append(e);cursor=e['end']
    if cursor<duration:parts.append({'start':cursor,'end':duration,'kind':'original'})
    chunks=[]
    for i,e in enumerate(parts):
        length=e['end']-e['start'];p=out/f'part-{i:04d}.mp4';chunks.append(p);args=['ffmpeg','-nostdin','-y','-v','error'];kind=e['kind']
        if kind=='graph':asset=out/f'graph-{i}.png';graph(e,asset);args+=['-loop','1','-i',asset]
        elif kind=='fact_card':asset=out/f'fact-{i}.png';fact_card(e,asset);args+=['-loop','1','-i',asset]
        elif kind in {'document','newspaper'} and not e.get('asset'):asset=out/f'source-{i}.png';source_card(e,asset);args+=['-loop','1','-i',asset]
        elif kind in {'image','document','newspaper'}:asset=out/f'still-{i}.png';still_card(e,asset);args+=['-loop','1','-i',asset]
        elif kind=='broll':args+=['-stream_loop','-1','-i',e['asset']]
        else:args+=['-ss',e['start'],'-i',source]
        vf='scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2'
        if kind=='zoom':
            n=max(1,round(length*fps)-1);amount=e.get('scale',1.04)-1;vf+=f",zoompan=z='1+{amount}*pow(sin(PI*on/{n}),2)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=3840x2160:fps={fps}"
        args+=['-t',length,'-an','-vf',vf,'-r',fps,'-c:v','h264_nvenc','-preset','p6','-cq','16','-pix_fmt','yuv420p',p];run(args)
    listing=out/'parts.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in chunks));run(['ffmpeg','-nostdin','-y','-v','error','-f','concat','-safe','0','-i',listing,'-i',source,'-map','0:v','-map','1:a:0','-c','copy','-t',duration,out/'timeline.partial.mp4']);(out/'timeline.partial.mp4').replace(out/'timeline.mp4')

def proxy(source,out):
    run(['ffmpeg','-nostdin','-y','-v','error','-hwaccel','cuda','-hwaccel_output_format','cuda','-i',source,'-vf','scale_cuda=1280:720','-c:v','h264_nvenc','-preset','p4','-cq','25','-c:a','aac','-b:a','128k',out/'proxy.partial.mp4']);(out/'proxy.partial.mp4').replace(out/'proxy-720p.mp4');duration,_=metadata(source);run(['ffmpeg','-nostdin','-y','-v','error','-i',source,'-vf',f'fps=1/{max(1,duration/24)},scale=480:-2,tile=4x6','-frames:v','1',out/'contact-sheet.jpg'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['evidence','handoff','render','proxy']);p.add_argument('source',type=Path);p.add_argument('out',type=Path);p.add_argument('--timeline',type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);t=read(a.timeline,{}) if a.timeline else {}
    if a.action=='evidence':evidence(a.source,a.out)
    elif a.action=='handoff':handoff(a.source,a.out,t)
    elif a.action=='render':render(a.source,a.out,t)
    else:proxy(a.source,a.out)
