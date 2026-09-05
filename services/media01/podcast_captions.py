#!/usr/bin/env python3
"""Create speaker-aware ASS captions for fixed left/right two-person podcasts.

Uses transcript word timings plus mouth-region motion to decide which side is speaking.
No cloud service or speaker model is required. The manifest supplies display names/colors.
"""
import argparse,json,math
from pathlib import Path
import cv2


def ass_time(seconds):
    cs=max(0,round(float(seconds)*100));h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def ass_escape(text):
    return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')

def chunks(transcript,maximum=12):
    out=[]
    for seg in transcript.get('segments',[]):
        words=seg.get('words') or []
        if words:
            for i in range(0,len(words),maximum):
                p=words[i:i+maximum]
                out.append({'start':p[0]['start'],'end':p[-1]['end'],'text':' '.join(x['word'].strip() for x in p)})
        elif seg.get('text'):
            out.append({'start':seg['start'],'end':seg['end'],'text':seg['text'].strip()})
    return [x for x in out if x['end']>x['start'] and x['text']]

def detect_pair(frame,cascade):
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    faces=cascade.detectMultiScale(gray,1.1,5,minSize=(80,80))
    if len(faces)<2:return None
    faces=sorted(faces,key=lambda r:r[2]*r[3],reverse=True)[:4]
    faces=sorted(faces,key=lambda r:r[0])
    return faces[0],faces[-1]

def mouth_roi(gray,face):
    x,y,w,h=map(int,face);x0=max(0,x+int(.15*w));x1=min(gray.shape[1],x+int(.85*w));y0=max(0,y+int(.55*h));y1=min(gray.shape[0],y+int(.92*h))
    if x1<=x0 or y1<=y0:return None
    return cv2.resize(gray[y0:y1,x0:x1],(96,48),interpolation=cv2.INTER_AREA)

def side_motion(video,start,end,samples=8):
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS) or 30
    cascade=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    times=[start+(end-start)*(i+1)/(samples+1) for i in range(samples)]
    last={'left':None,'right':None};score={'left':0.0,'right':0.0};seen=0;pair=None
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
        if not ok:continue
        if frame.shape[1]>1280:
            scale=1280/frame.shape[1];frame=cv2.resize(frame,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
        found=detect_pair(frame,cascade)
        if found:pair=found
        if not pair:continue
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        for side,face in zip(('left','right'),pair):
            roi=mouth_roi(gray,face)
            if roi is None:continue
            prev=last[side]
            if prev is not None:score[side]+=float(cv2.absdiff(prev,roi).mean())
            last[side]=roi
        seen+=1
    cap.release()
    if seen<3:return None,0.0
    total=score['left']+score['right']+1e-6
    confidence=abs(score['left']-score['right'])/total
    return ('left' if score['left']>=score['right'] else 'right'),confidence

def classify(video,cues,hold_seconds=2.0):
    previous=None;previous_end=-999
    for cue in cues:
        side,confidence=side_motion(video,max(0,cue['start']-.08),cue['end']+.08)
        if side is None or confidence<0.07:
            side=previous if previous and cue['start']-previous_end<=hold_seconds else ('left' if previous is None else previous)
        cue['side']=side;cue['speaker_confidence']=round(confidence,3)
        previous=side;previous_end=cue['end']
    return cues

def bgr_to_ass(hexcolor):
    s=hexcolor.lstrip('#')
    if len(s)!=6:return '&H00FFFFFF'
    r,g,b=s[0:2],s[2:4],s[4:6]
    return f'&H00{b}{g}{r}'

def write_ass(path,cues,cfg,width=3840,height=2160):
    left=cfg.get('left',{});right=cfg.get('right',{})
    lname=left.get('name','Woman');rname=right.get('name','Man')
    lcolor=bgr_to_ass(left.get('color','#7DFF95'));rcolor=bgr_to_ass(right.get('color','#83D9FF'))
    font=cfg.get('font','DejaVu Sans');size=int(cfg.get('font_size',78));margin=int(cfg.get('margin_v',115));outline=float(cfg.get('outline',2.2));shadow=float(cfg.get('shadow',3.2))
    header=f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Left,{font},{size},{lcolor},{lcolor},&H7A000000,&H50000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\nStyle: Right,{font},{size},{rcolor},{rcolor},&H7A000000,&H50000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    rows=[]
    for cue in cues:
        is_left=cue['side']=='left';name=lname if is_left else rname;style='Left' if is_left else 'Right'
        # Speaker name is intentionally small and on the first line so color itself remains the primary cue.
        text='{\\fs52\\b1}'+ass_escape(name).upper()+'{\\r'+style+'}\\N'+ass_escape(cue['text'])
        rows.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},{style},{ass_escape(name)},0,0,0,,{text}")
    path.write_text(header+'\n'.join(rows)+'\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--ass',type=Path,required=True);ap.add_argument('--assignments',type=Path,required=True);args=ap.parse_args()
    transcript=json.loads(args.transcript.read_text());manifest=json.loads(args.manifest.read_text());cfg=manifest.get('podcast_captions',{})
    cues=classify(args.video,chunks(transcript,int(cfg.get('words_per_caption',12))))
    args.ass.parent.mkdir(parents=True,exist_ok=True);write_ass(args.ass,cues,cfg)
    args.assignments.write_text(json.dumps({'mode':'fixed-left-right-mouth-motion','cues':cues},indent=2))
    print(json.dumps({'captions':len(cues),'left':sum(x['side']=='left' for x in cues),'right':sum(x['side']=='right' for x in cues),'ass':str(args.ass)},indent=2))
if __name__=='__main__':main()
