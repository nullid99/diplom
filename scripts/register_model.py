"""Локальна реєстрація лише фінальних ваг із завершеного перевіреного full-run."""
import argparse
import json
import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.analysis_service import checksum
from backend.app.config import PROJECT_ROOT, get_settings, storage_path
from backend.app.database import get_engine
from backend.app.models import ModelVersion


def checked_report(path):
    report=json.loads(path.read_text(encoding='utf-8'))
    run=Path(report['run_dir']).resolve()
    if not run.is_relative_to((PROJECT_ROOT/'runs/full').resolve()):
        raise ValueError('Дозволено лише завершений повний експеримент проєкту, без technical/pretrained.')
    state=json.loads((run/'state.json').read_text(encoding='utf-8'))
    if state['status']!='completed' or report['state']['status']!='completed':
        raise ValueError('Повне навчання ще не завершено або звіт не є підсумковим.')
    if report.get('test_used') is not False or report['readiness']['train']['images']!=7238 or report['readiness']['val']['images']!=1436:
        raise ValueError('Звіт не відповідає погодженому train/val експерименту.')
    if report['readiness']['original_weights']['sha256']!='0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1':
        raise ValueError('Це не погоджений базовий експеримент YOLO11n.')
    info=report['selected_checkpoint']
    weights=Path(info['file']).resolve()
    if weights!=(run/'training/weights/best.pt').resolve() or checksum(weights)!=info['sha256']:
        raise ValueError('Перевірені ваги best.pt відсутні або SHA-256 не збігається.')
    if info['names']!={'0':'smoke','1':'fire'} or set(report.get('per_class_val',{}))!={'smoke','fire'} or not report.get('integrity_after',{}).get('image_and_label_sha256_match'):
        raise ValueError('Немає підтвердження класів, валідації та цілісності даних.')
    # Лише після всіх обмежень; до завершення навчання ML не імпортується.
    import torch
    checkpoint=torch.load(weights,map_location='cpu',weights_only=False)
    model=checkpoint.get('ema') or checkpoint.get('model')
    if model is None or model.names!={0:'smoke',1:'fire'} or checkpoint.get('epoch')!=-1:
        raise ValueError('Потрібні фіналізовані двокласові inference-ваги.')
    if not all(bool(torch.isfinite(value).all()) for value in model.state_dict().values() if value.is_floating_point()):
        raise ValueError('NaN/Inf у вагах.')
    return report,weights


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--name',required=True)
    args=parser.parse_args()
    if not args.name.strip() or len(args.name.strip())>255: raise ValueError('Некоректна назва моделі.')
    report,weights=checked_report(args.report)
    identifier=uuid.uuid4()
    relative=f'models/{identifier}/weights.pt'
    settings=get_settings()
    target=storage_path(relative,settings.storage_root)
    target.parent.mkdir(parents=True,exist_ok=False)
    committed=False
    try:
        shutil.copyfile(weights,target)
        sha=checksum(target)
        if sha!=report['selected_checkpoint']['sha256']: raise ValueError('SHA-256 копії ваг не збігається.')
        with target.open('rb+') as saved: os.fsync(saved.fileno())
        with Session(get_engine()) as session:
            session.add(ModelVersion(id=identifier,name=args.name.strip(),architecture='YOLO11n',weights_path=relative,weights_sha256=sha,class_mapping={'0':'smoke','1':'fire'},training_metadata={
                'verified_final_full_run':True,'run_id':Path(report['run_dir']).name,
                'report_sha256':checksum(args.report),'best_epoch':report['best_epoch_one_based'],
                'validation_metrics':report['overall_val'],'per_class_val':report['per_class_val'],
                'scene_independence_proven':False,'test_used':False,
            }))
            session.commit()
            committed=True
        print(json.dumps({'id':str(identifier),'name':args.name.strip(),'weights_path':relative,'sha256':sha},ensure_ascii=False))
    finally:
        if not committed:
            # Якщо COMMIT невизначений через мережу, не видаляти потенційно зареєстровані ваги.
            try:
                with Session(get_engine()) as session: exists=session.get(ModelVersion,identifier) is not None
            except Exception: exists=True
            if not exists:
                target.unlink(missing_ok=True)
                target.parent.rmdir()


if __name__=='__main__':
    try: main()
    except Exception:
        raise SystemExit('Реєстрацію не виконано. Потрібні завершений full-run, підсумковий report.json, перевірені best.pt, доступні БД і сховище. Секрети приховано.') from None
