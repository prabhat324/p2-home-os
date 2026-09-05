#!/usr/bin/env python3
"""Review-only 4K worker. No automatic publication or destructive source edits."""
import argparse,fcntl,glob,hashlib,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
_venv=Path(__file__).resolve().parent/'venv-v2/bin/python'
if _venv.exists() and Path(sys.prefix).name!='venv-v2':os.execv(str(_venv),[str(_venv),__file__,*sys.argv[1:]])
from runtime import atomic,read,stamp,fingerprint,Runner,telemetry
ROOT=Path(os.environ.get('MEDIA01_ROOT','/srv/media-production'))
APP=Path(__file__).resolve().parent
os.environ.setdefault('XDG_CACHE_HOME',str(ROOT/'work/.cache'))
os.environ.setdefault('HF_HOME',str(ROOT/'work/.cache/huggingface'))
libs=glob.glob(str(Path(sys.prefix)/'lib/python*/site-packages/nvidia/*/lib'))
os.environ['LD_LIBRARY_PATH']=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')])
EXT={'.mp4','.mov','.mxf','.mkv','.mts','.m2ts'}
TERMINAL={'BLOCKED_FOR_REVIEW','REVIEW_REQUIRED','QA_FAILED','FAILED_FINAL','BLOCKED_STORAGE','LEGACY_OUTPUT_REVIEW'}

def probe(path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True,timeout=30))
def recipe_key(source,manifest):
    st=source.stat()
    return hashlib.sha256(json.dumps({'source':str(source),'size':st.st_size,'mtime_ns':st.st_mtime_ns,'manifest':manifest,'pipeline':2},sort_keys=True).encode()).hexdigest()
def source_for(job,manifest):
    if manifest.get('source'):
        p=(job/manifest['source']).resolve()
        if not p.is_relative_to(job.resolve()):raise ValueError('Source must be inside job directory')
        return p
    files=sorted(p for p in job.iterdir() if p.suffix.lower() in EXT)
    if len(files)!=1:raise ValueError('Set source in project.json when job has multiple source videos')
    return files[0]

