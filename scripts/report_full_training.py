"""Після завершення: повна val, фактичні приклади й відтворюваний звіт; test не читається."""
import argparse
import csv
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.config import PROJECT_ROOT
from scripts.train_full import atomic_json, inspect_checkpoint, latest_run, load_json, process_lock, verify_inputs
from scripts.train_technical import readonly_check_image


def report(run, output_dir=None):
    run=Path(run).resolve()
    # Ті самі блокування, що в worker: жодної паралельної GPU-валідації.
    with process_lock(run/'run.lock'), process_lock(PROJECT_ROOT/'.cache/full-training-gpu0.lock'):
        state=load_json(run/'state.json')
        if state['status']!='completed':
            raise RuntimeError('Підсумковий звіт дозволено лише для реально завершеного запуску.')
        import torch
        from ultralytics import YOLO
        from ultralytics.models.yolo.detect.val import DetectionValidator
        import ultralytics.data.dataset as dataset_module
        import ultralytics.data.utils as data_utils
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA недоступна; звіт не переходить мовчки на CPU.')
        folder=Path(output_dir).resolve() if output_dir else run/('report_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        folder.mkdir(parents=True,exist_ok=False)
        integrity_before=verify_inputs(run)
        weights=run/'training/weights/best.pt'
        checkpoint=inspect_checkpoint(weights,require_resume=False)
        configuration=load_json(run/'configuration.json')
        with (run/'training/results.csv').open(encoding='utf-8',newline='') as stream:
            history=[{k.strip():v.strip() for k,v in row.items()} for row in csv.DictReader(stream)]
        assert len(history)==state['completed_epochs']
        assert all(math.isfinite(float(value)) for row in history for key,value in row.items() if 'loss' in key)
        # CSV округлений: найкращу епоху визначаємо за повною точністю checkpoint.
        periodic=[inspect_checkpoint(path) for path in (run/'training/weights').glob('epoch*.pt')]
        best=max(periodic,key=lambda info:(info['fitness'],info['completed_epochs']))
        best_epoch=best['completed_epochs']
        selected_payload=torch.load(weights,map_location='cpu',weights_only=False)
        periodic_payload=torch.load(best['file'],map_location='cpu',weights_only=False)
        selected_model=selected_payload.get('ema') or selected_payload['model']
        periodic_model=periodic_payload.get('ema') or periodic_payload['model']
        assert all(torch.equal(value,periodic_model.state_dict()[key]) for key,value in selected_model.state_dict().items())
        del selected_payload,periodic_payload,selected_model,periodic_model
        model=YOLO(str(weights))
        assert model.names=={0:'smoke',1:'fire'}
        original_load=dataset_module.load_dataset_cache_file
        original_save=dataset_module.save_dataset_cache_file
        def location(path):
            target=PROJECT_ROOT/'.cache/ultralytics-labels'/('full-readonly-v2-'+hashlib.sha256(str(path).encode()).hexdigest()+'.cache')
            target.parent.mkdir(parents=True,exist_ok=True)
            return target
        def load(path): return original_load(location(path))
        def save(prefix,path,payload,version): return original_save(prefix,location(path),payload,version)
        started=time.perf_counter()
        validators=[]
        class ReportValidator(DetectionValidator):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                validators.append(self)
        with patch.object(dataset_module,'load_dataset_cache_file',load), patch.object(dataset_module,'save_dataset_cache_file',save), patch.object(data_utils,'check_image',readonly_check_image):
            metrics=model.val(validator=ReportValidator,data=str(run/'input/data.yaml'),split='val',device=0,workers=0,batch=configuration['overrides']['batch'],imgsz=640,cache=False,half=True,conf=.001,iou=.7,plots=True,save_json=True,project=str(folder),name='validation',exist_ok=False)
        assert str(validators[0].device).startswith('cuda')
        assert len(validators[0].dataloader.dataset)==1436
        per_class={}
        for index,class_id in enumerate(metrics.ap_class_index):
            values=metrics.class_result(index)
            per_class[model.names[int(class_id)]]=dict(zip(('precision','recall','mAP50','mAP50-95'),map(float,values)))
        rows=[json.loads(line) for line in (run/'input/val.jsonl').read_text(encoding='utf-8').splitlines()]
        selected=[]
        for category in ('fire-only','smoke-only','mixed','background'):
            found=[]
            for row in rows:
                classes={int(line.split()[0]) for line in (PROJECT_ROOT/'datasets/dfire'/row['label']).read_text().splitlines() if line.strip()}
                kind='mixed' if classes=={0,1} else 'smoke-only' if classes=={0} else 'fire-only' if classes=={1} else 'background'
                if kind==category: found.append(row)
            selected.extend(sorted(found,key=lambda row:row['image'])[:2])
        previews=folder/'predictions'
        previews.mkdir()
        predictions=[]
        for row in selected:
            result=model.predict(str(PROJECT_ROOT/'datasets/dfire'/row['image']),device=0,imgsz=640,batch=1,conf=.25,iou=.7,save=False,verbose=False)[0]
            output=previews/(Path(row['image']).stem+'.jpg')
            result.save(filename=str(output))
            boxes=[{'class_id':int(c),'name':model.names[int(c)],'confidence':float(score),'xyxy':coordinates} for c,score,coordinates in zip(result.boxes.cls.tolist(),result.boxes.conf.tolist(),result.boxes.xyxy.tolist())]
            predictions.append({'image':row['image'],'image_sha256':row['image_sha256'],'detections':boxes,'no_detections':not boxes,'preview':str(output)})
        evidence={
            'created_at':datetime.now(timezone.utc).isoformat(),'run_dir':str(run),'state':state,
            'epochs_completed':len(history),'termination_reason':state['reason'],
            'best_epoch_one_based':best_epoch,'best_periodic_checkpoint':best,'best_selection':'Maximum full precision checkpoint val mAP50-95, latest tie; selected weights tensors matched',
            'selected_checkpoint':checkpoint,'configuration':configuration,'readiness':load_json(run/'readiness.json'),
            'optimizer_runtime':load_json(run/'optimizer-runtime.json'),
            'overall_val':{k:float(v) for k,v in metrics.results_dict.items()},'per_class_val':per_class,
            'validation_options':{'split':'val','conf':.001,'iou':.7,'imgsz':640,'half':True,'images':1436},
            'prediction_options':{'conf':.25,'iou':.7,'thresholds_tuned':False},'predictions':predictions,
            'plots':[str(p) for root in (run/'training',folder/'validation') for p in root.glob('*.png')],
            'finite_training_and_validation_losses':True,'integrity_before':integrity_before,'integrity_after':verify_inputs(run),
            'report_wall_seconds':time.perf_counter()-started,'test_used':False,
            'limitations':'Val is used for model selection; scene independence is not proven. These are development validation metrics, not independent test results or event/video evaluation.'}
        atomic_json(folder/'report.json',evidence)
        lines=['# Перший базовий експеримент YOLO11n','',f"Стан: {state['status']}; причина: {state['reason']}; епох: {len(history)}; найкраща: {best_epoch}.",'',f"Ваги: `{weights}`; SHA-256 `{checkpoint['sha256']}`; 0=smoke, 1=fire.",'',f"Train 7238 / val 1436, test не використано. Пік allocated: {state.get('peak_allocated_bytes')}; reserved: {state.get('peak_reserved_bytes')} байтів. Час worker: {state.get('wall_seconds')} с.",'','## Фактичні метрики val','',json.dumps(evidence['overall_val'],ensure_ascii=False,indent=2),'','По класах:','',json.dumps(per_class,ensure_ascii=False,indent=2),'',f"Збережено {len(predictions)} передбачень; без виявлень: {sum(p['no_detections'] for p in predictions)}.",'','Конфігурація, версії, хеші даних, графіки та перевірки цілісності — у report.json і каталогах training/validation/predictions.','',evidence['limitations']]
        (folder/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(folder)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--output-dir',type=Path,help='New report directory; may be outside the immutable experiment.')
    args=parser.parse_args()
    report(args.run_dir or latest_run(),args.output_dir)


if __name__=='__main__':
    main()
