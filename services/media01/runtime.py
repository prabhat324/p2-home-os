"""Atomic state, bounded subprocesses and persistent per-stage telemetry."""
import hashlib,json,os,signal,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

def stamp(): return datetime.now(timezone.utc).isoformat()
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    with tmp.open('w') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    tmp.replace(path)
def read(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (FileNotFoundError,json.JSONDecodeError):return default

def fingerprint(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def telemetry():
    data={'at':stamp(),'load':os.getloadavg()}
    mem={k:int(v.split()[0]) for k,v in (x.split(':',1) for x in Path('/proc/meminfo').read_text().splitlines())}
    data['memory_available_kib']=mem['MemAvailable']
    data['thermal_c']={str(p):int(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp') if os.access(p,os.R_OK)}
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used,temperature.gpu,power.draw,clocks.sm,clocks.mem','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
        data['gpu_csv']=p.stdout.strip();data['gpu_error']=p.stderr.strip()
    except Exception as e:data['gpu_error']=str(e)
    return data

class Runner:
    def __init__(self,work,status,base):self.work=Path(work);self.status=Path(status);self.base=base;self.stage=None
    def state(self,state,**kw):
        self.base.update(state=state,updated_at=stamp(),**kw);atomic(self.status,self.base)
    def run(self,cmd,stage,duration=None,timeout=14400):
        self.state(stage,progress_seconds=0)
        begin=time.monotonic();progress=self.work/'ffmpeg-progress.txt'
        progress.unlink(missing_ok=True)
        cmd=list(map(str,cmd))
        if Path(cmd[0]).name=='ffmpeg':cmd[1:1]=['-nostdin','-nostats','-progress',str(progress)]
        self.stage=stage
        with (self.work/'commands.log').open('a') as log:
            log.write('\n'+stamp()+' '+repr(cmd)+'\n');log.flush()
            p=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while p.poll() is None:
                    elapsed=time.monotonic()-begin
                    if elapsed>timeout:raise TimeoutError(f'{stage} exceeded {timeout}s')
                    sample=telemetry();sample.update(stage=stage,elapsed_seconds=round(elapsed,2))
                    with (self.work/'performance.jsonl').open('a') as f:f.write(json.dumps(sample)+'\n')
                    sec=0
                    if progress.exists():
                        for line in progress.read_text().splitlines():
                            if line.startswith('out_time_us='):
                                try:sec=max(0,int(line.split('=')[1])/1e6)
                                except ValueError:pass
                    self.state(stage,elapsed_seconds=round(elapsed,1),progress_seconds=sec,percent=round(min(100,sec/duration*100),1) if duration else None)
                    time.sleep(2)
            except BaseException:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
                raise
        elapsed=time.monotonic()-begin
        metrics=read(self.work/'timings.json',[]);metrics.append({'stage':stage,'seconds':round(elapsed,3),'returncode':p.returncode});atomic(self.work/'timings.json',metrics)
        if p.returncode:raise RuntimeError(f'{stage} failed ({p.returncode}); see {self.work}/commands.log')
        return elapsed