def review_job(job):
    status=ROOT/'logs'/f'{job.name}.status.json'
    manifest=read(job/'project.json',{})
    if manifest.get('ready') is not True:return
    source=source_for(job,manifest);key=recipe_key(source,manifest)
    previous=read(status,{})
    if previous.get('recipe_key')==key:
        if previous.get('state') in TERMINAL:return
        if previous.get('retry_after',0)>time.time():return
    work=ROOT/'work'/job.name;review=ROOT/'review'/job.name
    work.mkdir(parents=True,exist_ok=True);review.mkdir(parents=True,exist_ok=True)
    with (work/'.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        base={'job':job.name,'recipe_key':key,'source':str(source),'attempt':previous.get('attempt',0)+1 if previous.get('recipe_key')==key else 1}
        r=Runner(work,status,base)
        try:
            output=review/'review-4k.mp4'
            if output.exists() and previous.get('recipe_key')!=key:
                r.state('LEGACY_OUTPUT_REVIEW',reason='Existing output preserved; use a new job directory for a revised export');return
            info=probe(source);v=next(s for s in info['streams'] if s['codec_type']=='video');duration=float(info['format']['duration'])
            if not any(s['codec_type']=='audio' for s in info['streams']):raise ValueError('Source audio is required')
            if v.get('color_transfer') in ['smpte2084','arib-std-b67']:
                r.state('BLOCKED_FOR_REVIEW',reason='HDR source needs an explicitly approved color conversion');return
            required=max(20*1024**3,int(source.stat().st_size*2.5))
            if shutil.disk_usage(ROOT).free<required:
                r.state('BLOCKED_STORAGE',required_free_bytes=required);return
            digest=read(work/'source-checksum.json',{})
            if digest.get('recipe_key')!=key:
                r.state('CHECKSUM');digest={'recipe_key':key,'sha256':fingerprint(source)};atomic(work/'source-checksum.json',digest)
            analysis=review/'analysis';analysis.mkdir(exist_ok=True)
            cachekey={'source_sha256':digest['sha256'],'model':manifest.get('transcription_model','large-v3-turbo'),'language':manifest.get('language','en'),'analyzer':2}
            if manifest.get('content_analysis',True):
                if read(analysis/'cache-key.json')!=cachekey:
                    r.run([sys.executable,APP/'content_analyzer.py',source,'--output-dir',analysis,'--model',cachekey['model'],'--language',cachekey['language']],'ANALYZING_CONTENT')
                    atomic(analysis/'cache-key.json',cachekey)
                report=read(analysis/'content-report.json',{})
                if report.get('probable_repeated_spoken_sections'):
                    r.run([sys.executable,APP/'editorial.py','evidence',source,review],'BUILDING_REVIEW_EVIDENCE',timeout=600)
                    r.state('BLOCKED_FOR_REVIEW',reason='Probable repeated speech; compare evidence clips before changing source',analysis=str(analysis));return
            # An explicit benchmark may skip editorial analysis, but never receives publish approval.
            timeline=job/'timeline.json'
            r.run([sys.executable,APP/'editorial.py','handoff',source,review,'--timeline',timeline],'BUILDING_HANDOFF',timeout=180)
            render_source=source
            if timeline.exists() and read(timeline,{}).get('events'):
                r.run([sys.executable,APP/'editorial.py','render',source,work,'--timeline',timeline],'RENDERING_TIMELINE',duration)
                render_source=work/'timeline.mp4'
            audio_report=work/'audio-measure.json'
            if not audio_report.exists():
                r.run(['ffmpeg','-hide_banner','-y','-i',render_source,'-vn','-af','loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json','-f','null','-'],'MEASURING_AUDIO',duration)
                import re
                blocks=re.findall(r'\{\s*"input_i".*?\}',(work/'commands.log').read_text(),re.S)
                if not blocks:raise RuntimeError('Audio measurement missing')
                atomic(audio_report,json.loads(blocks[-1]))
            a=read(audio_report)
            # Force dynamic mode in the second pass. Linear gain cannot satisfy the
            # loudness target when the required gain would violate the true-peak
            # ceiling; forcing dynamic mode makes loudnorm enforce TP reliably.
            af='loudnorm=I=-14:TP=-1.5:LRA=11:linear=false:'+':'.join(f'{dst}={a[src]}' for dst,src in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
            partial=review/'review-4k.partial.mp4'
            cmd=['ffmpeg','-hide_banner','-y','-hwaccel','cuda','-hwaccel_output_format','cuda','-i',render_source,'-map','0:v:0','-map','0:a:0']
            if (v['width'],v['height'])!=(3840,2160):
                cmd+=['-vf','scale_cuda=3840:2160:force_original_aspect_ratio=decrease:force_divisible_by=2,pad_cuda=3840:2160:(ow-iw)/2:(oh-ih)/2']
            cmd+=['-c:v','h264_nvenc','-preset','p7','-tune','hq','-rc','vbr','-cq','17','-b:v','35M','-maxrate','55M','-bufsize','110M','-profile:v','high','-fps_mode','passthrough','-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-af',af,'-c:a','aac','-b:a','320k','-ar','48000','-ac','2','-movflags','+faststart',partial]
            r.run(cmd,'RENDERING',duration)
            actual=float(probe(partial)['format']['duration'])
            if abs(actual-duration)>0.25:raise RuntimeError(f'Duration changed: {duration} -> {actual}')
            partial.replace(output)
            r.run([sys.executable,APP/'editorial.py','proxy',output,review],'GENERATING_PROXY',duration)
            try:r.run([sys.executable,APP/'qa_gate.py',output,'--report',review/'qa-report.json'],'QA_RUNNING',duration)
            except RuntimeError:
                qa=read(review/'qa-report.json')
                if qa:r.state('QA_FAILED',failures=qa['failures'],review=str(output));return
                raise
            r.state('REVIEW_REQUIRED',qa='PASS',review=str(output),benchmark_only=manifest.get('purpose')=='benchmark',timings=str(work/'timings.json'),manual_review_required=True)
        except ValueError as e:r.state('FAILED_FINAL',error=str(e))
        except Exception as e:
            attempt=base['attempt'];r.state('FAILED_FINAL' if attempt>=3 else 'RETRY_PENDING',error=str(e),retry_after=time.time()+min(1800,60*2**attempt))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--watch',action='store_true');ap.add_argument('--job');args=ap.parse_args()
    for name in ['logs','work/.cache/huggingface','review']: (ROOT/name).mkdir(parents=True,exist_ok=True)
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    while True:
        atomic(ROOT/'logs/worker-heartbeat.json',{'at':stamp(),'pid':os.getpid(),'pipeline':2})
        for job in sorted((ROOT/'inbox').iterdir()):
            if job.is_dir() and (not args.job or job.name==args.job):
                try:review_job(job)
                except Exception as e:atomic(ROOT/'logs'/f'{job.name}.status.json',{'state':'FAILED_FINAL','error':str(e),'updated_at':stamp()})
        if not args.watch:return
        # bounded rolling idle telemetry; active telemetry is per-job
        atomic(ROOT/'logs/machine-health.json',telemetry())
        time.sleep(10)
if __name__=='__main__':main()
