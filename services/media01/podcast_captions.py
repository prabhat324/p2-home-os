#!/usr/bin/env python3
"""Create speaker-aware ASS captions for fixed left/right two-person podcasts.

Speaker colour is assigned once per transcript/speaker turn, then inherited by every caption chunk
inside that turn. This prevents a hand gesture from changing colour halfway through one sentence.
Optional transcript insertions and speaker overrides provide an auditable human-correction path for
speech that ASR skipped or a turn that was visually ambiguous.
"""
import argparse,copy,json,subprocess
from pathlib import Path
import numpy as np


def ass_time(seconds):
    cs=max(0,round(float(seconds)*100));h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def ass_escape(text):return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')


def insertion_words(start,end,text):
    tokens=str(text).split();dur=max(float(end)-float(start),0.1);out=[]
    for i,token in enumerate(tokens):
        a=float(start)+dur*i/max(len(tokens),1);b=float(start)+dur*(i+1)/max(len(tokens),1)
        out.append({'start':a,'end':b,'word':(' ' if i else '')+token,'probability':1.0,'recovered':True})
    return out


def prepare_transcript(transcript,cfg):
    t=copy.deepcopy(transcript);segments=list(t.get('segments',[]))
    for patch in cfg.get('transcript_insertions',[]):
        start=float(patch['start']);end=float(patch['end']);text=str(patch['text']).strip()
        if not text or end<=start:continue
        # Do not duplicate a patch if a future ASR pass already covers most of this window.
        overlap=sum(max(0,min(end,float(s['end']))-max(start,float(s['start']))) for s in segments)
        if overlap >= 0.65*(end-start):continue
        segments.append({'start':start,'end':end,'text':text,'words':insertion_words(start,end,text),'recovered':True,'recovery_source':patch.get('source','manual-reviewed-audio')})
    segments.sort(key=lambda s:(float(s['start']),float(s['end'])))
    for i,s in enumerate(segments):s['_segment_index']=i
    t['segments']=segments
    return t


def chunks(transcript,maximum=12):
    out=[]
    for seg in transcript.get('segments',[]):
        si=int(seg.get('_segment_index',0));ws=seg.get('words') or []
        if ws:
            for i in range(0,len(ws),maximum):
                p=ws[i:i+maximum];text=' '.join(x['word'].strip() for x in p).strip()
                if text:out.append({'start':float(p[0]['start']),'end':float(p[-1]['end']),'text':text,'segment_index':si,'recovered':bool(seg.get('recovered'))})
        elif seg.get('text'):
            out.append({'start':float(seg['start']),'end':float(seg['end']),'text':seg['text'].strip(),'segment_index':si,'recovered':bool(seg.get('recovered'))})
    return [x for x in out if x['end']>x['start'] and x['text']]


def roi_pixels(spec,w,h):
    x0,y0,x1,y1=spec
    return max(0,int(x0*w)),max(0,int(y0*h)),min(w,int(x1*w)),min(h,int(y1*h))


def motion_series(video,cfg):
    fps=float(cfg.get('analysis_fps',5.0));w=int(cfg.get('analysis_width',640));h=int(round(w*9/16));frame_bytes=w*h
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
    return series,{'mode':'fixed-left-right-turn-motion','left_roi':left,'right_roi':right,'fps':fps}


def score_range(start,end,series,pad=.10):
    a=max(0,float(start)-pad);b=float(end)+pad;rows=[x for x in series if a<=x['t']<=b]
    if not rows:return None,0.0,0.0,0.0
    l=float(np.median([x['left'] for x in rows]));r=float(np.median([x['right'] for x in rows]));conf=abs(l-r)/(l+r+1e-6)
    return ('left' if l>=r else 'right'),conf,l,r


def override_for(start,end,cfg):
    center=(float(start)+float(end))/2
    for ov in cfg.get('speaker_overrides',[]):
        if float(ov['start'])<=center<=float(ov['end']) and ov.get('side') in ('left','right'):
            return ov['side'],ov.get('reason','reviewed speaker turn')
    return None,None


