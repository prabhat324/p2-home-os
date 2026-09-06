#!/usr/bin/env python3
"""Create speaker-aware ASS captions for fixed left/right two-person podcasts.

Speaker attribution prefers lower-face/mouth motion detected from the fixed camera shot. It falls
back to configured left/right regions when face detection is unavailable. This reduces false speaker
switches caused by hand gestures and upper-body movement.
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
                p=ws[i:i+maximum]
                text=' '.join(x['word'].strip() for x in p).strip()
                if text: out.append({'start':float(p[0]['start']),'end':float(p[-1]['end']),'text':text})
        elif seg.get('text'):
            out.append({'start':float(seg['start']),'end':float(seg['end']),'text':seg['text'].strip()})
    return [x for x in out if x['end']>x['start'] and x['text']]


def roi_pixels(spec,w,h):
    x0,y0,x1,y1=spec
    return max(0,int(x0*w)),max(0,int(y0*h)),min(w,int(x1*w)),min(h,int(y1*h))


def clamp_box(box,w,h):
    x0,y0,x1,y1=box
    return max(0,int(x0)),max(0,int(y0)),min(w,int(x1)),min(h,int(y1))


def face_motion_regions(video,cfg,w,h):
    fallback={
        'left': {'mouth':roi_pixels(cfg.get('left_roi',[0.10,0.12,0.46,0.50]),w,h),'upper':None},
        'right':{'mouth':roi_pixels(cfg.get('right_roi',[0.54,0.12,0.90,0.50]),w,h),'upper':None},
        'mode':'configured-fallback'
    }
    if not bool(cfg.get('face_motion_detection',True)):
        return fallback
    try:
        import cv2
        cascade=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
        if cascade.empty(): return fallback
        scan_seconds=float(cfg.get('face_scan_seconds',30.0));fps=float(cfg.get('face_scan_fps',1.0));frame_bytes=w*h
        cmd=['ffmpeg','-nostdin','-v','error','-t',str(scan_seconds),'-i',str(video),'-vf',f'fps={fps},scale={w}:{h},format=gray','-f','rawvideo','-pix_fmt','gray','pipe:1']
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        boxes={'left':[],'right':[]}
        try:
            while True:
                raw=p.stdout.read(frame_bytes)
                if not raw: break
                if len(raw)!=frame_bytes: break
                frame=np.frombuffer(raw,dtype=np.uint8).reshape(h,w)
                faces=cascade.detectMultiScale(frame,scaleFactor=1.1,minNeighbors=4,minSize=(36,36))
                candidates={'left':[],'right':[]}
                for x,y,bw,bh in faces:
                    side='left' if x+bw/2 < w/2 else 'right'
                    candidates[side].append((x,y,bw,bh))
                for side in ('left','right'):
                    if candidates[side]:
                        boxes[side].append(max(candidates[side],key=lambda b:b[2]*b[3]))
        finally:
            if p.stdout: p.stdout.close()
        if p.stderr: p.stderr.read()
        p.wait()
        regions={'mode':'face-mouth'}
        for side in ('left','right'):
            if len(boxes[side])<2:
                regions[side]=fallback[side]
                continue
            arr=np.array(boxes[side],dtype=float)
            x,y,bw,bh=np.median(arr,axis=0)
            mouth=clamp_box((x+0.12*bw,y+0.48*bh,x+0.88*bw,y+1.00*bh),w,h)
            upper=clamp_box((x+0.12*bw,y+0.05*bh,x+0.88*bw,y+0.46*bh),w,h)
            regions[side]={'mouth':mouth,'upper':upper,'detections':len(boxes[side]),'face':[round(float(v),1) for v in (x,y,bw,bh)]}
        return regions
    except Exception as exc:
        fallback['face_detection_error']=str(exc)
        return fallback


def motion_value(diff,box):
    x0,y0,x1,y1=box
    region=diff[y0:y1,x0:x1]
    if region.size==0:return 0.0
    return float(np.percentile(region,75))


def speech_motion(diff,region):
    mouth=motion_value(diff,region['mouth'])
    upper=motion_value(diff,region['upper']) if region.get('upper') else 0.0
    if region.get('upper'):
        return max(0.0,mouth-0.45*upper),mouth,upper
    return mouth,mouth,0.0


def motion_series(video,cfg):
    fps=float(cfg.get('analysis_fps',5.0));w=int(cfg.get('analysis_width',640));h=int(round(w*9/16));frame_bytes=w*h
    regions=face_motion_regions(video,cfg,w,h)
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
                ls,lm,lu=speech_motion(diff,regions['left']);rs,rm,ru=speech_motion(diff,regions['right'])
                series.append({'t':index/fps,'left':ls,'right':rs,'left_mouth':lm,'right_mouth':rm,'left_upper':lu,'right_upper':ru})
            prev=frame.copy();index+=1
    finally:
        if p.stdout:p.stdout.close()
    err=p.stderr.read().decode('utf-8','replace') if p.stderr else '';rc=p.wait()
    if rc:raise RuntimeError('ffmpeg motion analysis failed: '+err[-1200:])
    if len(series)<10:raise RuntimeError('Too few motion samples for speaker analysis')
    return series,regions


def score_cue(cue,series,pad=.10):
    a=max(0,float(cue['start'])-pad);b=float(cue['end'])+pad;rows=[x for x in series if a<=x['t']<=b]
    if not rows:return None,0.0,0.0,0.0
    l=float(np.median([x['left'] for x in rows]));r=float(np.median([x['right'] for x in rows]));total=l+r+1e-6;conf=abs(l-r)/total
    return ('left' if l>=r else 'right'),conf,l,r


def smooth_turns(cues,cfg):
    isolated=float(cfg.get('isolated_flip_confidence',0.34));short_run=float(cfg.get('short_run_seconds',2.0));short_conf=float(cfg.get('short_run_confidence',0.30))
    for i in range(1,len(cues)-1):
        if cues[i-1]['side']==cues[i+1]['side']!=cues[i]['side'] and cues[i]['speaker_confidence']<isolated:
            cues[i]['side']=cues[i-1]['side'];cues[i]['speaker_repair']='isolated-flip'
    i=0
    while i<len(cues):
        j=i+1
        while j<len(cues) and cues[j]['side']==cues[i]['side']:j+=1
        if i>0 and j<len(cues) and cues[i-1]['side']==cues[j]['side']!=cues[i]['side']:
            duration=cues[j-1]['end']-cues[i]['start'];conf=max(c['speaker_confidence'] for c in cues[i:j])
            if duration<=short_run and conf<short_conf:
                replacement=cues[i-1]['side']
                for c in cues[i:j]:c['side']=replacement;c['speaker_repair']='short-run'
        i=j
    return cues


def pad_caption_timing(cues,cfg):
    bridge=float(cfg.get('bridge_caption_gap_seconds',0.30));tail=float(cfg.get('caption_tail_pad_seconds',0.12));lead=float(cfg.get('caption_lead_pad_seconds',0.04))
    for i,cue in enumerate(cues):
        cue['start']=max(0.0,float(cue['start'])-lead)
        original_end=float(cue['end']);target=original_end+tail
        if i+1<len(cues):
            next_start=float(cues[i+1]['start'])
            if 0<=next_start-original_end<=bridge: target=next_start
            else: target=min(target,max(original_end,next_start-0.01))
        cue['end']=max(cue['start']+0.05,target)
    return cues


def classify(video,cues,cfg):
    series,regions=motion_series(video,cfg);previous=cfg.get('initial_speaker');previous_end=-999;hold=float(cfg.get('speaker_hold_seconds',2.5));threshold=float(cfg.get('confidence_threshold',0.075))
    for cue in cues:
        side,confidence,l,r=score_cue(cue,series)
        raw_side=side
        if side is None or confidence<threshold:
            if previous and cue['start']-previous_end<=hold:side=previous
            elif previous:side=previous
            else:side='left' if l>=r else 'right'
        cue['raw_side']=raw_side;cue['side']=side;cue['speaker_confidence']=round(float(confidence),3);cue['motion_left']=round(float(l),3);cue['motion_right']=round(float(r),3)
        previous=side;previous_end=cue['end']
    cues=smooth_turns(cues,cfg)
    cues=pad_caption_timing(cues,cfg)
    return cues,regions


def ass_color(hexcolor,alpha='00'):
    s=str(hexcolor).lstrip('#')
    if len(s)!=6:s='FFFFFF'
    a=str(alpha).upper().replace('0X','').replace('&H','')[-2:].zfill(2)
    r,g,b=s[0:2],s[2:4],s[4:6]
    return f'&H{a}{b}{g}{r}'


def write_ass(path,cues,cfg,width=3840,height=2160):
    left=cfg.get('left',{});right=cfg.get('right',{});lname=left.get('name','Woman');rname=right.get('name','Man')
    text_default=cfg.get('text_color','#000000')
    ltext=ass_color(left.get('text_color',text_default));rtext=ass_color(right.get('text_color',text_default))
    lshadow=left.get('shadow_color',left.get('color','#8EF2A0'));rshadow=right.get('shadow_color',right.get('color','#8FD6FF'))
    shadow_alpha=cfg.get('shadow_alpha','20');outline_alpha=cfg.get('outline_alpha','30')
    lback=ass_color(lshadow,shadow_alpha);rback=ass_color(rshadow,shadow_alpha)
    loutline=ass_color(lshadow,outline_alpha);routline=ass_color(rshadow,outline_alpha)
    font=cfg.get('font','DejaVu Sans');size=int(cfg.get('font_size',72));margin=int(cfg.get('margin_v',50));outline=float(cfg.get('outline',2.8));shadow=float(cfg.get('shadow',4.0));show_names=bool(cfg.get('show_speaker_names',False))
    header=f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Left,{font},{size},{ltext},{ltext},{loutline},{lback},0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\nStyle: Right,{font},{size},{rtext},{rtext},{routline},{rback},0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    rows=[]
    for cue in cues:
        is_left=cue['side']=='left';name=lname if is_left else rname;style='Left' if is_left else 'Right';text=ass_escape(cue['text'])
        if show_names:text='{\\fs48\\b1}'+ass_escape(name).upper()+'{\\r'+style+'}\\N'+text
        rows.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},{style},{ass_escape(name)},0,0,0,,{text}")
    path.write_text(header+'\n'.join(rows)+'\n')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--ass',type=Path,required=True);ap.add_argument('--assignments',type=Path,required=True);args=ap.parse_args()
    transcript=json.loads(args.transcript.read_text());manifest=json.loads(args.manifest.read_text());cfg=manifest.get('podcast_captions',{});cues,regions=classify(args.video,chunks(transcript,int(cfg.get('words_per_caption',12))),cfg)
    args.ass.parent.mkdir(parents=True,exist_ok=True);write_ass(args.ass,cues,cfg)
    gaps=[]
    for a,b in zip(cues,cues[1:]):
        gap=float(b['start'])-float(a['end'])
        if gap>0.35:gaps.append({'start':round(float(a['end']),2),'end':round(float(b['start']),2),'seconds':round(gap,2)})
    payload={'mode':'fixed-left-right-face-mouth-motion','analysis_regions':regions,'caption_gaps_over_0_35s':gaps,'cues':cues};args.assignments.write_text(json.dumps(payload,indent=2))
    print(json.dumps({'captions':len(cues),'left':sum(x['side']=='left' for x in cues),'right':sum(x['side']=='right' for x in cues),'low_confidence':sum(x['speaker_confidence']<float(cfg.get('confidence_threshold',0.075)) for x in cues),'caption_gaps_over_0_35s':len(gaps),'analysis_mode':regions.get('mode'),'ass':str(args.ass)},indent=2))
if __name__=='__main__':main()
