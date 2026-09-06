#!/usr/bin/env python3
"""Create speaker-aware ASS captions for a fixed left/right two-person podcast.

For long-form runs, speaker attribution combines screen-side motion with a stereo audio signature
calibrated from reviewed speaker windows. Colour is assigned per detected speaker turn and inherited
by all caption chunks in that turn. Reviewed overrides remain available for known ambiguous windows.
"""
import argparse,copy,json,math,subprocess
from pathlib import Path
import numpy as np


def ass_time(seconds):
    cs=max(0,round(float(seconds)*100));h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def ass_escape(text):return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')


def prepare_transcript(transcript,cfg):
    t=copy.deepcopy(transcript);segments=sorted(list(t.get('segments',[])),key=lambda s:(float(s['start']),float(s['end'])))
    for i,s in enumerate(segments):s['_segment_index']=i
    t['segments']=segments
    return t


def build_turns(transcript,cfg):
    split_gap=float(cfg.get('turn_gap_split_seconds',0.55));turns=[];tid=0
    for seg in transcript.get('segments',[]):
        ws=list(seg.get('words') or [])
        if not ws:
            if seg.get('text'):
                turns.append({'turn_id':tid,'start':float(seg['start']),'end':float(seg['end']),'text':seg['text'].strip(),'words':[],'recovered':bool(seg.get('recovered'))});tid+=1
            continue
        groups=[];current=[]
        for w in ws:
            if current and float(w['start'])-float(current[-1]['end'])>=split_gap:
                groups.append(current);current=[]
            current.append(w)
        if current:groups.append(current)
        for group in groups:
            text=' '.join(w['word'].strip() for w in group).strip()
            if text:
                turns.append({'turn_id':tid,'start':float(group[0]['start']),'end':float(group[-1]['end']),'text':text,'words':group,'recovered':bool(seg.get('recovered'))});tid+=1
    return turns


def chunks(turns,maximum=8):
    out=[]
    for turn in turns:
        ws=turn.get('words') or []
        if ws:
            for i in range(0,len(ws),maximum):
                p=ws[i:i+maximum];text=' '.join(x['word'].strip() for x in p).strip()
                if text:out.append({'start':float(p[0]['start']),'end':float(p[-1]['end']),'text':text,'turn_id':turn['turn_id'],'recovered':turn.get('recovered',False)})
        elif turn.get('text'):
            out.append({'start':turn['start'],'end':turn['end'],'text':turn['text'],'turn_id':turn['turn_id'],'recovered':turn.get('recovered',False)})
    return out


def roi_pixels(spec,w,h):
    x0,y0,x1,y1=spec
    return max(0,int(x0*w)),max(0,int(y0*h)),min(w,int(x1*w)),min(h,int(y1*h))


def motion_series(video,cfg):
    fps=float(cfg.get('analysis_fps',3.0));w=int(cfg.get('analysis_width',480));h=int(round(w*9/16));frame_bytes=w*h
    left=roi_pixels(cfg.get('left_roi',[0.08,0.10,0.47,0.67]),w,h);right=roi_pixels(cfg.get('right_roi',[0.53,0.10,0.92,0.67]),w,h)
    cmd=['ffmpeg','-nostdin','-v','error','-i',str(video),'-vf',f'fps={fps},scale={w}:{h},format=gray','-f','rawvideo','-pix_fmt','gray','pipe:1']
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE);prev=None;series=[];index=0
    try:
        while True:
            raw=p.stdout.read(frame_bytes)
            if not raw:break
            if len(raw)!=frame_bytes:raise RuntimeError('Incomplete raw analysis frame')
            frame=np.frombuffer(raw,dtype=np.uint8).reshape(h,w)
            if prev is not None:
                diff=np.abs(frame.astype(np.int16)-prev.astype(np.int16));lx0,ly0,lx1,ly1=left;rx0,ry0,rx1,ry1=right
                series.append({'t':index/fps,'left':float(diff[ly0:ly1,lx0:lx1].mean()),'right':float(diff[ry0:ry1,rx0:rx1].mean())})
            prev=frame.copy();index+=1
    finally:
        if p.stdout:p.stdout.close()
    err=p.stderr.read().decode('utf-8','replace') if p.stderr else '';rc=p.wait()
    if rc:raise RuntimeError('ffmpeg motion analysis failed: '+err[-1200:])
    if len(series)<10:raise RuntimeError('Too few motion samples for speaker analysis')
    return series,{'mode':'calibrated-audio-visual-turns','left_roi':left,'right_roi':right,'fps':fps}


