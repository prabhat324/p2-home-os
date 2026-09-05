#!/usr/bin/env python3
"""Autonomous 4K worker with technical and creative review gates. Never publishes or destructively edits source media."""
import argparse,fcntl,glob,hashlib,json,os,re,shutil,signal,subprocess,sys,time
from pathlib import Path
_venv=Path(__file__).resolve().parent/'venv-v2/bin/python'
if _venv.exists() and Path(sys.prefix).name!='venv-v2':os.execv(str(_venv),[str(_venv),__file__,*sys.argv[1:]])
from runtime import atomic,read,stamp,fingerprint,Runner,telemetry
ROOT=Path(os.environ.get('MEDIA01_ROOT','/srv/media-production'));APP=Path(__file__).resolve().parent
os.environ.setdefault('XDG_CACHE_HOME',str(ROOT/'work/.cache'));os.environ.setdefault('HF_HOME',str(ROOT/'work/.cache/huggingface'))
libs=glob.glob(str(Path(sys.prefix)/'lib/python*/site-packages/nvidia/*/lib'));os.environ['LD_LIBRARY_PATH']=':'.join(libs+[os.environ.get('LD_LIBRARY_PATH','')])
EXT={'.mp4','.mov','.mxf','.mkv','.mts','.m2ts'}
TERMINAL={'BLOCKED_FOR_REVIEW','REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED','QA_REVIEW_REQUIRED','FAILED_FINAL','BLOCKED_STORAGE'}
QA_LOGIC_VERSION=3

def probe(path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True,timeout=30))
def recipe_key(source,manifest):
    st=source.stat();return hashlib.sha256(json.dumps({'source':str(source),'size':st.st_size,'mtime_ns':st.st_mtime_ns,'manifest':manifest,'pipeline':4},sort_keys=True).encode()).hexdigest()
def source_for(job,manifest):
    if manifest.get('source'):
        p=(job/manifest['source']).resolve()
        if not p.is_relative_to(job.resolve()):raise ValueError('Source must be inside job directory')
        return p
    files=sorted(p for p in job.iterdir() if p.suffix.lower() in EXT)
    if len(files)!=1:raise ValueError('Set source in project.json when job has multiple source videos')
    return files[0]
def mode_for(manifest):
    mode=manifest.get('mode','explainer')
    if mode not in {'podcast','explainer','feature'}:raise ValueError(f'Unsupported production mode: {mode}')
    return 'explainer' if mode=='feature' else mode

def qa_with_repairs(r,source,output,review,work,duration,cfg):
    qa_report=review/'qa-report.json';result_path=work/'auto-repair-result.json';maximum=int(cfg.get('autonomy',{}).get('max_auto_repair_attempts',3));repairs=[]
    for index in range(maximum+1):
        try:
            r.run([sys.executable,APP/'qa_gate.py',output,'--source',source,'--profile',APP/'quality-profile.json','--report',qa_report],'QA_RUNNING',duration);return True,repairs
        except RuntimeError:
            qa=read(qa_report,{}) or {}
            if not qa:raise
            if index>=maximum:r.state('QA_REVIEW_REQUIRED',failures=qa.get('failures',[]),review=str(output),auto_repair_attempts=len(repairs),visual_baseline=qa.get('visual_baseline'));return False,repairs
            result_path.unlink(missing_ok=True);r.run([sys.executable,APP/'auto_repair.py',output,'--qa-report',qa_report,'--profile',APP/'quality-profile.json','--attempt',index+1,'--result',result_path],'AUTO_REPAIRING',duration)
            result=read(result_path,{}) or {};repairs.append(result)
            if not result.get('changed'):r.state('QA_REVIEW_REQUIRED',failures=qa.get('failures',[]),review=str(output),auto_repair_attempts=len(repairs),auto_repair=result,visual_baseline=qa.get('visual_baseline'));return False,repairs
    return False,repairs

def creative_gate(r,manifest,timeline,review,assignments=None):
    report=review/'creative-qa.json';cmd=[sys.executable,APP/'creative_qa.py','--manifest',manifest,'--timeline',timeline,'--report',report]
    if assignments:cmd+=['--assignments',assignments]
    try:r.run(cmd,'CREATIVE_QA',timeout=240);return True,read(report,{})
    except RuntimeError:
        q=read(report,{}) or {};r.state('CREATIVE_REVIEW_REQUIRED',creative_qa=q,failures=q.get('failures',[]));return False,q

