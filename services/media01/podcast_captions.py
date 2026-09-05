#!/usr/bin/env python3
"""Create speaker-aware ASS captions for fixed left/right two-person podcasts.

Speaker attribution is determined by one-pass low-resolution motion analysis over configurable
left/right upper-body regions. This avoids cloud diarization and fragile OpenCV face APIs.
"""
import argparse,json,subprocess
from pathlib import Path
import numpy as np


def ass_time(seconds):
    cs=max(0,round(float(seconds)*100));h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"
def ass_escape(text):return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')

def chunks(transcript,maximum=12):
    out=[]
    for seg in transcript.get('segments',[]):
        ws=seg.get('words') or []
        if ws:
            for i in range(0,len(ws),maximum):
                p=ws[i:i+maximum];out.append({'start':float(p[0]['start']),'end':float(p[-1]['end']),'text':' '.join(x['word'].strip() for x in p)})
        elif seg.get('text'):out.append({'start':float(seg['start']),'end':float(seg['end']),'text':seg['text'].strip()})
    return [x for x in out if x['end']>x['start'] and x['text']]

def roi_pixels(spec,w,h):
    x0,y0,x1,y1=spec
    return max(0,int(x0*w)),max(0,int(y0*h)),min(w,int(x1*w)),min(h,int(y1*h))

def motion_series(video,cfg):
    fps=float(cfg.get('analysis_fps',4.0));w=int(cfg.get('analysis_width',640));h=int(round(w*9/16));frame_bytes=w*h
    left=roi_pixels(cfg.get('left_roi',[0.08,0.10,0.47,0.67]),w,h);right=roi_pixels(cfg.get('right_roi',[0.53,0.10,0.92,0.67]),w,h)
    cmd=['ffmpeg','-nostdin','-v','error','-i',str(video),'-vf',f'fps={fps},scale={w}:{h},format=gray','-f','rawvideo','-pix_fmt','gray','pipe:1']
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    prev=None;series=[];index=0
    try:
        while True:
            raw=p.stdout.read(frame_bytes)
            if not raw:break
            if len(raw)!=frame_bytes:raise RuntimeError('Incomplete raw analysis frame')
            frame=np.frombuffer(raw,dtype=np.uint8).reshape(h,w)
            if prev is not None:
                diff=np.abs(frame.astype(np.int16)-prev.astype(np.int16))
                lx0,ly0,lx1,ly1=left;rx0,ry0,rx1,ry1=right
                ls=float(diff[ly0:ly1,lx0:lx1].mean());rs=float(diff[ry0:ry1,rx0:rx1].mean())
                series.append({'t':index/fps,'left':ls,'right':rs})
            prev=frame.copy();index+=1
    finally:
        if p.stdout:p.stdout.close()
    err=p.stderr.read().decode('utf-8','replace') if p.stderr else '';rc=p.wait()
    if rc:raise RuntimeError('ffmpeg motion analysis failed: '+err[-1200:])
    if len(series)<10:raise RuntimeError('Too few motion samples for speaker analysis')
    return series

def score_cue(cue,series,pad=.12):
    a=max(0,float(cue['start'])-pad);b=float(cue['end'])+pad;rows=[x for x in series if a<=x['t']<=b]
    if not rows:return None,0.0,0.0,0.0
    l=float(np.median([x['left'] for x in rows]));r=float(np.median([x['right'] for x in rows]));total=l+r+1e-6;conf=abs(l-r)/total
    return ('left' if l>=r else 'right'),conf,l,r

def classify(video,cues,cfg):
    series=motion_series(video,cfg);previous=None;previous_end=-999;hold=float(cfg.get('speaker_hold_seconds',2.5));threshold=float(cfg.get('confidence_threshold',0.055))
    for cue in cues:
        side,confidence,l,r=score_cue(cue,series)
        if side is None or confidence<threshold:
            if previous and cue['start']-previous_end<=hold:side=previous
            elif previous:side=previous
            else:side='left' if l>=r else 'right'
        cue['side']=side;cue['speaker_confidence']=round(float(confidence),3);cue['motion_left']=round(float(l),3);cue['motion_right']=round(float(r),3)
        previous=side;previous_end=cue['end']
    # Repair isolated one-cue flips surrounded by the other speaker; these are usually gestures.
    for i in range(1,len(cues)-1):
        if cues[i-1]['side']==cues[i+1]['side']!=cues[i]['side'] and cues[i]['speaker_confidence']<0.16:cues[i]['side']=cues[i-1]['side']
    return cues

def bgr_to_ass(hexcolor):
    s=hexcolor.lstrip('#')
    if len(s)!=6:return '&H00FFFFFF'
    r,g,b=s[0:2],s[2:4],s[4:6];return f'&H00{b}{g}{r}'

def write_ass(path,cues,cfg,width=3840,height=2160):
    left=cfg.get('left',{});right=cfg.get('right',{});lname=left.get('name','Woman');rname=right.get('name','Man')
    lcolor=bgr_to_ass(left.get('color','#7DFF95'));rcolor=bgr_to_ass(right.get('color','#83D9FF'))
    font=cfg.get('font','DejaVu Sans');size=int(cfg.get('font_size',78));margin=int(cfg.get('margin_v',115));outline=float(cfg.get('outline',2.2));shadow=float(cfg.get('shadow',3.2))
    header=f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Left,{font},{size},{lcolor},{lcolor},&H7A000000,&H50000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\nStyle: Right,{font},{size},{rcolor},{rcolor},&H7A000000,&H50000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    rows=[]
    for cue in cues:
        is_left=cue['side']=='left';name=lname if is_left else rname;style='Left' if is_left else 'Right';text='{\\fs52\\b1}'+ass_escape(name).upper()+'{\\r'+style+'}\\N'+ass_escape(cue['text'])
        rows.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},{style},{ass_escape(name)},0,0,0,,{text}")
    path.write_text(header+'\n'.join(rows)+'\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--ass',type=Path,required=True);ap.add_argument('--assignments',type=Path,required=True);args=ap.parse_args()
    transcript=json.loads(args.transcript.read_text());manifest=json.loads(args.manifest.read_text());cfg=manifest.get('podcast_captions',{});cues=classify(args.video,chunks(transcript,int(cfg.get('words_per_caption',12))),cfg)
    args.ass.parent.mkdir(parents=True,exist_ok=True);write_ass(args.ass,cues,cfg);payload={'mode':'fixed-left-right-ffmpeg-motion','cues':cues};args.assignments.write_text(json.dumps(payload,indent=2))
    print(json.dumps({'captions':len(cues),'left':sum(x['side']=='left' for x in cues),'right':sum(x['side']=='right' for x in cues),'low_confidence':sum(x['speaker_confidence']<float(cfg.get('confidence_threshold',0.055)) for x in cues),'ass':str(args.ass)},indent=2))
if __name__=='__main__':main()
