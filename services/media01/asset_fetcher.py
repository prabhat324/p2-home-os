#!/usr/bin/env python3
"""Resolve public HTTPS visual assets into a project-local cache.

This is deliberately not a web-search engine. The orchestration layer supplies verified URLs
and provenance; this stage safely downloads direct image/video assets so media-01 can render
them without manual file copying. Private/link-local destinations and unapproved MIME types
are rejected to avoid SSRF and accidental arbitrary downloads.
"""
import argparse,hashlib,ipaddress,json,mimetypes,os,re,socket,urllib.parse,urllib.request
from pathlib import Path

MAX_BYTES=120*1024*1024
ALLOWED_PREFIXES=('image/','video/')
EXTENSIONS={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif','video/mp4':'.mp4','video/quicktime':'.mov','video/webm':'.webm'}


def safe_host(host):
    if not host:raise ValueError('Asset URL requires a hostname')
    for info in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f'Asset host resolves to non-public address: {ip}')

def validate_url(url):
    p=urllib.parse.urlparse(url)
    if p.scheme!='https':raise ValueError('Only HTTPS visual asset URLs are allowed')
    if p.username or p.password:raise ValueError('Credentials in asset URLs are prohibited')
    safe_host(p.hostname);return p

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(url,dest_base):
    parsed=validate_url(url);opener=urllib.request.build_opener(SafeRedirect());req=urllib.request.Request(url,headers={'User-Agent':'BeSquare-media01/1.0'})
    with opener.open(req,timeout=45) as resp:
        final=resp.geturl();validate_url(final);ctype=(resp.headers.get_content_type() or '').lower();length=resp.headers.get('Content-Length')
        if not ctype.startswith(ALLOWED_PREFIXES):raise ValueError(f'Unsupported asset content type: {ctype}')
        if length and int(length)>MAX_BYTES:raise ValueError('Asset exceeds maximum download size')
        ext=EXTENSIONS.get(ctype) or Path(urllib.parse.urlparse(final).path).suffix.lower() or mimetypes.guess_extension(ctype) or '.bin'
        if ext not in {'.jpg','.jpeg','.png','.webp','.gif','.mp4','.mov','.webm'}:raise ValueError(f'Unsupported asset extension: {ext}')
        target=dest_base.with_suffix('.jpg' if ext=='.jpeg' else ext);tmp=target.with_suffix(target.suffix+'.part');total=0;h=hashlib.sha256()
        with tmp.open('wb') as f:
            while True:
                chunk=resp.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>MAX_BYTES:raise ValueError('Asset exceeded maximum download size while streaming')
                h.update(chunk);f.write(chunk)
        os.replace(tmp,target);return target,ctype,total,h.hexdigest(),final

def resolve(manifest,cache):
    cache.mkdir(parents=True,exist_ok=True);out=json.loads(json.dumps(manifest));records=[];assets=[]
    for i,item in enumerate(manifest.get('visual_assets',[]),1):
        row=dict(item)
        if row.get('url'):
            if not row.get('source'):raise ValueError(f'visual_assets[{i}] URL requires source/provenance text')
            target,ctype,size,digest,final=download(row['url'],cache/f'{i:03d}-{row.get("kind","asset")}')
            row['path']=str(target);records.append({'index':i,'url':row['url'],'final_url':final,'path':str(target),'content_type':ctype,'bytes':size,'sha256':digest,'source':row['source']})
        elif row.get('path'):
            p=Path(row['path']).expanduser().resolve()
            if not p.exists() or not p.is_file():raise ValueError(f'visual_assets[{i}] path does not exist: {p}')
            row['path']=str(p);records.append({'index':i,'path':str(p),'source':row.get('source','Project-provided asset')})
        else:raise ValueError(f'visual_assets[{i}] requires path or url')
        assets.append(row)
    out['visual_assets']=assets;return out,records

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--cache-dir',type=Path,required=True);ap.add_argument('--output-manifest',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args()
    manifest=json.loads(a.manifest.read_text());resolved,records=resolve(manifest,a.cache_dir);a.output_manifest.write_text(json.dumps(resolved,indent=2));payload={'status':'PASS','assets':records};a.report.write_text(json.dumps(payload,indent=2));print(json.dumps({'status':'PASS','resolved_assets':len(records),'output_manifest':str(a.output_manifest)},indent=2))
if __name__=='__main__':main()
