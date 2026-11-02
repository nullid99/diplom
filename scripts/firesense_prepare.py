"""Model-free FIRESENSE inventory, temporal previews, clip preparation and degradation."""
import argparse
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
from backend.app.config import PROJECT_ROOT,get_settings
from scripts.fetch_firesense import ROOT,digest

REPORT=PROJECT_ROOT/'reports/firesense'
FONT=ImageFont.truetype('C:/Windows/Fonts/consola.ttf',13)


def probe(path):
    tool=get_settings().ffprobe_path
    result=subprocess.run([str(tool),'-v','error','-select_streams','v:0','-show_entries','stream=codec_name,width,height,avg_frame_rate,r_frame_rate,start_time:format=duration,start_time','-of','json',str(path)],capture_output=True,check=True,timeout=30)
    return json.loads(result.stdout)


def frame(path,when):
    result=subprocess.run([str(get_settings().ffmpeg_path),'-v','error','-threads','1','-ss',str(when),'-i',str(path),'-frames:v','1','-threads','1','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,check=True,timeout=40)
    import io
    return Image.open(io.BytesIO(result.stdout)).convert('RGB')


def sheet(items,path,columns=4,size=(320,240)):
    image=Image.new('RGB',(columns*size[0],((len(items)+columns-1)//columns)*size[1]),'#14202b')
    draw=ImageDraw.Draw(image)
    for index,(picture,label) in enumerate(items):
        x,y=index%columns*size[0],index//columns*size[1]
        tile=ImageOps.contain(picture,(size[0],size[1]-35))
        image.paste(tile,(x+(size[0]-tile.width)//2,y+35+(size[1]-35-tile.height)//2))
        draw.text((x+4,y+4),label,font=FONT,fill='white')
    image.save(path)


def inventory():
    REPORT.mkdir(parents=True,exist_ok=True)
    paths=sorted((ROOT/'raw').rglob('*.avi'))
    def inspect(path):
        metadata=probe(path);when=float(metadata['format']['duration'])/2
        return dict(path=path.relative_to(ROOT).as_posix(),sha256=digest(path),bytes=path.stat().st_size,metadata=metadata,preview_seconds=when),frame(path,when)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(inspect,paths))
    (REPORT/'inventory.json').write_text(json.dumps([row for row,_ in results],indent=2),encoding='utf-8')
    for category in ('fire/pos','fire/neg','smoke/pos','smoke/neg'):
        items=[(picture,f"{Path(row['path']).name}\n{row['preview_seconds']:.1f}s / {float(row['metadata']['format']['duration']):.1f}s") for row,picture in results if '/'+category+'/' in row['path']]
        sheet(items,REPORT/(category.replace('/','-')+'-overview.jpg'))
    print(f'Inventoried {len(results)} original videos; model not imported.')


def prepare(selection):
    rows=json.loads(selection.read_text(encoding='utf-8'))['clips']
    target=ROOT/'clips';target.mkdir(exist_ok=True)
    manifest=[]
    for row in rows:
        source=ROOT/row['original_file'];metadata=probe(source)
        start,end=row['start_seconds'],row['end_seconds']
        if not 0<=start<end<=float(metadata['format']['duration'])+.00001:raise ValueError('Interval outside source')
        output=target/(row['id']+'.mp4')
        transform=row.get('transform','reference')
        filters=['setpts=PTS-STARTPTS']
        if transform=='low_resolution':filters.append('scale=160:-2:flags=area')
        if transform=='blur':filters.append('gblur=sigma=4:steps=2')
        filters.append('pad=ceil(iw/2)*2:ceil(ih/2)*2')
        command=[str(get_settings().ffmpeg_path),'-v','error','-nostdin','-n','-threads','1','-i',str(source),'-ss',str(start),'-t',str(end-start),'-map','0:v:0','-an','-sn','-vf',','.join(filters),'-c:v','libx264','-threads','1','-preset','medium','-crf','42' if transform=='strong_compression' else '18','-bf','0','-fps_mode','vfr','-enc_time_base','1:1000000','-movflags','+faststart',str(output)]
        if output.exists():raise RuntimeError('Refusing to overwrite '+str(output))
        subprocess.run(command,capture_output=True,check=True,timeout=120)
        info=probe(output)
        # Decode every output frame; do not accept a nominally valid but broken clip.
        subprocess.run([str(get_settings().ffmpeg_path),'-v','error','-threads','1','-i',str(output),'-map','0:v:0','-f','null','-'],capture_output=True,check=True,timeout=60)
        def times(path):
            process=subprocess.run([str(get_settings().ffprobe_path),'-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time,duration_time','-of','json',str(path)],capture_output=True,check=True,timeout=30)
            return json.loads(process.stdout)['frames']
        timeline=times(output)
        with (target/(row['id']+'.timeline.json')).open('w',encoding='utf-8') as stream:json.dump(timeline,stream)
        entry={**row,'source_record':'https://zenodo.org/records/836749','doi':'10.5281/zenodo.836749','license':'CC-BY-4.0',
               'source_sha256':digest(source),'file':output.relative_to(ROOT).as_posix(),'sha256':digest(output),'bytes':output.stat().st_size,
               'metadata':info,'frames':len(timeline),'ffmpeg_command':command,'selection_sha256':digest(selection),
               'independent_test':False,'label_basis':'Content reviewed before inference; archive category is single-class only.'}
        manifest.append(entry)
        previews=[]
        duration=float(info['format']['duration'])
        for tick in range(int(duration*2)):
            when=tick/2
            previews.append((frame(output,when),f"{row['id']} | {when:.1f}s"))
        sheet(previews,REPORT/(row['id']+'-review.jpg'),columns=5,size=(256,192))
        print(row['id']+' prepared',flush=True)
    # Variant frames and PTS must match the reference; no dropping/duplicating time.
    lookup={row['id']:row for row in manifest}
    for row in manifest:
        if row.get('reference_id'):
            reference=lookup[row['reference_id']]
            a=json.loads((target/(row['id']+'.timeline.json')).read_text())
            b=json.loads((target/(reference['id']+'.timeline.json')).read_text())
            assert len(a)==len(b)
            assert max(abs(float(x['best_effort_timestamp_time'])-float(y['best_effort_timestamp_time'])) for x,y in zip(a,b))<=.000002
            assert abs(float(row['metadata']['format']['duration'])-float(reference['metadata']['format']['duration']))<=.00001
    (ROOT/'manifest.json').write_text(json.dumps(dict(created_at=datetime.now(timezone.utc).isoformat(),demonstration_only=True,selected_before_inference=True,clips=manifest),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inventory','prepare'])
    parser.add_argument('--selection',type=Path,default=ROOT/'selection.json')
    args=parser.parse_args()
    inventory() if args.action=='inventory' else prepare(args.selection)
