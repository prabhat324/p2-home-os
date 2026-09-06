#!/usr/bin/env python3
"""Recover suspicious non-silent transcript gaps with targeted CPU Whisper passes."""
import argparse,json,math,subprocess,tempfile
from pathlib import Path
import numpy as np


def audio_stats(video,start,end):
    dur=max(0.1,end-start)
    cmd=['ffmpeg','-nostdin','-v','error','-ss',str(max(0,start)),'-t',str(dur),'-i',str(video),'-vn','-ac','1','-ar','16000','-f','s16le','pipe:1']
    raw=subprocess.check_output(cmd)
    if not raw:return -120.0,-120.0,b''
    x=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768.0
    rms=float(np.sqrt(np.mean(x*x))+1e-12);peak=float(np.max(np.abs(x))+1e-12)
    return 20*math.log10(rms),20*math.log10(peak),raw


def words_payload(seg,offset,lo,hi):
    out=[]
    for w in (seg.words or []):
        a=offset+float(w.start);b=offset+float(w.end)
        if b < lo or a > hi:continue
        out.append({'start':max(lo,a),'end':min(hi,b),'word':w.word,'probability':float(w.probability),'recovered':True})
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('input',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--report',type=Path,required=True)
    ap.add_argument('--model',default='large-v3-turbo');ap.add_argument('--language',default='en');ap.add_argument('--min-gap',type=float,default=1.8);ap.add_argument('--max-gap',type=float,default=12.0)
    ap.add_argument('--rms-threshold',type=float,default=-43.0);ap.add_argument('--peak-threshold',type=float,default=-27.0);ap.add_argument('--min-word-probability',type=float,default=0.58);ap.add_argument('--max-no-speech',type=float,default=0.45)
    args=ap.parse_args();t=json.loads(args.input.read_text());segments=sorted(t.get('segments',[]),key=lambda s:float(s['start']))
    candidates=[]
    for a,b in zip(segments,segments[1:]):
        start=float(a['end']);end=float(b['start']);gap=end-start
        if args.min_gap<=gap<=args.max_gap:candidates.append((start,end,gap))
    from faster_whisper import WhisperModel
    model=None;recovered=[];rejected=[]
    for start,end,gap in candidates:
        rms,peak,raw=audio_stats(args.video,start,end)
        if rms<args.rms_threshold and peak<args.peak_threshold:
            rejected.append({'start':round(start,2),'end':round(end,2),'seconds':round(gap,2),'reason':'quiet','rms_db':round(rms,1),'peak_db':round(peak,1)});continue
        if model is None:model=WhisperModel(args.model,device='cpu',compute_type='int8')
        pad=.20;lo=max(0,start-pad);hi=end+pad
        with tempfile.NamedTemporaryFile(suffix='.wav') as f:
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-ss',str(lo),'-t',str(hi-lo),'-i',str(args.video),'-vn','-ac','1','-ar','16000',f.name],check=True)
            stream,_=model.transcribe(f.name,language=args.language,beam_size=6,vad_filter=False,condition_on_previous_text=False,word_timestamps=True,temperature=0.0)
            for s in stream:
                text=s.text.strip();ws=words_payload(s,lo,start,end)
                probs=[float(w['probability']) for w in ws]
                avg=float(np.mean(probs)) if probs else 0.0
                ns=float(getattr(s,'no_speech_prob',1.0));seg_start=max(start,lo+float(s.start));seg_end=min(end,lo+float(s.end))
                if text and ws and seg_end>seg_start and avg>=args.min_word_probability and ns<=args.max_no_speech:
                    recovered.append({'start':seg_start,'end':seg_end,'text':' '.join(w['word'].strip() for w in ws).strip(),'words':ws,'recovered':True,'recovery_source':'automatic non-silent gap CPU Whisper','recovery_confidence':round(avg,3),'no_speech_prob':round(ns,3),'gap_window':[start,end]})
                elif text:
                    rejected.append({'start':round(start,2),'end':round(end,2),'seconds':round(gap,2),'reason':'low-confidence-asr','text':text,'avg_word_probability':round(avg,3),'no_speech_prob':round(ns,3),'rms_db':round(rms,1),'peak_db':round(peak,1)})
    merged=segments+recovered;merged.sort(key=lambda s:(float(s['start']),float(s['end'])))
    # Report any still-suspicious non-silent gaps after accepted recovery.
    unresolved=[]
    for a,b in zip(merged,merged[1:]):
        start=float(a['end']);end=float(b['start']);gap=end-start
        if gap<args.min_gap or gap>args.max_gap:continue
        rms,peak,_=audio_stats(args.video,start,end)
        if rms>=args.rms_threshold or peak>=args.peak_threshold:
            unresolved.append({'start':round(start,2),'end':round(end,2),'seconds':round(gap,2),'rms_db':round(rms,1),'peak_db':round(peak,1)})
    t['segments']=merged;t['podcast_gap_recovery']={'candidate_gaps':len(candidates),'recovered_segments':len(recovered),'unresolved_suspect_gaps':unresolved}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(t,indent=2));args.report.write_text(json.dumps({'candidates':len(candidates),'recovered':recovered,'rejected':rejected,'unresolved_suspect_gaps':unresolved},indent=2))
    print(json.dumps({'candidate_gaps':len(candidates),'recovered_segments':len(recovered),'unresolved_suspect_gaps':len(unresolved),'report':str(args.report)},indent=2))

if __name__=='__main__':main()
