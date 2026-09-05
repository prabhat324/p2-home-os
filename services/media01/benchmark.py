#!/usr/bin/env python3
import json,subprocess,time
from pathlib import Path
from runtime import Runner,atomic,read
ROOT=Path('/srv/media-production');work=ROOT/'work/performance-validation';work.mkdir(parents=True,exist_ok=True)
r=Runner(work,ROOT/'logs/performance-validation.status.json',{'job':'performance-validation'})
source=ROOT/'inbox/besquare-demo-01/master.mp4'
results={}
for name,gpu in [('cpu_filters',False),('gpu_resident',True)]:
 cmd=['ffmpeg','-y','-hide_banner','-hwaccel','cuda']
 if gpu:cmd+=['-hwaccel_output_format','cuda']
 cmd+=['-ss','60','-i',source,'-t','30','-an']
 if not gpu:cmd+=['-vf','scale=3840:2160:force_original_aspect_ratio=decrease:flags=lanczos,pad=3840:2160:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p']
 cmd+=['-c:v','h264_nvenc','-preset','p7','-tune','hq','-rc','vbr','-cq','17','-b:v','35M','-maxrate','55M','-bufsize','110M',work/f'{name}.mp4']
 results[name]=r.run(cmd,name,30,300)
r.run(['ffmpeg','-hide_banner','-i',work/'cpu_filters.mp4','-i',work/'gpu_resident.mp4','-lavfi','ssim','-f','null','-'],'COMPARING_FILTER_PATHS',30,300)
results['gpu_speedup']=results['cpu_filters']/results['gpu_resident']
for name,cmd in [('disk_write',['dd','if=/dev/zero',f'of={work}/disk-test.tmp','bs=1M','count=512','oflag=direct','conv=fdatasync']),('disk_read',['dd',f'if={work}/disk-test.tmp','of=/dev/null','bs=1M','iflag=direct'])]:
 p=subprocess.run(cmd,text=True,capture_output=True,timeout=60);results[name]={'returncode':p.returncode,'measurement':p.stderr}
(work/'disk-test.tmp').unlink(missing_ok=True)
atomic(work/'results.json',results);r.state('COMPLETE',results=results)

job=ROOT/'inbox/performance-4k-v2/project.json'
m=read(job,{});m['ready']=True;atomic(job,m)
