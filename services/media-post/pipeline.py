#!/usr/bin/env python3
import argparse, csv, hashlib, json, re, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def stamp(t):
    h,m,s=t.split(":"); return int(h)*3600+int(m)*60+float(s)

def font(size, bold=False):
    names=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return ImageFont.truetype(next(p for p in names if Path(p).exists()),size)

def wrap(draw,text,f,maxw):
    words=text.split(); lines=[]; cur=""
    for word in words:
        nxt=(cur+" "+word).strip()
        if draw.textbbox((0,0),nxt,font=f)[2] <= maxw: cur=nxt
        else:
            if cur: lines.append(cur)
            cur=word
    if cur: lines.append(cur)
    return lines

def card(cfg,event,out,asset_root):
    w,h=cfg["format"]["width"],cfg["format"]["height"]
    p=cfg["palette"]; im=Image.new("RGBA",(w,h),(0,0,0,0))
    d=ImageDraw.Draw(im)
    # editorial-paper panel with depth, leaving host visible on left
    panel=(690,115,1845,940); shadow=Image.new("RGBA",im.size,(0,0,0,0)); sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((panel[0]+18,panel[1]+22,panel[2]+18,panel[3]+22),28,fill=(0,0,0,125))
    im=Image.alpha_composite(im,shadow.filter(ImageFilter.GaussianBlur(18))); d=ImageDraw.Draw(im)
    d.rounded_rectangle(panel,28,fill=p["paper"],outline=p["gold"],width=4)
    d.rectangle((panel[0],panel[1],panel[2],panel[1]+14),fill=p["gold"])
    d.text((744,166),event["label"],font=font(28,True),fill=p["blue"])
    d.text((744,211),cfg["brand"],font=font(24,True),fill=p["navy"])
    y=280
    for line in wrap(d,event["headline"],font(54,True),1000):
        d.text((744,y),line,font=font(54,True),fill=p["ink"]); y+=68
    ap=asset_root/event.get("asset","")
    if event.get("asset") and ap.exists():
        src=Image.open(ap).convert("RGB"); src.thumbnail((980,360))
        x=744+(980-src.width)//2; im.alpha_composite(src.convert("RGBA"),(x,510))
        d=ImageDraw.Draw(im); d.rectangle((x,510,x+src.width,510+src.height),outline=(20,30,40,90),width=2)
    elif event.get("asset"):
        d.rounded_rectangle((744,520,1725,790),18,fill="#E7E0D4",outline="#B8AFA1",width=2)
        d.text((825,626),"APPROVED SOURCE IMAGE NEEDED",font=font(30,True),fill="#786F65")
    d.text((744,865),event["source"],font=font(22),fill="#53606D")
    out.parent.mkdir(parents=True,exist_ok=True); im.save(out)

def render_motion(png,mov,duration,fps,w,h):
    fade=min(.35,duration/5); vf=(f"scale={w}:{h},format=rgba," 
        f"fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={duration-fade}:d={fade}:alpha=1")
    cmd=["ffmpeg","-y","-loop","1","-framerate",str(fps),"-i",str(png),"-t",str(duration),"-vf",vf,
         "-c:v","prores_ks","-profile:v","4444","-pix_fmt","yuva444p10le",str(mov)]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def main():
    a=argparse.ArgumentParser(); a.add_argument("--project",required=True); a.add_argument("--master"); a.add_argument("--captions",required=True); a.add_argument("--output",required=True); a.add_argument("--assets",default=".")
    x=a.parse_args(); cfg=json.loads(Path(x.project).read_text()); out=Path(x.output); out.mkdir(parents=True,exist_ok=True)
    captions=Path(x.captions); shutil.copy2(captions,out/"captions_verified.srt")
    rows=[]; provenance=[]
    for e in cfg["events"]:
        png=out/"cards"/f"{e['id']}.png"; mov=out/"overlays"/f"{e['id']}.mov"
        card(cfg,e,png,Path(x.assets)); mov.parent.mkdir(parents=True,exist_ok=True)
        if shutil.which("ffmpeg"): render_motion(png,mov,e["duration"],cfg["format"]["fps"],cfg["format"]["width"],cfg["format"]["height"])
        rows.append([e["start"],e["duration"],e["id"],e["type"],str(mov),e["label"]])
        ap=Path(x.assets)/e.get("asset",""); provenance.append({"id":e["id"],"source":e["source"],"asset":str(ap) if e.get("asset") else None,"asset_present":ap.exists() if e.get("asset") else True})
    with (out/"timeline.csv").open("w",newline="") as f: csv.writer(f).writerows([["start","duration","id","type","overlay","label"],*rows])
    (out/"provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
    manifest={"project":cfg["project_id"],"caption_sha256":hashlib.sha256(captions.read_bytes()).hexdigest(),"master":x.master,"events":len(rows),"review_status":"ASSET REVIEW REQUIRED"}
    (out/"build-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps(manifest))
if __name__=="__main__": main()

