"""Fetch the two specified FIRESENSE archives; verify published MD5 and keep originals."""
import hashlib
import json
import shutil
import stat
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from backend.app.config import PROJECT_ROOT

ROOT=PROJECT_ROOT/'datasets/firesense'
RECORD='https://zenodo.org/records/836749'
FILES={'fire_videos.1406.zip':'7cfe8286cc4b45193149186bf67ea00d',
       'smoke_videos.1407.zip':'5ee6bc867c4a9332b4e75f308c26fc23'}


def digest(path,algorithm='sha256'):
    with path.open('rb') as stream:return hashlib.file_digest(stream,algorithm).hexdigest()


def fetch(name):
    url=RECORD+'/files/'+name+'?download=1'
    archive=ROOT/name
    if not archive.exists():
        partial=archive.with_suffix('.zip.part')
        if partial.exists():raise RuntimeError('Existing partial download needs explicit inspection: '+str(partial))
        print('Downloading '+name,flush=True)
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'FireVision research preparation'}),timeout=90) as response,partial.open('xb') as output:
            count=0
            while chunk:=response.read(1024*1024):
                output.write(chunk);count+=len(chunk)
                if count%(64*1024**2)==0:print(f'{name}: {count//1024**2} MiB',flush=True)
        if digest(partial,'md5')!=FILES[name] or not zipfile.is_zipfile(partial):raise RuntimeError('Archive checksum/format mismatch: '+name)
        partial.rename(archive)
    if digest(archive,'md5')!=FILES[name]:raise RuntimeError('Existing archive differs from published checksum: '+name)
    info=dict(name=name,url=url,bytes=archive.stat().st_size,published_md5=FILES[name],actual_md5=digest(archive,'md5'),sha256=digest(archive))
    directory=ROOT/'raw'/name.split('_')[0]
    marker=ROOT/'provenance'/(name+'.extraction.json')
    if marker.exists():
        previous=json.loads(marker.read_text(encoding='utf-8'))
        assert previous['archive_sha256']==info['sha256']
        for row in previous['files']:assert digest(ROOT/row['path'])==row['sha256']
    else:
        if directory.exists() and any(directory.iterdir()):raise RuntimeError('Nonempty extraction without completed manifest: '+str(directory))
        directory.mkdir(parents=True,exist_ok=True)
        originals=[]
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path=directory/member.filename.replace('\\','/')
                if not path.resolve().is_relative_to(directory.resolve()) or ':' in member.filename or stat.S_ISLNK(member.external_attr>>16):raise RuntimeError('Unsafe ZIP member')
                if member.is_dir():path.mkdir(parents=True,exist_ok=True);continue
                path.parent.mkdir(parents=True,exist_ok=True)
                with bundle.open(member) as source,path.open('xb') as target:shutil.copyfileobj(source,target,1024*1024)
                originals.append(dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=digest(path)))
                path.chmod(stat.S_IREAD)
        marker.write_text(json.dumps(dict(archive_sha256=info['sha256'],files=originals),indent=2),encoding='utf-8')
    print('Verified and extracted '+name,flush=True)
    return info


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'provenance').mkdir(exist_ok=True)
    if shutil.disk_usage(ROOT).free<5*1024**3:raise RuntimeError('Need at least 5 GiB free on D:')
    for filename,url in [('record.html',RECORD),('record.json','https://zenodo.org/api/records/836749')]:
        target=ROOT/'provenance'/filename
        if not target.exists():
            try:
                with urllib.request.urlopen(url,timeout=30) as response:body=response.read()
                target.write_bytes(body)
            except Exception as error:print(f'Provenance {filename}: {type(error).__name__}',flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:archives=list(pool.map(fetch,FILES))
    (ROOT/'provenance/acquisition.json').write_text(json.dumps(dict(record=RECORD,retrieved_at=datetime.now(timezone.utc).isoformat(),archives=archives),indent=2),encoding='utf-8')
    print(json.dumps(archives,indent=2),flush=True)


if __name__=='__main__':main()