def finish_review(r,source,output,review,work,duration,cfg,manifest_path,manifest,timeline,assignments=None):
    passed,repairs=qa_with_repairs(r,source,output,review,work,duration,cfg)
    if not passed:return
    creative_ok,creative=creative_gate(r,manifest_path,timeline,review,assignments)
    if not creative_ok:return
    r.run([sys.executable,APP/'editorial.py','proxy',output,review],'GENERATING_PROXY',duration)
    qa=read(review/'qa-report.json',{}) or {}
    r.state('REVIEW_REQUIRED',qa='PASS',creative_qa='PASS',review=str(output),benchmark_only=manifest.get('purpose')=='benchmark',timings=str(work/'timings.json'),manual_review_required=True,auto_repair_attempts=len(repairs),auto_repairs=repairs,visual_baseline=qa.get('visual_baseline'),production_mode=mode_for(manifest))

def build_timeline(r,job,manifest_path,manifest,analysis,work,review,duration):
    explicit=job/'timeline.json';auto=work/'timeline.auto.json';mode=mode_for(manifest)
    if explicit.exists():return explicit
    report=analysis/'content-report.json';transcript=analysis/'transcript.json'
    r.run([sys.executable,APP/'creative_planner.py','--manifest',manifest_path,'--report',report,'--transcript',transcript,'--duration',duration,'--output',auto],'PLANNING_CREATIVE',timeout=180)
    return auto