def load_audio(video,cfg):
    sr=int(cfg.get('audio_analysis_rate',8000))
    raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(video),'-vn','-ac','2','-ar',str(sr),'-f','s16le','pipe:1'])
    x=np.frombuffer(raw,dtype=np.int16)
    if len(x)<sr*2:raise RuntimeError('Too little audio for speaker calibration')
    return x[:len(x)//2*2].reshape(-1,2).astype(np.float32)/32768.0,sr


def feature_range(start,end,motion,audio,sr):
    rows=[x for x in motion if float(start)-.10<=x['t']<=float(end)+.10]
    ml=float(np.median([x['left'] for x in rows])) if rows else 0.0;mr=float(np.median([x['right'] for x in rows])) if rows else 0.0
    vr=math.log((ml+0.02)/(mr+0.02))
    a=max(0,int(float(start)*sr));b=min(len(audio),int(float(end)*sr));chunk=audio[a:b]
    if len(chunk):
        rms=np.sqrt(np.mean(chunk*chunk,axis=0)+1e-12);db=20*np.log10(rms+1e-12);ar=float(db[0]-db[1]);ldb=float(db[0]);rdb=float(db[1])
    else:ar=0.0;ldb=rdb=-120.0
    return {'visual_ratio':vr,'audio_lr_db':ar,'motion_left':ml,'motion_right':mr,'audio_left_db':ldb,'audio_right_db':rdb}


def calibration(cfg,motion,audio,sr):
    spans=cfg.get('speaker_calibration',{});centroids={}
    for side in ('left','right'):
        feats=[]
        for span in spans.get(side,[]):
            feats.append(feature_range(float(span['start']),float(span['end']),motion,audio,sr))
        if feats:
            centroids[side]={'visual_ratio':float(np.median([f['visual_ratio'] for f in feats])),'audio_lr_db':float(np.median([f['audio_lr_db'] for f in feats])),'samples':len(feats)}
    return centroids


def override_for(start,end,cfg):
    center=(float(start)+float(end))/2
    for ov in cfg.get('speaker_overrides',[]):
        if float(ov['start'])<=center<=float(ov['end']) and ov.get('side') in ('left','right'):
            return ov['side'],ov.get('reason','reviewed speaker turn')
    return None,None


def classify_turns(turns,cues,motion,audio,sr,cfg):
    by_turn={}
    for cue in cues:by_turn.setdefault(cue['turn_id'],[]).append(cue)
    cents=calibration(cfg,motion,audio,sr);previous=cfg.get('initial_speaker');previous_end=-999.0
    uncertain_threshold=float(cfg.get('uncertain_confidence',0.16));close_gap=float(cfg.get('close_turn_gap_seconds',0.9));close_conf=float(cfg.get('close_turn_switch_confidence',0.28));audio_weight=float(cfg.get('audio_weight',0.68));visual_weight=1-audio_weight
    if set(cents)!= {'left','right'}:raise RuntimeError('Both left and right speaker calibration windows are required')
    vscale=max(abs(cents['left']['visual_ratio']-cents['right']['visual_ratio']),0.25);ascale=max(abs(cents['left']['audio_lr_db']-cents['right']['audio_lr_db']),1.5)
    out=[]
    for turn in turns:
        f=feature_range(turn['start'],turn['end'],motion,audio,sr);dist={}
        for side in ('left','right'):
            dv=abs(f['visual_ratio']-cents[side]['visual_ratio'])/vscale;da=abs(f['audio_lr_db']-cents[side]['audio_lr_db'])/ascale
            dist[side]=visual_weight*dv+audio_weight*da
        raw=min(dist,key=dist.get);conf=abs(dist['left']-dist['right'])/(dist['left']+dist['right']+1e-6);side=raw;repair=None
        ov,reason=override_for(turn['start'],turn['end'],cfg)
        if ov:side=ov;repair='speaker-override: '+reason;conf=1.0
        elif previous and side!=previous and (conf<uncertain_threshold or (turn['start']-previous_end<close_gap and conf<close_conf)):
            side=previous;repair='calibrated-turn continuity'
        rec={**turn,'side':side,'raw_side':raw,'speaker_confidence':round(float(conf),3),'distance_left':round(float(dist['left']),3),'distance_right':round(float(dist['right']),3),'visual_ratio':round(f['visual_ratio'],3),'audio_lr_db':round(f['audio_lr_db'],2)}
        if repair:rec['speaker_repair']=repair
        if conf<uncertain_threshold and not ov:rec['uncertain']=True
        out.append(rec)
        for cue in by_turn.get(turn['turn_id'],[]):
            cue.update({'side':side,'raw_side':raw,'speaker_confidence':rec['speaker_confidence'],'audio_lr_db':rec['audio_lr_db'],'visual_ratio':rec['visual_ratio']})
            if repair:cue['speaker_repair']=repair
        previous=side;previous_end=turn['end']
    return out,cues,cents


def pad_caption_timing(cues,cfg):
    bridge=float(cfg.get('bridge_caption_gap_seconds',0.55));tail=float(cfg.get('caption_tail_pad_seconds',0.12));lead=float(cfg.get('caption_lead_pad_seconds',0.04));cues.sort(key=lambda c:(c['start'],c['end']))
    for i,cue in enumerate(cues):
        cue['start']=max(0.0,float(cue['start'])-lead);original_end=float(cue['end']);target=original_end+tail
        if i+1<len(cues):
            next_start=float(cues[i+1]['start']);gap=next_start-original_end
            if 0<=gap<=bridge:target=next_start
            else:target=min(target,max(original_end,next_start-0.01))
        cue['end']=max(cue['start']+0.05,target)
    return cues


def ass_color(hexcolor,alpha='00'):
    s=str(hexcolor).lstrip('#');s=s if len(s)==6 else 'FFFFFF';a=str(alpha).upper().replace('0X','').replace('&H','')[-2:].zfill(2);r,g,b=s[0:2],s[2:4],s[4:6]
    return f'&H{a}{b}{g}{r}'


def write_ass(path,cues,cfg,width=3840,height=2160):
    left=cfg.get('left',{});right=cfg.get('right',{});lname=left.get('name','Woman');rname=right.get('name','Man');text_default=cfg.get('text_color','#000000')
    ltext=ass_color(left.get('text_color',text_default));rtext=ass_color(right.get('text_color',text_default));lshadow=left.get('shadow_color','#8EF2A0');rshadow=right.get('shadow_color','#8FD6FF')
    shadow_alpha=cfg.get('shadow_alpha','20');outline_alpha=cfg.get('outline_alpha','30');lback=ass_color(lshadow,shadow_alpha);rback=ass_color(rshadow,shadow_alpha);loutline=ass_color(lshadow,outline_alpha);routline=ass_color(rshadow,outline_alpha)
    font=cfg.get('font','DejaVu Sans');size=int(cfg.get('font_size',72));margin=int(cfg.get('margin_v',48));outline=float(cfg.get('outline',2.8));shadow=float(cfg.get('shadow',4.0));show_names=bool(cfg.get('show_speaker_names',False))
    header=f"""[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Left,{font},{size},{ltext},{ltext},{loutline},{lback},0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\nStyle: Right,{font},{size},{rtext},{rtext},{routline},{rback},0,0,0,0,100,100,0,0,1,{outline},{shadow},2,220,220,{margin},1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    rows=[]
    for cue in cues:
        is_left=cue['side']=='left';name=lname if is_left else rname;style='Left' if is_left else 'Right';text=ass_escape(cue['text'])
        if show_names:text='{\\fs48\\b1}'+ass_escape(name).upper()+'{\\r'+style+'}\\N'+text
        rows.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},{style},{ass_escape(name)},0,0,0,,{text}")
    path.write_text(header+'\n'.join(rows)+'\n')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--transcript',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--ass',type=Path,required=True);ap.add_argument('--assignments',type=Path,required=True);args=ap.parse_args()
    manifest=json.loads(args.manifest.read_text());cfg=manifest.get('podcast_captions',{});transcript=prepare_transcript(json.loads(args.transcript.read_text()),cfg);turns=build_turns(transcript,cfg);cues=chunks(turns,int(cfg.get('words_per_caption',8)))
    motion,regions=motion_series(args.video,cfg);audio,sr=load_audio(args.video,cfg);turns,cues,cents=classify_turns(turns,cues,motion,audio,sr,cfg);cues=pad_caption_timing(cues,cfg)
    args.ass.parent.mkdir(parents=True,exist_ok=True);write_ass(args.ass,cues,cfg);gaps=[]
    for a,b in zip(cues,cues[1:]):
        gap=float(b['start'])-float(a['end'])
        if gap>0.60:gaps.append({'start':round(float(a['end']),2),'end':round(float(b['start']),2),'seconds':round(gap,2)})
    uncertain=[t for t in turns if t.get('uncertain')]
    payload={'mode':'calibrated-audio-visual-speaker-turns','analysis_regions':regions,'calibration':cents,'turns':turns,'uncertain_turns':uncertain,'caption_gaps_over_0_60s':gaps,'cues':cues};args.assignments.write_text(json.dumps(payload,indent=2))
    print(json.dumps({'captions':len(cues),'turns':len(turns),'left':sum(x['side']=='left' for x in cues),'right':sum(x['side']=='right' for x in cues),'uncertain_turns':len(uncertain),'recovered_captions':sum(bool(x.get('recovered')) for x in cues),'caption_gaps_over_0_60s':len(gaps),'calibration':cents,'analysis_mode':regions.get('mode'),'ass':str(args.ass)},indent=2))
if __name__=='__main__':main()
