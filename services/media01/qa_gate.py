#!/usr/bin/env python3
import argparse,json,math,re,subprocess,sys
from pathlib import Path

def run(cmd):return subprocess.run(cmd,text=True,capture_output=True,check=False)
def probe(path):
    p=run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)])
    if p.returncode:raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout)
def rational(value):
    a,b=value.split('/');return float(a)/float(b) if float(b) else 0.0

def visual_hashes(path):
    cmd=['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vf','blackdetect=d=0.75:pix_th=0.10,freezedetect=n=-50dB:d=2,fps=1,scale=9:8,format=gray','-f','rawvideo','-']
    p=subprocess.run(cmd,capture_output=True,check=False)
    if p.returncode:raise RuntimeError('Video QA failed: '+p.stderr.decode(errors='replace')[-2000:])
    frame_size=9*8
    frames=[p.stdout[i:i+frame_size] for i in range(0,len(p.stdout)-frame_size+1,frame_size)]
    hashes=[]
    for frame in frames:
        value=0;bit=0
        for y in range(8):
            row=frame[y*9:(y+1)*9]
            for x in range(8):
                value|=(1 if row[x]>row[x+1] else 0)<<bit;bit+=1
        hashes.append(value)
    return hashes,p.stderr.decode(errors='replace')

def repeated_from_hashes(hashes,seconds=5):
    seen,repeats={},[]
    for i in range(0,max(0,len(hashes)-seconds+1)):
        sig=tuple(hashes[i:i+seconds]);previous=seen.get(sig)
        if previous is None:
            seen[sig]=i
        elif i-previous>=seconds+5:
            repeats.append({'first_second':previous,'repeat_second':i,'seconds':seconds})
    return repeats[:50]

def repeated_sequences(path,seconds=5):
    hashes,log=visual_hashes(path)
    return repeated_from_hashes(hashes,seconds),log,hashes

def parse_visual_log(log):
    black=[{'start':float(a),'end':float(b),'duration':float(c)} for a,b,c in re.findall(r'black_start:([0-9.]+).*?black_end:([0-9.]+).*?black_duration:([0-9.]+)',log)]
    starts=[float(x) for x in re.findall(r'freeze_start: ([0-9.]+)',log)]
    durations=[float(x) for x in re.findall(r'freeze_duration: ([0-9.]+)',log)]
    freezes=[]
    for i,d in enumerate(durations):
        s=starts[i] if i<len(starts) else None
        freezes.append({'start':s,'duration':d})
    return black,freezes

def visual_signals(path,seconds):
    repeats,log,hashes=repeated_sequences(path,seconds)
    black,freezes=parse_visual_log(log)
    return {'black_segments':black,'freeze_events':freezes,'repeated_sequences':repeats},hashes

def new_events(output_events,source_events,keys,tolerance):
    new=[]
    for event in output_events:
        matched=False
        for base in source_events:
            ok=True
            for key in keys:
                a=event.get(key);b=base.get(key)
                if a is None or b is None or abs(float(a)-float(b))>tolerance:ok=False;break
            if ok:matched=True;break
        if not matched:new.append(event)
    return new

def repeat_event_present_in_source(event,source_hashes,seconds,tolerance,max_mean_hamming=8.0,max_frame_hamming=14):
    """Verify an output repeat against the source at the same timeline positions.

    Independent repeated-sequence detection can pair the same lossy-transcoded scene
    differently. This check asks the safer question: were the two output-repeated
    timeline regions already perceptually similar in the source?
    """
    first=int(round(float(event.get('first_second',-1))));repeat=int(round(float(event.get('repeat_second',-1))))
    radius=max(0,int(math.ceil(float(tolerance))))
    for df in range(-radius,radius+1):
        for dr in range(-radius,radius+1):
            a=first+df;b=repeat+dr
            if a<0 or b<0 or a+seconds>len(source_hashes) or b+seconds>len(source_hashes):continue
            distances=[(int(source_hashes[a+i])^int(source_hashes[b+i])).bit_count() for i in range(seconds)]
            if distances and max(distances)<=max_frame_hamming and sum(distances)/len(distances)<=max_mean_hamming:return True
    return False

