#!/usr/bin/env python3
"""Apply reviewed transcript insertions and prefix trims without altering the source media."""
import argparse,json
from pathlib import Path


def words_for(start,end,text):
    toks=text.split();dur=max(end-start,0.1);out=[]
    for i,w in enumerate(toks):
        a=start+dur*i/max(len(toks),1);b=start+dur*(i+1)/max(len(toks),1)
        out.append({'start':a,'end':b,'word':(' ' if i else '')+w,'probability':1.0,'recovered':True})
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('input',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--insert-start',type=float,required=True);ap.add_argument('--insert-end',type=float,required=True);ap.add_argument('--insert-text',required=True)
    ap.add_argument('--trim-segment-start',type=float);ap.add_argument('--trim-through',type=float)
    ap.add_argument('--source-note',default='reviewed targeted ASR recovery')
    args=ap.parse_args()
    t=json.loads(args.input.read_text());segments=[];trimmed=[]
    for raw in t.get('segments',[]):
        s=dict(raw);ws=list(s.get('words') or [])
        if args.trim_segment_start is not None and abs(float(s.get('start',-999))-args.trim_segment_start)<=0.20:
            before=[w for w in ws if float(w.get('end',0))<=float(args.trim_through)]
            ws=[w for w in ws if float(w.get('end',0))>float(args.trim_through)]
            if before:
                trimmed.extend(w.get('word','').strip() for w in before)
                s['words']=ws
                if ws:
                    s['start']=float(ws[0]['start']);s['text']=' '.join(w.get('word','').strip() for w in ws).strip()
                else:
                    continue
                s['reviewed_trim']={'through':args.trim_through,'removed':' '.join(trimmed)}
        segments.append(s)
    recovered={
        'start':args.insert_start,'end':args.insert_end,'text':args.insert_text,
        'words':words_for(args.insert_start,args.insert_end,args.insert_text),'recovered':True,'recovery_source':args.source_note
    }
    segments.append(recovered);segments.sort(key=lambda s:(float(s['start']),float(s['end'])))
    t['segments']=segments;t['reviewed_transcript_patch']={
        'insert':[args.insert_start,args.insert_end,args.insert_text],
        'trim_segment_start':args.trim_segment_start,'trim_through':args.trim_through,'trimmed_words':trimmed,
        'source_note':args.source_note
    }
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(t,indent=2))
    print(json.dumps(t['reviewed_transcript_patch'],indent=2))

if __name__=='__main__':main()
