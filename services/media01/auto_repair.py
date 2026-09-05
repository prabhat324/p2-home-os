#!/usr/bin/env python3
"""Bounded, non-destructive QA repairs for media-01 review exports."""
import argparse,json,subprocess
from pathlib import Path

AUDIO_FAILURE_PREFIXES=("True peak ","Integrated loudness ")

def read_json(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (FileNotFoundError,json.JSONDecodeError):return default

def classify_failures(failures):
    audio=[f for f in failures if f.startswith(AUDIO_FAILURE_PREFIXES)]
    other=[f for f in failures if f not in audio]
    return audio,other

def probe_duration(path):
    return float(subprocess.check_output([
        'ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)
    ],text=True,timeout=30).strip())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('video',type=Path)
    ap.add_argument('--qa-report',type=Path,required=True)
    ap.add_argument('--profile',type=Path,required=True)
    ap.add_argument('--attempt',type=int,default=1)
    ap.add_argument('--result',type=Path,required=True)
    args=ap.parse_args()
    qa=read_json(args.qa_report,{}) or {}
    cfg=read_json(args.profile,{}) or {}
    failures=qa.get('failures',[])
    audio,other=classify_failures(failures)
    result={'changed':False,'attempt':args.attempt,'failures':failures,'audio_failures':audio,'unhandled_failures':other}
    if not audio or other:
        args.result.write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2));return 0
    autonomy=cfg.get('autonomy',{})
    base_target=float(autonomy.get('audio_true_peak_repair_target_dbtp',-2.5))
    floor=float(autonomy.get('audio_true_peak_repair_floor_dbtp',-4.0))
    target=max(floor,base_target-0.5*max(0,args.attempt-1))
    loudness=float(cfg.get('delivery',{}).get('integrated_loudness_lufs',-14.0))
    old_duration=probe_duration(args.video)
    partial=args.video.with_name(args.video.stem+'.auto-repair.partial'+args.video.suffix)
    partial.unlink(missing_ok=True)
    af=f'loudnorm=I={loudness}:TP={target}:LRA=11:linear=false'
    cmd=['ffmpeg','-nostdin','-hide_banner','-y','-i',str(args.video),'-map','0:v:0','-map','0:a:0','-c:v','copy','-af',af,'-c:a','aac','-b:a','320k','-ar','48000','-ac','2','-movflags','+faststart',str(partial)]
    p=subprocess.run(cmd,text=True)
    if p.returncode:
        partial.unlink(missing_ok=True);raise SystemExit(p.returncode)
    new_duration=probe_duration(partial)
    if abs(new_duration-old_duration)>0.25:
        partial.unlink(missing_ok=True);raise RuntimeError(f'Audio repair changed duration: {old_duration} -> {new_duration}')
    partial.replace(args.video)
    result.update(changed=True,repair='audio_loudness_true_peak',target_dbtp=target,old_duration=old_duration,new_duration=new_duration)
    args.result.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
