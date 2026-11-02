"""Перший повний базовий запуск YOLO11n: підготовка, worker, стан і resume."""
import argparse
import contextlib
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import PROJECT_ROOT
from scripts.train_technical import digest, readonly_check_image

LATEST = PROJECT_ROOT / 'reports/ml/full-training-latest.json'


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    os.replace(temporary, path)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def latest_run():
    return Path(load_json(LATEST)['run_dir'])


@contextlib.contextmanager
def process_lock(path):
    """Блокування ОС звільняється навіть після аварійного завершення процесу."""
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('Інший процес уже утримує блокування: '+str(path)) from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def is_locked(path):
    try:
        with process_lock(path):
            return False
    except RuntimeError:
        return True


def rows_for(run):
    for split in ('train','val'):
        for line in (Path(run)/'input'/f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
            yield json.loads(line)


def verify_inputs(run):
    root=PROJECT_ROOT/'datasets/dfire'
    evidence=load_json(Path(run)/'readiness.json')
    for name, checksum in evidence['input_manifest_sha256'].items():
        if digest(Path(run)/'input'/name) != checksum:
            raise RuntimeError('Changed run input manifest: '+name)
    for name, checksum in evidence['main_manifest_sha256'].items():
        if digest(root/'prepared'/name) != checksum:
            raise RuntimeError('Змінився основний маніфест: '+name)
    count=0
    for row in rows_for(run):
        for kind in ('image','label'):
            if digest(root/row[kind]) != row[kind+'_sha256']:
                raise RuntimeError('Порушена цілісність '+kind+': '+row[kind])
        count+=1
    assert count==8674
    return {'verified_at':utc(),'images':count,'image_and_label_sha256_match':True,'main_manifests_unchanged':True}


def prepare(batch=4):
    import yaml
    from ultralytics.cfg import get_cfg
    if shutil.disk_usage(PROJECT_ROOT).free < 10*1024**3:
        raise RuntimeError('Потрібно щонайменше 10 ГіБ вільно на D:.')
    with process_lock(PROJECT_ROOT/'.cache/full-training-gpu0.lock'):
        pass
    compute=subprocess.run(['nvidia-smi','--query-compute-apps=pid,process_name','--format=csv,noheader'],capture_output=True,text=True,check=True,timeout=10)
    if any('python' in line.lower() for line in compute.stdout.splitlines()):
        raise RuntimeError('На GPU вже є Python-процес; спочатку перевірте інше обчислення.')
    dataset=PROJECT_ROOT/'datasets/dfire'
    audit=load_json(PROJECT_ROOT/'reports/dfire/audit.json')
    review=load_json(PROJECT_ROOT/'reports/dfire/reviews/yolo11n_tech_20261101T195952Z_f9f60144/review.json')
    assert review['excluded_union']==10858 and review['kept']==10669
    assert sum(review['disjoint_reason_signatures'].values())==10858
    main={p.name:digest(p) for p in (dataset/'prepared').iterdir() if p.is_file()}
    assert main==audit['manifest_sha256']==review['main_manifest_sha256']
    weights=PROJECT_ROOT/'weights/pretrained/yolo11n-v8.3.0.pt'
    provenance=load_json(weights.with_suffix('.json'))
    assert digest(weights)==provenance['sha256']=='0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1'
    identifier='yolo11n_baseline_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    run=PROJECT_ROOT/'runs/full'/identifier
    (run/'input').mkdir(parents=True,exist_ok=False)
    (run/'code').mkdir()
    for name in ('train_full.py','train_technical.py','train-full.ps1','project-env.ps1'):
        shutil.copy2(PROJECT_ROOT/'scripts'/name,run/'code'/name)
    records={record['image']:record for record in audit['records']}
    for split,expected in (('train',7238),('val',1436)):
        rows=[json.loads(line) for line in (dataset/f'prepared/{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len(rows)==expected and all(row['split']==split and not records[row['image']]['issues'] for row in rows)
        for suffix in ('txt','jsonl'):
            shutil.copy2(dataset/f'prepared/{split}.{suffix}',run/f'input/{split}.{suffix}')
    data={'path':str(run/'input'),'train':'train.txt','val':'val.txt','nc':2,'names':{0:'smoke',1:'fire'}}
    (run/'input/data.yaml').write_text(yaml.safe_dump(data,sort_keys=False),encoding='utf-8')
    options=dict(data=str(run/'input/data.yaml'),epochs=50,patience=10,imgsz=640,batch=batch,device=0,workers=0,amp=True,cache=False,optimizer='AdamW',lr0=.001,seed=42,save=True,save_period=1,project=str(run),name='training',exist_ok=False,resume=False,pretrained=True,deterministic=True)
    resolved=vars(get_cfg(overrides=options))
    readiness={'prepared_at':utc(),'train':audit['prepared_counts']['train'],'val':audit['prepared_counts']['val'],'excluded_images':10858,'no_known_unfixed_preparation_bug':True,'scene_independence_not_proven':True,'main_manifest_sha256':main,'input_manifest_sha256':{p.name:digest(p) for p in (run/'input').iterdir()},'original_weights':provenance,'original_weights_path':str(weights),'audit_sha256':digest(PROJECT_ROOT/'reports/dfire/audit.json'),'free_disk_bytes':shutil.disk_usage(PROJECT_ROOT).free,'compute_apps_before_start':compute.stdout.strip(),'read_only_jpeg_policy':'PIL verify and full decode; no auto-repair; label cache outside raw','test_used':False,'versions':{name:importlib.metadata.version(name) for name in ('torch','torchvision','ultralytics','numpy','opencv-python')}}
    atomic_json(run/'readiness.json',readiness)
    atomic_json(run/'configuration.json',{'id':identifier,'overrides':options,'resolved_defaults':resolved,'best_rule':'Maximum val mAP50-95 (fitness weights [0,0,0,1]); latest tied fitness saved by library','lr_schedule':f"LambdaLR linear: max(1-epoch/50,0)*(1-lrf)+lrf; lrf={resolved['lrf']}, cos_lr={resolved['cos_lr']}; warmup_epochs={resolved['warmup_epochs']}",'test_used':False})
    atomic_json(run/'input-verification-before.json',verify_inputs(run))
    # Обидва JPEG, які раніше переписувала бібліотека, тепер перевіряються без запису.
    for split,name in (('train','WEB07199.jpg'),('val','WEB07535.jpg')):
        path=dataset/f'raw/data/{split}/images/{name}'
        before=digest(path)
        readonly_check_image(str(path))
        assert digest(path)==before
    atomic_json(run/'state.json',{'status':'prepared','id':identifier,'completed_epochs':0,'updated_at':utc()})
    atomic_json(LATEST,{'run_dir':str(run),'id':identifier})
    print(str(run))
    return run


def inspect_checkpoint(path, require_resume=True):
    """Лише власні/офіційні файли: torch.load із pickle не для чужих checkpoint."""
    import torch
    path=Path(path)
    checkpoint=torch.load(path,map_location='cpu',weights_only=False)
    epoch=checkpoint.get('epoch',-1)
    model=checkpoint.get('ema') or checkpoint.get('model')
    if model is None or model.names != {0:'smoke',1:'fire'}:
        raise RuntimeError('Checkpoint не має очікуваної моделі/класів.')
    if not all(bool(torch.isfinite(v).all()) for v in model.state_dict().values() if torch.is_tensor(v) and v.is_floating_point()):
        raise RuntimeError('NaN/Inf у checkpoint.')
    optimizer=checkpoint.get('optimizer')
    resumable=isinstance(epoch,int) and epoch>=0 and isinstance(optimizer,dict) and bool(optimizer.get('state')) and bool(optimizer.get('param_groups'))
    if require_resume and not resumable:
        raise RuntimeError('Файл придатний лише для inference: немає номера епохи або optimizer state.')
    if resumable:
        scaler=checkpoint.get('scaler')
        if checkpoint.get('train_args',{}).get('amp',True) and (not isinstance(scaler,dict) or not scaler or any(not math.isfinite(float(value)) for value in scaler.values())):
            raise RuntimeError('Missing or non-finite AMP scaler state.')
        if not isinstance(checkpoint.get('updates'),(int,float)) or checkpoint['updates']<0:
            raise RuntimeError('Missing EMA update counter.')
        for values in optimizer['state'].values():
            for value in values.values():
                if torch.is_tensor(value) and value.is_floating_point() and not bool(torch.isfinite(value).all()):
                    raise RuntimeError('NaN/Inf optimizer state.')
    result={'file':str(path),'sha256':digest(path),'bytes':path.stat().st_size,'epoch_zero_based':epoch,'completed_epochs':epoch+1 if epoch>=0 else None,'resumable':resumable,'optimizer_present':optimizer is not None,'scaler_present':bool(checkpoint.get('scaler')),'ema_updates':checkpoint.get('updates'),'train_epochs':checkpoint.get('train_args',{}).get('epochs'),'data':checkpoint.get('train_args',{}).get('data'),'names':model.names,'fitness':checkpoint.get('train_metrics',{}).get('fitness'),'best_fitness':checkpoint.get('best_fitness')}
    del checkpoint,model
    return result


def choose_resume(run):
    run=Path(run)
    state=load_json(run/'state.json')
    if state['status']=='completed':
        raise RuntimeError('Запуск уже завершений; нове донавчання не є resume.')
    if is_locked(run/'run.lock'):
        raise RuntimeError('Цей запуск ще працює; другий процес заборонено.')
    candidates=[run/'training/weights/last.pt',run/'training/weights/resume-last.pt']
    candidates+=sorted((run/'training/weights').glob('epoch*.pt'),key=lambda p:int(p.stem.removeprefix('epoch')),reverse=True)
    failures=[]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            info=inspect_checkpoint(candidate)
            recorded=run/'checkpoints'/f"epoch{info['epoch_zero_based']}.json"
            if recorded.exists() and load_json(recorded)['sha256']!=info['sha256']:
                raise RuntimeError('Checkpoint SHA-256 differs from the hash recorded at save time.')
            assert info['completed_epochs']<info['train_epochs']
            assert Path(info['data']).resolve()==(run/'input/data.yaml').resolve()
            atomic_json(run/'resume-selection.json',{'selected_at':utc(),'checkpoint':info,'rejected':failures})
            return candidate
        except Exception as error:
            failures.append({'path':str(candidate),'error':str(error)})
    atomic_json(run/'resume-selection.json',{'selected_at':utc(),'checkpoint':None,'rejected':failures})
    raise RuntimeError('Немає справного checkpoint зі станом для resume.')


def stage_resume(run, checkpoint_path):
    """Відкотити журнал і best до вибраної епохи; зберегти попередні артефакти."""
    import torch
    run=Path(run)
    checkpoint_path=Path(checkpoint_path)
    info=inspect_checkpoint(checkpoint_path)
    recorded=run/'checkpoints'/f"epoch{info['epoch_zero_based']}.json"
    if recorded.exists() and load_json(recorded)['sha256']!=info['sha256']:
        raise RuntimeError('Checkpoint SHA-256 changed before Resume.')
    if Path(info['data']).resolve()!=(run/'input/data.yaml').resolve():
        raise RuntimeError('Checkpoint належить іншому запуску.')
    payload=torch.load(checkpoint_path,map_location='cpu',weights_only=False)
    history=payload.get('train_results') or {}
    epochs=history.get('epoch',[])
    if len(epochs)!=info['completed_epochs'] or int(epochs[-1])!=info['completed_epochs']:
        raise RuntimeError('Checkpoint не містить узгодженого журналу завершених епох.')
    best_path=None
    choices=[run/'training/weights/best.pt',checkpoint_path]
    choices+=sorted((run/'training/weights').glob('epoch*.pt'),reverse=True)
    for candidate in choices:
        try:
            candidate_info=inspect_checkpoint(candidate)
            if candidate_info['completed_epochs']<=info['completed_epochs'] and candidate_info['fitness']==info['best_fitness']:
                best_path=candidate
                break
        except Exception:
            continue
    if best_path is None:
        raise RuntimeError('Не знайдено справний best до епохи resume; журнал не змінено.')
    archive=run/'resume-history'/('before_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6])
    archive.mkdir(parents=True,exist_ok=False)
    shutil.copy2(checkpoint_path,archive/'selected-resume.pt')
    shutil.copy2(best_path,archive/'selected-best.pt')
    for name in ('results.csv',):
        if (run/'training'/name).exists(): shutil.copy2(run/'training'/name,archive/name)
    for name in ('epoch-times.jsonl','state.json'):
        if (run/name).exists(): shutil.copy2(run/name,archive/name)
    weights=run/'training/weights'
    (archive/'weights').mkdir()
    for path in weights.glob('*.pt'):
        shutil.copy2(path,archive/'weights'/path.name)
    with (run/'training/results.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(history))
        writer.writeheader()
        writer.writerows(dict(zip(history,values)) for values in zip(*history.values()))
    timings=run/'epoch-times.jsonl'
    if timings.exists():
        retained=[line for line in timings.read_text().splitlines() if json.loads(line)['epoch']<=info['completed_epochs']]
        timings.write_text('\n'.join(retained)+'\n',encoding='utf-8')
    for path in weights.glob('epoch*.pt'):
        if int(path.stem.removeprefix('epoch'))>info['epoch_zero_based']:
            path.unlink()  # Попередню версію вже скопійовано в archive/weights.
    shutil.copy2(archive/'selected-best.pt',weights/'best.pt')
    shutil.copy2(archive/'selected-resume.pt',weights/'last.pt')
    atomic_json(archive/'resume-plan.json',{'checkpoint':info,'history_rows':len(epochs),'best_from':str(best_path),'archive':str(archive),'restore_optimizer_scaler_ema_stopper':True})
    return archive/'selected-resume.pt'


def worker(run,resume_path=None):
    import torch
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect.train import DetectionTrainer
    import ultralytics.data.dataset as dataset_module
    import ultralytics.data.utils as data_utils
    from unittest.mock import patch
    run=Path(run)
    with process_lock(run/'run.lock'),process_lock(PROJECT_ROOT/'.cache/full-training-gpu0.lock'):
        config=load_json(run/'configuration.json')
        previous_state=load_json(run/'state.json')
        if previous_state.get('status')!='prepared':
            if not resume_path:
                raise RuntimeError('Existing run requires checked Resume; a fresh start cannot reuse its folder.')
            atomic_json(run/'session-history'/('before_'+uuid.uuid4().hex+'.json'),previous_state)
        state={'id':config['id'],'status':'running','pid':os.getpid(),'started_at':utc(),'completed_epochs':0,'batch':config['overrides']['batch'],'device':'cuda:0','losses_finite':True,'resume_checkpoint':str(resume_path) if resume_path else None}
        prior_wall=previous_state.get('wall_seconds',0)
        prior_allocated=previous_state.get('peak_allocated_bytes',0)
        prior_reserved=previous_state.get('peak_reserved_bytes',0)
        atomic_json(run/'state.json',state)
        start=time.perf_counter()
        try:
            assert torch.cuda.is_available(),'CUDA недоступна; CPU fallback заборонено.'
            torch.cuda.set_device(0)
            torch.cuda.reset_peak_memory_stats(0)
            state['gpu_name']=torch.cuda.get_device_name(0)
            state['input_verification']=verify_inputs(run)
            model_path=resume_path or load_json(run/'readiness.json')['original_weights_path']
            if resume_path:
                resume_info=inspect_checkpoint(resume_path)
                state['completed_epochs']=resume_info['completed_epochs']
                resume_path=stage_resume(run,resume_path)
                model_path=resume_path
                state['resume_checkpoint']=str(resume_path)
            model=YOLO(str(model_path))
            session='session_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6]
            self_run=run

            class BaselineTrainer(DetectionTrainer):
                def _handle_nan_recovery(self,epoch):
                    if self.loss is not None and not bool(torch.isfinite(self.loss).all()):
                        raise FloatingPointError('NaN/Inf training loss; no silent epoch retry')
                    if self.fitness is not None and not math.isfinite(float(self.fitness)):
                        raise FloatingPointError('NaN/Inf validation fitness')
                    return False

                def save_model(self):
                    if not all(bool(torch.isfinite(v).all()) for v in self.ema.ema.state_dict().values() if torch.is_tensor(v) and v.is_floating_point()):
                        raise FloatingPointError('NaN/Inf EMA before serialization')
                    return super().save_model()

                def final_eval(self):
                    # last/best стають inference-файлами; окремо лишаємо повний стан.
                    if self.last.exists():
                        temporary=self.wdir/'resume-last.tmp'
                        shutil.copy2(self.last,temporary)
                        os.replace(temporary,self.wdir/'resume-last.pt')
                        inspect_checkpoint(self.wdir/'resume-last.pt')
                    return super().final_eval()

            epoch_start_time=[None]
            def update(trainer):
                free,total=torch.cuda.mem_get_info(0)
                state.update(updated_at=utc(),peak_allocated_bytes=max(prior_allocated,torch.cuda.max_memory_allocated(0)),peak_reserved_bytes=max(prior_reserved,torch.cuda.max_memory_reserved(0)),free_vram_bytes=free,total_vram_bytes=total,wall_seconds=prior_wall+time.perf_counter()-start,active_device=str(trainer.device))
                atomic_json(run/'state.json',state)

            def train_start(trainer):
                assert len(trainer.train_loader.dataset)==7238 and len(trainer.test_loader.dataset)==1436
                assert trainer.device.type=='cuda' and trainer.args.optimizer=='AdamW'
                state.update(actual_train_images=7238,actual_val_images=1436,actual_batch=trainer.batch_size)
                atomic_json(run/'optimizer-runtime.json',{'class':type(trainer.optimizer).__name__,'parameter_groups':[{k:v for k,v in group.items() if k!='params'} for group in trainer.optimizer.param_groups],'scheduler_class':type(trainer.scheduler).__name__})
                update(trainer)

            def epoch_start(trainer):
                trainer._oom_retries=3
                epoch_start_time[0]=time.perf_counter()
                state.update(active_epoch=trainer.epoch+1,batch_in_epoch=0)
                update(trainer)

            def batch_end(trainer):
                if not bool(torch.isfinite(trainer.loss).all()):
                    raise FloatingPointError('NaN/Inf training loss')
                state['batch_in_epoch']+=1
                if state['batch_in_epoch']%32==0:
                    state['latest_loss']=float(trainer.loss.detach().cpu())
                    update(trainer)

            def saved(trainer):
                if not all(math.isfinite(float(value)) for value in trainer.metrics.values()):
                    raise FloatingPointError('NaN/Inf validation metric or loss')
                periodic=trainer.wdir/f'epoch{trainer.epoch}.pt'
                checkpoint=inspect_checkpoint(periodic)
                atomic_json(run/'checkpoints'/f'epoch{trainer.epoch}.json',checkpoint)
                state.update(completed_epochs=trainer.epoch+1,latest_checkpoint=checkpoint,best_fitness=float(trainer.best_fitness),current_fitness=float(trainer.fitness))
                if trainer.epoch==trainer.start_epoch:
                    state['first_epoch_input_verification']=verify_inputs(run)
                    atomic_json(run/'input-verification-first-epoch.json',state['first_epoch_input_verification'])
                update(trainer)

            def fitted(trainer):
                if epoch_start_time[0] is not None and state.get('completed_epochs')==trainer.epoch+1:
                    timing={'epoch':trainer.epoch+1,'seconds':time.perf_counter()-epoch_start_time[0],'session':session,'measured_at':utc()}
                    with (run/'epoch-times.jsonl').open('a',encoding='utf-8') as out:
                        out.write(json.dumps(timing)+'\n')
                    epoch_start_time[0]=None
                update(trainer)

            for name,callback in (('on_train_start',train_start),('on_train_epoch_start',epoch_start),('on_train_batch_end',batch_end),('on_model_save',saved),('on_fit_epoch_end',fitted)):
                model.add_callback(name,callback)
            original_load=dataset_module.load_dataset_cache_file
            original_save=dataset_module.save_dataset_cache_file
            def location(path):
                result=PROJECT_ROOT/'.cache/ultralytics-labels'/('full-readonly-v2-'+hashlib.sha256(str(path).encode()).hexdigest()+'.cache')
                result.parent.mkdir(parents=True,exist_ok=True)
                return result
            def load(path): return original_load(location(path))
            def save(prefix,path,payload,version): return original_save(prefix,location(path),payload,version)
            options=config['overrides'].copy()
            if resume_path:
                options={'resume':str(resume_path),'data':str(run/'input/data.yaml'),'device':0,'workers':0,'cache':False,'save_dir':str(run/'training')}
            atomic_json(run/f'command-{session}.json',{'argv':sys.argv,'pid':os.getpid(),'resume':str(resume_path) if resume_path else None,'options':options,'script_sha256':digest(Path(__file__))})
            with patch.object(dataset_module,'load_dataset_cache_file',load),patch.object(dataset_module,'save_dataset_cache_file',save),patch.object(data_utils,'check_image',readonly_check_image):
                model.train(trainer=BaselineTrainer,**options)
            state['final_input_verification']=verify_inputs(run)
            state.update(status='completed',finished_at=utc(),reason='max_epochs' if state['completed_epochs']>=50 else 'early_stopping',best_epoch_one_based=model.trainer.stopper.best_epoch,final_best_metrics=model.trainer.metrics)
            update(model.trainer)
        except BaseException as error:
            state.update(status='failed',finished_at=utc(),error_type=type(error).__name__,error=str(error),cuda_oom=isinstance(error,torch.cuda.OutOfMemoryError) or ('cuda' in str(error).lower() and 'out of memory' in str(error).lower()))
            (run/f'error-{int(time.time())}.txt').write_text(traceback.format_exc(),encoding='utf-8')
            if state['cuda_oom']:
                state['next_action']='Підготуйте новий запуск -Action Start -Batch 2; це зміна базового експерименту, не прихований CPU fallback.'
            atomic_json(run/'state.json',state)
            traceback.print_exc()
            return 1
    return 0


def status(run):
    run=Path(run)
    state=load_json(run/'state.json')
    state['process_lock_held']=is_locked(run/'run.lock')
    if state['status']=='running' and not state['process_lock_held']:
        state['observed_status']='interrupted_or_process_missing'
    timings=[json.loads(line) for line in (run/'epoch-times.jsonl').read_text().splitlines()] if (run/'epoch-times.jsonl').exists() else []
    if timings:
        values=[row['seconds'] for row in timings[-3:]]
        mean=sum(values)/len(values)
        state['recent_mean_epoch_seconds']=mean
        state['eta_to_50_seconds_ignoring_early_stopping']=max(0,50-state['completed_epochs'])*mean
    state['run_dir']=str(run)
    print(json.dumps(state,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','worker','status','select-resume','inspect'])
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--batch',type=int,choices=(4,2),default=4)
    args=parser.parse_args()
    if args.action=='prepare': prepare(args.batch)
    elif args.action=='inspect': print(json.dumps(inspect_checkpoint(args.checkpoint),ensure_ascii=False,indent=2))
    elif args.action=='select-resume': print(choose_resume(args.run_dir or latest_run()))
    elif args.action=='status': status(args.run_dir or latest_run())
    else:
        return worker(args.run_dir or latest_run(),args.checkpoint)
    return 0


if __name__=='__main__':
    sys.exit(main())