def review_job(job):
    status=ROOT/'logs'/f'{job.name}.status.json';manifest_path=job/'project.json';manifest=read(manifest_path,{})
    if manifest.get('ready') is not True:return
    source=source_for(job,manifest);key=recipe_key(source,manifest);previous=read(status,{}) or {}
    if previous.get('recipe_key')==key:
        state=previous.get('state');qa_logic_stale=state in {'QA_REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED'} and int(previous.get('qa_logic_version',0) or 0)<QA_LOGIC_VERSION
        if state in TERMINAL and not qa_logic_stale:return
        if previous.get('retry_after',0)>time.time():return
    work=ROOT/'work'/job.name;review=ROOT/'review'/job.name;work.mkdir(parents=True,exist_ok=True);review.mkdir(parents=True,exist_ok=True)
    with (work/'.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        base={'job':job.name,'recipe_key':key,'source':str(source),'attempt':previous.get('attempt',0)+1 if previous.get('recipe_key')==key else 1,'qa_logic_version':QA_LOGIC_VERSION,'production_mode':mode_for(manifest)};r=Runner(work,status,base)
        cfg=read(APP/'quality-profile.json',{}) or {};max_runtime=int(cfg.get('autonomy',{}).get('auto_retry_runtime_failures',3))
        try:
            output=review/'review-4k.mp4';info=probe(source);v=next(s for s in info['streams'] if s['codec_type']=='video');duration=float(info['format']['duration'])
            if not any(s['codec_type']=='audio' for s in info['streams']):raise ValueError('Source audio is required')
            if v.get('color_transfer') in ['smpte2084','arib-std-b67']:r.state('BLOCKED_FOR_REVIEW',reason='HDR source needs an explicitly approved color conversion');return
            required=max(20*1024**3,int(source.stat().st_size*2.5))
            if shutil.disk_usage(ROOT).free<required:r.state('BLOCKED_STORAGE',required_free_bytes=required);return
            digest=read(work/'source-checksum.json',{}) or {}
            if digest.get('recipe_key')!=key:r.state('CHECKSUM');digest={'recipe_key':key,'sha256':fingerprint(source)};atomic(work/'source-checksum.json',digest)
            analysis=review/'analysis';analysis.mkdir(exist_ok=True);cachekey={'source_sha256':digest['sha256'],'model':manifest.get('transcription_model','large-v3-turbo'),'language':manifest.get('language','en'),'analyzer':2}
            if manifest.get('content_analysis',True):
                if read(analysis/'cache-key.json')!=cachekey:
                    r.run([sys.executable,APP/'content_analyzer.py',source,'--output-dir',analysis,'--model',cachekey['model'],'--language',cachekey['language']],'ANALYZING_CONTENT');atomic(analysis/'cache-key.json',cachekey)
                report=read(analysis/'content-report.json',{}) or {}
                if report.get('probable_repeated_spoken_sections'):
                    r.run([sys.executable,APP/'editorial.py','evidence',source,review],'BUILDING_REVIEW_EVIDENCE',timeout=600);r.state('BLOCKED_FOR_REVIEW',reason='Probable repeated speech requires editorial evidence review',analysis=str(analysis));return
            timeline=build_timeline(r,job,manifest_path,manifest,analysis,work,review,duration)
            assignments=None;subtitle_ass=None
            if mode_for(manifest)=='podcast' and manifest.get('podcast_captions',{}).get('enabled',True):
                subtitle_ass=review/'speaker-captions.ass';assignments=review/'speaker-assignments.json'
                r.run([sys.executable,APP/'podcast_captions.py',source,'--transcript',analysis/'transcript.json','--manifest',manifest_path,'--ass',subtitle_ass,'--assignments',assignments],'ANALYZING_SPEAKERS',duration,timeout=7200)
            # A stale QA-only retry is safe only when the output was produced by this exact recipe.
            if previous.get('recipe_key')==key and previous.get('state') in {'QA_FAILED','QA_REVIEW_REQUIRED','CREATIVE_REVIEW_REQUIRED'} and output.exists():
                finish_review(r,source,output,review,work,duration,cfg,manifest_path,manifest,timeline,assignments);return
            if output.exists() and previous.get('recipe_key')!=key:output.replace(review/f'review-4k.previous-{int(time.time())}.mp4')
            r.run([sys.executable,APP/'editorial.py','handoff',source,review,'--timeline',timeline],'BUILDING_HANDOFF',timeout=180)
            render_source=source
            if mode_for(manifest)!='podcast' and read(timeline,{}).get('events'):
                r.run([sys.executable,APP/'editorial.py','render',source,work,'--timeline',timeline],'RENDERING_TIMELINE',duration);render_source=work/'timeline.mp4'
            audio_report=work/'audio-measure.json';a=read(audio_report,{}) or {}
            if a.get('recipe_key')!=key:
                r.run(['ffmpeg','-hide_banner','-y','-i',render_source,'-vn','-af','loudnorm=I=-14:TP=-2.0:LRA=11:print_format=json','-f','null','-'],'MEASURING_AUDIO',duration)
                blocks=re.findall(r'\{\s*"input_i".*?\}',(work/'commands.log').read_text(),re.S)
                if not blocks:raise RuntimeError('Audio measurement missing')
                a=json.loads(blocks[-1]);a['recipe_key']=key;atomic(audio_report,a)
            af='loudnorm=I=-14:TP=-2.0:LRA=11:linear=false:'+':'.join(f'{dst}={a[src]}' for dst,src in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
            partial=review/'review-4k.partial.mp4';cmd=['ffmpeg','-hide_banner','-y','-hwaccel','cuda','-hwaccel_output_format','cuda','-i',render_source,'-map','0:v:0','-map','0:a:0']
            filters=[]
            if (v['width'],v['height'])!=(3840,2160):filters.append('scale_cuda=3840:2160:force_original_aspect_ratio=decrease:force_divisible_by=2,pad_cuda=3840:2160:(ow-iw)/2:(oh-ih)/2')
            if subtitle_ass:
                # libass is a CPU filter. Download from CUDA only at the final caption stage.
                if filters:filters+=['hwdownload','format=nv12']
                else:cmd=['ffmpeg','-hide_banner','-y','-i',render_source,'-map','0:v:0','-map','0:a:0']
                filters.append("ass='"+str(subtitle_ass).replace("'","\\'")+"'")
            if filters:cmd+=['-vf',','.join(filters)]
            cmd+=['-c:v','h264_nvenc','-preset','p7','-tune','hq','-rc','vbr','-cq','17','-b:v','35M','-maxrate','55M','-bufsize','110M','-profile:v','high','-fps_mode','passthrough','-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-af',af,'-c:a','aac','-b:a','320k','-ar','48000','-ac','2','-movflags','+faststart',partial]
            r.run(cmd,'RENDERING',duration);actual=float(probe(partial)['format']['duration'])
            if abs(actual-duration)>0.25:raise RuntimeError(f'Duration changed: {duration} -> {actual}')
            partial.replace(output);finish_review(r,source,output,review,work,duration,cfg,manifest_path,manifest,timeline,assignments)
        except ValueError as e:r.state('FAILED_FINAL',error=str(e))
        except Exception as e:
            attempt=base['attempt'];r.state('FAILED_FINAL' if attempt>=max_runtime else 'RETRY_PENDING',error=str(e),retry_after=time.time()+min(1800,60*2**attempt))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--watch',action='store_true');ap.add_argument('--job');args=ap.parse_args()
    for name in ['logs','work/.cache/huggingface','review']:(ROOT/name).mkdir(parents=True,exist_ok=True)
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    while True:
        atomic(ROOT/'logs/worker-heartbeat.json',{'at':stamp(),'pid':os.getpid(),'pipeline':4})
        for job in sorted((ROOT/'inbox').iterdir()):
            if job.is_dir() and (not args.job or job.name==args.job):
                try:review_job(job)
                except Exception as e:atomic(ROOT/'logs'/f'{job.name}.status.json',{'state':'FAILED_FINAL','error':str(e),'updated_at':stamp()})
        if not args.watch:return
        atomic(ROOT/'logs/machine-health.json',telemetry());time.sleep(10)
if __name__=='__main__':main()
