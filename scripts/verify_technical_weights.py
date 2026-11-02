"""Перевірка пробних checkpoint і фактичних передбачень лише на val."""
import json
import sys
import time
from pathlib import Path

from backend.app.config import PROJECT_ROOT
from scripts.train_technical import digest, write_json


def main():
    import torch
    from ultralytics import YOLO
    pointer = json.loads((PROJECT_ROOT/'reports/ml/technical-training.json').read_text(encoding='utf-8'))
    attempt = Path(pointer['successful_attempt'])
    summary = json.loads((attempt/'summary.json').read_text(encoding='utf-8'))
    folder = attempt/'verification'
    folder.mkdir(exist_ok=False)
    checkpoints = {}
    for name in ('best', 'last'):
        path=Path(summary['checkpoint_'+name])
        assert path.is_file() and path.stat().st_size > 0
        loaded=YOLO(str(path))
        assert loaded.names == {0:'smoke',1:'fire'}
        checkpoints[name]={'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size,'names':loaded.names,'loads':True}
    data=Path(pointer['data']).parent
    rows=[json.loads(line) for line in (data/'val.jsonl').read_text(encoding='utf-8').splitlines()]
    dataset=PROJECT_ROOT/'datasets/dfire'
    selected=[]
    for category in ('fire-only','smoke-only','mixed','background'):
        candidates=[]
        for row in rows:
            present={int(line.split()[0]) for line in (dataset/row['label']).read_text().splitlines() if line.strip()}
            current='mixed' if present=={0,1} else 'smoke-only' if present=={0} else 'fire-only' if present=={1} else 'background'
            if current==category:
                candidates.append(row)
        selected+=sorted(candidates,key=lambda row:row['image'])[:2]
    assert len(selected)==8 and all(row['split']=='val' for row in selected)
    model=YOLO(checkpoints['best']['path'])
    start=time.perf_counter()
    results=model.predict(source=[str(dataset/row['image']) for row in selected], imgsz=640, device=0, conf=.25, iou=.7, batch=1, save=False, verbose=False)
    torch.cuda.synchronize()
    assert model.predictor.model.device.type=='cuda'
    predictions=[]
    for row,result in zip(selected,results):
        boxes=[]
        for coordinates, confidence, class_id in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
            class_id=int(class_id)
            assert class_id in (0,1)
            boxes.append({'class_id':class_id,'class_name':model.names[class_id],'confidence':confidence,'xyxy_pixels':coordinates})
        output=folder/(Path(row['image']).stem+'.jpg')
        result.save(filename=str(output))
        predictions.append({'image':row['image'],'image_sha256':row['image_sha256'],'detections':boxes,'count':len(boxes),'no_detections':len(boxes)==0,'preview':str(output),'speed_ms':result.speed})
    gpu_seconds=time.perf_counter()-start
    cpu=YOLO(checkpoints['best']['path'])
    start=time.perf_counter()
    cpu_result=cpu.predict(source=str(dataset/selected[0]['image']), imgsz=640, device='cpu', conf=.25, iou=.7, save=False, verbose=False)[0]
    assert cpu.predictor.model.device.type=='cpu'
    cpu_result.save(filename=str(folder/'cpu-example.jpg'))
    report={'technical_only':True,'checkpoint_checks':checkpoints,'gpu_device':str(model.predictor.model.device),'prediction_settings':{'imgsz':640,'conf':.25,'iou':.7,'thresholds_tuned':False},'gpu_predictions':predictions,'gpu_prediction_wall_seconds':gpu_seconds,'cpu':{'success':True,'device':str(cpu.predictor.model.device),'image':selected[0]['image'],'detections':[{'class_id':int(c),'confidence':float(s),'xyxy_pixels':box} for c,s,box in zip(cpu_result.boxes.cls.tolist(),cpu_result.boxes.conf.tolist(),cpu_result.boxes.xyxy.tolist())],'wall_seconds':time.perf_counter()-start,'preview':str(folder/'cpu-example.jpg')},'test_used':False}
    write_json(folder/'verification.json',report)
    print('Checkpoint завантажуються, класи правильні; GPU прикладів:',len(predictions),'; без виявлень:',sum(x['no_detections'] for x in predictions),'; CPU: успішно.')
    print('Результати:',folder)


if __name__ == '__main__':
    main()
