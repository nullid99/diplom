"""Use the existing upload/analysis APIs and separate real worker with one frozen configuration."""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from backend.app.config import PROJECT_ROOT
from scripts.fetch_firesense import ROOT,digest
from scripts.firesense_prepare import REPORT

MODEL='8c37f231-7e6e-4db4-8405-0e4f731c4b87'
CONFIG=dict(smoke_threshold=.25,fire_threshold=.25,imgsz=640,analysis_fps=2,device='cuda:0',
            temporal=dict(window_seconds=3,min_hits=3,min_span_seconds=1,absence_seconds=2,match_iou=.1,
                          center_distance=.12,clip_before_seconds=2,clip_after_seconds=3))


def main():
    frozen=json.loads((ROOT/'freeze.json').read_text(encoding='utf-8'))
    assert digest(ROOT/'manifest.json')==frozen['manifest_sha256']
    assert digest(ROOT/'content-review.json')==frozen['content_review_sha256']
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['labels_reviewed_before_inference']
    state_path=REPORT/'runs.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else dict(started_at=datetime.now(timezone.utc).isoformat(),configuration=CONFIG,model_id=MODEL,manifest_sha256=frozen['manifest_sha256'],runs=[])
    assert state['configuration']==CONFIG and state['manifest_sha256']==frozen['manifest_sha256']
    def save():state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    training=json.loads((PROJECT_ROOT/'runs/full/yolo11n_baseline_20261101T203432Z_b1931c45/state.json').read_text(encoding='utf-8'))
    if training['status']!='completed':raise RuntimeError('Training is not completed')
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=90) as api:
        models=api.get('/api/model-versions').raise_for_status().json()
        assert models['gpu_enabled'] and any(m['id']==MODEL and m['available'] for m in models['items'])
        for row in manifest['clips']:
            previous=next((item for item in state['runs'] if item['clip_id']==row['id']),None)
            if previous:
                current=api.get('/api/analysis-runs/'+previous['run_id']).raise_for_status().json()
                if current['status']=='completed':continue
                if current['status'] in ('running','failed','stopped'):raise RuntimeError('Existing unfinished/failed run needs inspection; no automatic duplicate: '+previous['run_id'])
                item=previous
            else:
                active=api.get('/api/analysis-runs?page_size=100').raise_for_status().json()
                if any(r['status'] in ('pending','running') for r in active['items']):raise RuntimeError('Another job is active; do not claim it')
                file=ROOT/row['file'];assert digest(file)==row['sha256']
                with file.open('rb') as stream:
                    source=api.post('/api/video-sources',data={'name':f"FIRESENSE demo {row['id']} — {row['transform']}"},files={'file':(file.name,stream,'video/mp4')}).raise_for_status().json()
                run=api.post('/api/analysis-runs',json=dict(video_source_id=source['id'],model_version_id=MODEL,settings=CONFIG)).raise_for_status().json()
                assert run['settings_snapshot']['zones']==[]
                item=dict(clip_id=row['id'],source_id=source['id'],run_id=run['id'],created=run,progress=[])
                state['runs'].append(item);save()
            print(f"{row['id']}: queued {item['run_id']}",flush=True)
            environment={**os.environ,'ANALYSIS_ALLOW_GPU':'true'}
            with (REPORT/(row['id']+'-worker.log')).open('wb') as log:
                worker=subprocess.Popen([str(PROJECT_ROOT/'.venv/Scripts/python.exe'),'-X','utf8','-u','-m','backend.app.analysis_worker','--once'],cwd=PROJECT_ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT)
                item['worker_launcher_pid']=worker.pid;save()
                deadline=time.monotonic()+300
                while True:
                    current=api.get('/api/analysis-runs/'+item['run_id']).raise_for_status().json()
                    sample=dict(at=datetime.now(timezone.utc).isoformat(),status=current['status'],progress=current['progress'],summary=current['summary_metrics'])
                    if not item['progress'] or sample['status']!=item['progress'][-1]['status'] or sample['progress']!=item['progress'][-1]['progress']:
                        item['progress'].append(sample);save()
                    if current['status'] in ('completed','failed','stopped'):
                        item['result']=current;save();break
                    if worker.poll() is not None:raise RuntimeError('Worker exited before terminal state; inspect its log')
                    if time.monotonic()>deadline:raise RuntimeError('Worker still active beyond observation deadline; left running, no duplicate launch')
                    time.sleep(.5)
                item['worker_exit_code']=worker.wait(timeout=30);save()
            if current['status']!='completed' or item['worker_exit_code']!=0:raise RuntimeError('Analysis did not complete: '+row['id'])
            (REPORT/(row['id']+'-run.json')).write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
            for kind in ('video','detections','summary'):
                response=api.get(f"/api/analysis-runs/{item['run_id']}/files/{kind}").raise_for_status()
                assert len(response.content)>0
                item.setdefault('files',{})[kind]=dict(bytes=len(response.content),sha256=hashlib.sha256(response.content).hexdigest(),relative_path=current['result_paths'][kind])
            for key,value in CONFIG.items():assert current['settings_snapshot'][key]==value
            assert current['summary_metrics']['device']=='cuda:0'
            save();print(f"{row['id']}: completed {current['summary_metrics']}",flush=True)
        state['finished_at']=datetime.now(timezone.utc).isoformat();save()


if __name__=='__main__':main()
