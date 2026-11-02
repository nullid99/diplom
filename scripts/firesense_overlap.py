"""Screen selected source frames against cached prepared train/val hashes, without re-auditing D-Fire."""
import json
from pathlib import Path
import imagehash
from PIL import Image,ImageDraw,ImageOps
from scripts.firesense_prepare import ROOT,REPORT,frame,sheet
from backend.app.config import PROJECT_ROOT


def main():
    selected=json.loads((ROOT/'selection.json').read_text(encoding='utf-8'))['clips']
    membership={}
    for split in ('train','val'):
        for line in (PROJECT_ROOT/f'datasets/dfire/prepared/{split}.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line);membership[row['image']]=split
    known=[]
    for line in (PROJECT_ROOT/'reports/dfire/files.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row['image'] in membership and row.get('phash'):
            known.append(dict(image=row['image'],split=membership[row['image']],phash=int(row['phash'],16),pixel_sha256=row.get('pixel_sha256'),aspect=row['width']/row['height']))
    results=[];previews=[]
    for row in selected:
        if row.get('reference_id'):continue
        candidates=[]
        for tick in range(int(row['end_seconds']-row['start_seconds'])):
            when=row['start_seconds']+tick
            image=frame(ROOT/row['original_file'],when)
            code=int(str(imagehash.phash(image,hash_size=8)),16)
            aspect=image.width/image.height
            nearest=sorted(((code^item['phash']).bit_count(),item['image'],item) for item in known if abs(aspect/item['aspect']-1)<=.15)[:3]
            for distance,_,item in nearest:
                candidates.append(dict(distance=distance,source_seconds=when,trainval_image=item['image'],split=item['split']))
        candidates.sort(key=lambda item:(item['distance'],item['source_seconds'],item['trainval_image']))
        unique=[];seen=set()
        for candidate in candidates:
            if candidate['trainval_image'] not in seen:
                unique.append(candidate);seen.add(candidate['trainval_image'])
            if len(unique)==3:break
        results.append(dict(clip_id=row['id'],source_file=row['original_file'],nearest_candidates=unique,possible_overlap=any(c['distance']<=12 for c in unique)))
        best=unique[0]
        a=frame(ROOT/row['original_file'],best['source_seconds'])
        with Image.open(PROJECT_ROOT/'datasets/dfire'/best['trainval_image']) as opened:b=opened.convert('RGB')
        previews.extend([(a,f"{row['id']} @ {best['source_seconds']:.1f}s"),(b,f"{best['split']} d={best['distance']}\n{Path(best['trainval_image']).name}")])
        print(row['id']+' nearest Hamming '+str(best['distance']),flush=True)
    sheet(previews,REPORT/'overlap-nearest-pairs.jpg',columns=4,size=(320,240))
    payload=dict(method='Source frames at 1-second spacing; 64-bit pHash versus cached prepared train/val; aspect ratio tolerance 15%; d<=12 is only a possible scene/image overlap, not proof.',
                 train_images=sum(x['split']=='train' for x in known),val_images=sum(x['split']=='val' for x in known),test_used=False,
                 results=results,independence_confirmed=False,
                 limitations='Sparse frame/hash screening misses crops, edits, different timestamps and related scenes. Pretrained COCO provenance not exhaustively checked. Variants share F02 and are correlated. No independent-test claim.')
    (REPORT/'overlap.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')


if __name__=='__main__':main()