def loudness(path):
    p=run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vn','-af','loudnorm=I=-14:TP=-1:LRA=11:print_format=json','-f','null','-'])
    if p.returncode:raise RuntimeError('Audio QA failed: '+p.stderr[-2000:])
    blocks=re.findall(r'\{\s*"input_i".*?\}',p.stderr,re.S)
    if not blocks:raise RuntimeError('Audio QA produced no measurement')
    return json.loads(blocks[-1])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--source',type=Path);ap.add_argument('--profile',type=Path,default=Path(__file__).with_name('quality-profile.json'));ap.add_argument('--report',type=Path);args=ap.parse_args()
    cfg=json.loads(args.profile.read_text());info=probe(args.video)
    videos=[s for s in info['streams'] if s.get('codec_type')=='video'];audios=[s for s in info['streams'] if s.get('codec_type')=='audio']
    failures,warnings=[],[]
    if not videos:failures.append('No video stream')
    if not audios:failures.append('No audio stream')
    if videos:
        v=videos[0]
        if int(v.get('width',0))<cfg['delivery']['width'] or int(v.get('height',0))<cfg['delivery']['height']:failures.append(f"Resolution is {v.get('width')}x{v.get('height')}, below required 3840x2160")
        ratio=int(v.get('width',0))/max(int(v.get('height',1)),1)
        if abs(ratio-16/9)>0.01:failures.append(f'Aspect ratio {ratio:.4f} is not 16:9')
        fps=rational(v.get('avg_frame_rate','0/1'))
        if fps<23 or fps>61:warnings.append(f'Unusual frame rate: {fps:.3f}')
    if audios:
        a=audios[0]
        if int(a.get('sample_rate',0))!=cfg['delivery']['audio_sample_rate']:failures.append(f"Audio sample rate is {a.get('sample_rate')}, expected 48000")
        if int(a.get('channels',0))!=cfg['delivery']['audio_channels']:warnings.append(f"Audio has {a.get('channels')} channel(s), delivery target is stereo")
    repeat_seconds=int(cfg['qa_gates']['fail_on_probable_repeated_sequence_seconds'])
    output_visual,output_hashes=visual_signals(args.video,repeat_seconds)
    baseline=None
    if args.source:
        source_visual,source_hashes=visual_signals(args.source,repeat_seconds)
        tol=float(cfg.get('autonomy',{}).get('visual_baseline_tolerance_seconds',1.5))
        new_black=new_events(output_visual['black_segments'],source_visual['black_segments'],['start','duration'],tol)
        new_freeze=new_events(output_visual['freeze_events'],source_visual['freeze_events'],['start','duration'],tol)
        candidate_new_repeats=new_events(output_visual['repeated_sequences'],source_visual['repeated_sequences'],['first_second','repeat_second'],tol)
        perceptually_inherited=[];new_repeats=[]
        mean_hamming=float(cfg.get('autonomy',{}).get('visual_repeat_source_mean_hamming_max',8.0))
        frame_hamming=int(cfg.get('autonomy',{}).get('visual_repeat_source_frame_hamming_max',14))
        for event in candidate_new_repeats:
            if repeat_event_present_in_source(event,source_hashes,repeat_seconds,tol,mean_hamming,frame_hamming):perceptually_inherited.append(event)
            else:new_repeats.append(event)
        inherited={k:max(0,len(output_visual[k])-len(v)) for k,v in [('black_segments',new_black),('freeze_events',new_freeze),('repeated_sequences',new_repeats)]}
        if inherited['black_segments']:warnings.append(f"{inherited['black_segments']} black segment(s) are inherited from the source")
        if inherited['freeze_events']:warnings.append(f"{inherited['freeze_events']} freeze event(s) are inherited from the source")
        if inherited['repeated_sequences']:warnings.append(f"{inherited['repeated_sequences']} repeated visual sequence(s) are inherited from the source")
        if perceptually_inherited:warnings.append(f"{len(perceptually_inherited)} repeat pairing difference(s) verified against source timeline")
        if new_black:failures.append(f'Detected {len(new_black)} new black segment(s) introduced after source')
        if new_freeze:failures.append(f'Detected {len(new_freeze)} new freeze event(s) introduced after source')
        if new_repeats:failures.append(f'Detected {len(new_repeats)} new probable repeated sequence(s) introduced after source')
        baseline={'source':str(args.source),'tolerance_seconds':tol,'source_counts':{k:len(v) for k,v in source_visual.items()},'output_counts':{k:len(v) for k,v in output_visual.items()},'new':{'black_segments':new_black,'freeze_events':new_freeze,'repeated_sequences':new_repeats},'perceptually_inherited_repeats':perceptually_inherited,'inherited_counts':inherited}
    else:
        if output_visual['black_segments']:failures.append(f"Detected {len(output_visual['black_segments'])} black segment(s) >= 0.75s")
        if output_visual['freeze_events']:failures.append(f"Detected {len(output_visual['freeze_events'])} freeze event(s) >= 2s; review intentional stills")
        if output_visual['repeated_sequences']:failures.append(f"Detected {len(output_visual['repeated_sequences'])} probable non-consecutive repeated sequence(s); review static scenes")
    audio=loudness(args.video) if audios else {}
    if audio:
        measured=float(audio.get('input_i',-99));peak=float(audio.get('input_tp',99));target=cfg['delivery']['integrated_loudness_lufs'];tol=cfg['delivery']['loudness_tolerance_lu']
        if abs(measured-target)>tol:failures.append(f'Integrated loudness {measured:.1f} LUFS is outside {target:.1f}±{tol:.1f}')
        if peak>cfg['delivery']['true_peak_max_dbtp']:failures.append(f'True peak {peak:.1f} dBTP exceeds {cfg["delivery"]["true_peak_max_dbtp"]:.1f} dBTP')
    report={'profile':cfg['profile'],'file':str(args.video),'status':'PASS' if not failures else 'FAIL','failures':failures,'warnings':warnings,'probe':info,'loudness':audio,'visual_signals':output_visual,'visual_baseline':baseline,'manual_gates':['Full timeline review completed','No cropped faces, text, or source material','Captions remain in bottom safe area and do not cover content','All zooms are slow, eased, and editorially motivated','No repeated footage or duplicated spoken section','Every graph communicates real labeled data and cites its source','Names, numbers, quotations, dates, and protected terms verified','Political presentation remains neutral and avoids gotcha editing']}
    out=args.report or args.video.with_suffix('.qa.json');out.write_text(json.dumps(report,indent=2));print(json.dumps({'status':report['status'],'report':str(out),'failures':failures,'warnings':warnings},indent=2));return 0 if not failures else 2

if __name__=='__main__':sys.exit(main())