def classify_turns(transcript,cues,series,cfg):
    by_segment={}
    for cue in cues:by_segment.setdefault(cue['segment_index'],[]).append(cue)
    previous=cfg.get('initial_speaker');previous_end=-999.0
    switch_conf=float(cfg.get('turn_switch_confidence',0.28));close_switch_conf=float(cfg.get('close_turn_switch_confidence',0.38));close_gap=float(cfg.get('close_turn_gap_seconds',1.0));low=float(cfg.get('confidence_threshold',0.055))
    turns=[]
    for seg in transcript.get('segments',[]):
        si=int(seg['_segment_index']);start=float(seg['start']);end=float(seg['end']);raw,conf,l,r=score_range(start,end,series)
        side=raw;repair=None;ov,ov_reason=override_for(start,end,cfg)
        if ov:
            side=ov;repair='speaker-override: '+ov_reason
        elif previous:
            gap=start-previous_end
            if raw is None or conf<low:
                side=previous;repair='low-confidence turn continuity'
            elif raw!=previous and (conf<switch_conf or (gap<close_gap and conf<close_switch_conf)):
                side=previous;repair='speaker-turn continuity'
        elif side is None:
            side='right'
        turn={'segment_index':si,'start':start,'end':end,'side':side,'raw_side':raw,'speaker_confidence':round(float(conf),3),'motion_left':round(float(l),3),'motion_right':round(float(r),3),'recovered':bool(seg.get('recovered'))}
        if repair:turn['speaker_repair']=repair
        turns.append(turn)
        for cue in by_segment.get(si,[]):
            cue.update({'side':side,'raw_side':raw,'speaker_confidence':turn['speaker_confidence'],'motion_left':turn['motion_left'],'motion_right':turn['motion_right']})
            if repair:cue['speaker_repair']=repair
        previous=side;previous_end=end
    return turns,cues


def pad_caption_timing(cues,cfg):
    bridge=float(cfg.get('bridge_caption_gap_seconds',0.55));tail=float(cfg.get('caption_tail_pad_seconds',0.12));lead=float(cfg.get('caption_lead_pad_seconds',0.04))
    cues.sort(key=lambda c:(c['start'],c['end']))
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
    manifest=json.loads(args.manifest.read_text());cfg=manifest.get('podcast_captions',{});transcript=prepare_transcript(json.loads(args.transcript.read_text()),cfg);cues=chunks(transcript,int(cfg.get('words_per_caption',8)));series,regions=motion_series(args.video,cfg);turns,cues=classify_turns(transcript,cues,series,cfg);cues=pad_caption_timing(cues,cfg)
    args.ass.parent.mkdir(parents=True,exist_ok=True);write_ass(args.ass,cues,cfg);gaps=[]
    for a,b in zip(cues,cues[1:]):
        gap=float(b['start'])-float(a['end'])
        if gap>0.60:gaps.append({'start':round(float(a['end']),2),'end':round(float(b['start']),2),'seconds':round(gap,2)})
    payload={'mode':'fixed-left-right-speaker-turn-motion','analysis_regions':regions,'turns':turns,'caption_gaps_over_0_60s':gaps,'cues':cues};args.assignments.write_text(json.dumps(payload,indent=2))
    print(json.dumps({'captions':len(cues),'turns':len(turns),'left':sum(x['side']=='left' for x in cues),'right':sum(x['side']=='right' for x in cues),'recovered_captions':sum(bool(x.get('recovered')) for x in cues),'speaker_overrides':sum(str(t.get('speaker_repair','')).startswith('speaker-override') for t in turns),'caption_gaps_over_0_60s':len(gaps),'analysis_mode':regions.get('mode'),'ass':str(args.ass)},indent=2))
if __name__=='__main__':main()
