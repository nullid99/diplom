import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.request import urlopen
import socket
from unittest.mock import patch

import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.database import build_engine, get_session
from backend.app.models import AnalysisRun, ModelVersion, VideoSource
from backend.app.analysis_service import CreateAnalysis, checksum, create_run, request_cancel
from backend.app.analysis_worker import WorkerLease, claim, run_job
from scripts.db import connect, migration_config


class TestDetector:
    """Тільки fixture: жодного імпорту torch/Ultralytics та жодного GPU."""
    closed=0
    def __init__(self,weights,device,imgsz):
        assert device=='cpu'
    def detect(self,frame,thresholds):
        return [dict(class_id=0,class_name='smoke',confidence=.9,xyxy=[2.,2.,30.,30.])]
    def close(self): TestDetector.closed+=1


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox=Path(tempfile.mkdtemp(prefix='analysis-test-',dir=PROJECT_ROOT/'.tmp'))
        cls.settings=replace(get_settings(),storage_root=cls.sandbox/'storage',analysis_queue_limit=2)
        cls.settings.storage_root.mkdir()
        cls.name='firevision_analysis_test_'+uuid.uuid4().hex[:12]
        with connect('postgres') as connection:
            connection.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(cls.name)))
        cls.engine=build_engine(get_settings().database_url().set(database=cls.name))
        with cls.engine.begin() as connection:
            command.upgrade(migration_config(connection),'head')
            command.upgrade(migration_config(connection),'head')
        cls.sample=cls.sandbox/'technical-test-not-training.mp4'
        subprocess.run([str(cls.settings.ffmpeg_path),'-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=10','-t','1.2','-vf',"select='if(lt(t,0.6),not(mod(n,2)),1)'",'-fps_mode','vfr','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(cls.sample)],capture_output=True,check=True,timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        with connect('postgres') as connection:
            connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cls.name)))

    def setUp(self):
        with self.engine.begin() as connection:
            connection.execute(sa.text('TRUNCATE events, analysis_runs, model_versions, video_sources CASCADE'))
        from backend.app.main import app
        self.app=app
        def sessions():
            with Session(self.engine) as session: yield session
        app.dependency_overrides[get_session]=sessions
        self.patches=[patch('backend.app.analysis_api.get_settings',return_value=self.settings),patch('backend.app.analysis_api.get_engine',return_value=self.engine),patch('backend.app.config.get_settings',return_value=self.settings)]
        for item in self.patches: item.start()
        self.client=TestClient(app)
        self.source_id=uuid.uuid4(); self.model_id=uuid.uuid4()
        self.original=self.settings.storage_root/f'video-{self.source_id}.mp4'
        self.original.write_bytes(self.sample.read_bytes())
        self.weights=self.settings.storage_root/f'test-only-{self.model_id}.fixture'
        self.weights.write_bytes(b'isolated fake detector fixture, never real YOLO weights')
        with Session(self.engine) as session:
            session.add(VideoSource(id=self.source_id,name='Технічний тест, не навчальні дані',original_filename='test.mp4',file_path=self.original.name,sha256=checksum(self.original)))
            session.commit()

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()
        for item in reversed(self.patches): item.stop()

    def add_model(self):
        with Session(self.engine) as session:
            session.add(ModelVersion(id=self.model_id,name='ТІЛЬКИ ТЕСТ: не YOLO',architecture='YOLO11n',weights_path=self.weights.name,weights_sha256=checksum(self.weights),class_mapping={'0':'smoke','1':'fire'},training_metadata={'test_fixture':True}))
            session.commit()

    def payload(self,**options):
        return dict(video_source_id=str(self.source_id),model_version_id=str(self.model_id),settings={'analysis_fps':2,**options})

    def start(self,**options):
        response=self.client.post('/api/analysis-runs',json=self.payload(**options))
        self.assertEqual(response.status_code,201,response.text)
        return uuid.UUID(response.json()['id'])

    def test_empty_models_validation_and_unknown_run(self):
        self.assertEqual(self.client.get('/api/model-versions').json()['items'],[])
        self.assertEqual(self.client.post('/api/analysis-runs',json=self.payload()).status_code,409)
        self.assertEqual(self.client.get('/api/analysis-runs').json()['total'],0)
        self.assertEqual(self.client.get(f'/api/analysis-runs/{uuid.uuid4()}').status_code,404)
        for settings in ({'analysis_fps':0},{'imgsz':641},{'smoke_threshold':1.1},{'device':'cuda:1'},{'analysis_fps':'NaN'},{'unexpected':1}):
            self.assertEqual(self.client.post('/api/analysis-runs',json=self.payload(**settings)).status_code,422,settings)

    def test_registration_rejects_active_run_before_loading_weights(self):
        from scripts.register_model import checked_report
        isolated_root=self.sandbox/uuid.uuid4().hex
        active=isolated_root/'runs/full/fake-active'
        active.mkdir(parents=True)
        (active/'state.json').write_text(json.dumps({'status':'running'}))
        report=isolated_root/'report.json'
        report.write_text(json.dumps({'run_dir':str(active)}))
        loaded='torch' in sys.modules
        with patch('scripts.register_model.PROJECT_ROOT',isolated_root):
            with self.assertRaisesRegex(ValueError,'ще не завершено'): checked_report(report)
        self.assertTrue(loaded or 'torch' not in sys.modules)

    def test_files_hash_queue_snapshot_and_pending_cancel(self):
        self.add_model()
        self.assertTrue(self.client.get('/api/model-versions').json()['items'][0]['available'])
        self.assertEqual(self.client.post('/api/analysis-runs',json=self.payload(device='cuda:0')).status_code,409)
        first=self.start(); self.start()
        self.assertEqual(self.client.post('/api/analysis-runs',json=self.payload()).status_code,429)
        reply=self.client.post(f'/api/analysis-runs/{first}/cancel').json()
        self.assertEqual(reply['status'],'stopped')
        self.assertEqual(self.client.get(f'/api/analysis-runs/{first}/files/video').status_code,409)
        with Session(self.engine) as session:
            run=session.get(AnalysisRun,first)
            run.settings_snapshot={**run.settings_snapshot,'imgsz':1280}
            with self.assertRaises(sa.exc.IntegrityError): session.commit()
        self.weights.write_bytes(b'changed')
        self.assertFalse(self.client.get('/api/model-versions').json()['items'][0]['available'])
        self.assertEqual(self.client.post('/api/analysis-runs',json=self.payload()).status_code,409)

    def test_claim_single_worker_and_crash_recovery(self):
        self.add_model(); run_id=self.start()
        with WorkerLease(self.engine) as lease:
            with self.assertRaises(RuntimeError):
                with WorkerLease(self.engine): pass
            identity=claim(self.engine)
            self.assertEqual(identity[0],run_id)
            self.assertIsNone(claim(self.engine))
        with WorkerLease(self.engine) as lease:
            self.assertEqual(lease.recover(self.settings),1)
        self.assertEqual(self.client.get(f'/api/analysis-runs/{run_id}').json()['status'],'failed')

    def test_concurrent_claim_and_queue_capacity(self):
        self.add_model()
        def submit(_):
            with Session(self.engine) as session:
                try: create_run(session,CreateAnalysis.model_validate(self.payload()),self.settings); return 201
                except Exception as error:
                    if getattr(error,'status_code',None)==429: return 429
                    raise
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(sorted(pool.map(submit,range(3))),[201,201,429])
        with WorkerLease(self.engine):
            with ThreadPoolExecutor(max_workers=3) as pool:
                results=list(pool.map(lambda _:claim(self.engine),range(3)))
            claimed=[item[0] for item in results if item]
            self.assertEqual(len(claimed),2)
            self.assertEqual(len(set(claimed)),2)

    def test_api_detects_abandoned_worker_without_pid_assumption(self):
        self.add_model(); run_id=self.start()
        with WorkerLease(self.engine):
            claim(self.engine)
            self.assertEqual(self.client.get(f'/api/analysis-runs/{run_id}').json()['status'],'running')
        self.assertEqual(self.client.get(f'/api/analysis-runs/{run_id}').json()['status'],'failed')

    def test_pipeline_vfr_results_ranges_and_no_dataset_mutation(self):
        self.add_model(); run_id=self.start()
        before=checksum(self.original)
        with WorkerLease(self.engine) as lease:
            identity=claim(self.engine)
            self.assertEqual(run_job(lease,identity,self.settings,TestDetector),0)
        reply=self.client.get(f'/api/analysis-runs/{run_id}').json()
        self.assertEqual(reply['status'],'completed',reply)
        self.assertEqual(self.client.post(f'/api/analysis-runs/{run_id}/cancel').json()['status'],'completed')
        self.assertEqual(reply['progress'],1)
        self.assertEqual(checksum(self.original),before)
        self.assertEqual(reply['summary_metrics']['frames_read'],9)
        self.assertEqual(reply['summary_metrics']['frames_analyzed'],3)
        detections=self.client.get(f'/api/analysis-runs/{run_id}/files/detections').text.splitlines()
        self.assertEqual(len(detections),9)
        self.assertTrue(any(not json.loads(line)['analyzed'] for line in detections))
        timestamps=[json.loads(line)['time_seconds'] for line in detections]
        self.assertGreater(len(set(round(b-a,3) for a,b in zip(timestamps,timestamps[1:]))),1)
        video=self.client.get(f'/api/analysis-runs/{run_id}/files/video',headers={'Range':'bytes=10-39'})
        self.assertEqual(video.status_code,206)
        self.assertEqual(len(video.content),30)
        self.assertEqual(self.client.get(f'/api/analysis-runs/{run_id}/files/unknown').status_code,404)
        self.assertGreater(TestDetector.closed,0)

    def test_irregular_timestamps_and_last_frame_duration(self):
        import numpy as np
        from backend.app.analysis_media import VideoSink,validate_video
        folder=self.sandbox/uuid.uuid4().hex
        folder.mkdir()
        times=[dict(time_seconds=0.,duration_seconds=.1),dict(time_seconds=.1,duration_seconds=.23),dict(time_seconds=.33,duration_seconds=.37)]
        timeline=folder/'times.jsonl'
        timeline.write_text('\n'.join(json.dumps(row) for row in times)+'\n',encoding='utf-8')
        metadata={'frames':3,'width':160,'height':120,'duration_seconds':.7,'last_duration_seconds':.37}
        sink=VideoSink(folder/'variable.mp4',metadata,self.settings,lambda:None)
        try:
            for row in times: sink.frame(np.zeros((120,160,3),dtype=np.uint8),row['time_seconds'],row['duration_seconds'])
            sink.close(success=True)
        except BaseException:
            sink.close()
            raise
        validate_video(folder/'variable.mp4',timeline,metadata,self.settings,lambda:None)

    def test_yolo_adapter_separate_thresholds_without_loading_ml(self):
        torch_was_loaded='torch' in sys.modules
        import numpy as np
        from types import SimpleNamespace
        from backend.app.analysis_detector import YoloDetector
        calls=[]
        class ModelStub:
            names={0:'smoke',1:'fire'}
            predictor=SimpleNamespace(model=SimpleNamespace(device=SimpleNamespace(type='cpu')))
            def predict(self,*args,**kwargs):
                calls.append(kwargs)
                return [SimpleNamespace(boxes=SimpleNamespace(cls=np.array([0,1]),conf=np.array([.4,.4]),xyxy=np.array([[1.,1.,10.,10.],[1.,1.,10.,10.]])))]
        adapter=YoloDetector.__new__(YoloDetector)
        adapter.model=ModelStub(); adapter.device='cpu'; adapter.imgsz=640
        found=adapter.detect(np.zeros((20,20,3),dtype=np.uint8),{'smoke':.7,'fire':.2})
        self.assertEqual([row['class_name'] for row in found],['fire'])
        self.assertEqual(calls[0]['device'],'cpu')
        self.assertEqual(calls[0]['conf'],.2)
        self.assertTrue(torch_was_loaded or 'torch' not in sys.modules)

    def test_worker_failure_cleanup(self):
        self.add_model(); run_id=self.start()
        class BrokenDetector(TestDetector):
            def detect(self,*args): raise RuntimeError('test-only exception')
        with WorkerLease(self.engine) as lease:
            identity=claim(self.engine)
            self.assertEqual(run_job(lease,identity,self.settings,BrokenDetector),1)
        result=self.client.get(f'/api/analysis-runs/{run_id}').json()
        self.assertEqual(result['status'],'failed')
        self.assertIsNone(result['result_paths'])
        self.assertFalse((self.settings.storage_root/f'tmp/analysis/{run_id}-{identity[1]}').exists())
        self.assertEqual(self.client.get(f'/api/analysis-runs/{run_id}/files/video').status_code,409)

    def test_commit_failure_does_not_publish_results(self):
        self.add_model(); run_id=self.start()
        with self.engine.begin() as connection:
            connection.execute(sa.text("ALTER TABLE analysis_runs ADD CONSTRAINT test_no_complete CHECK (status <> 'completed')"))
        try:
            with WorkerLease(self.engine) as lease:
                identity=claim(self.engine)
                self.assertEqual(run_job(lease,identity,self.settings,TestDetector),1)
            result=self.client.get(f'/api/analysis-runs/{run_id}').json()
            self.assertEqual(result['status'],'failed')
            self.assertIsNone(result['result_paths'])
            self.assertFalse((self.settings.storage_root/f'results/analysis/{run_id}/{identity[1]}').exists())
        finally:
            with self.engine.begin() as connection:
                connection.execute(sa.text('ALTER TABLE analysis_runs DROP CONSTRAINT test_no_complete'))

    def test_active_cancel_is_request_until_worker_stops(self):
        self.add_model(); run_id=self.start()
        class CancellingDetector(TestDetector):
            def detect(inner,*args):
                with Session(self.engine) as session: request_cancel(session,run_id)
                current=self.client.get(f'/api/analysis-runs/{run_id}').json()
                self.assertEqual(current['status'],'running')
                time.sleep(1.1)
                return super().detect(*args)
        with WorkerLease(self.engine) as lease:
            identity=claim(self.engine)
            self.assertEqual(run_job(lease,identity,self.settings,CancellingDetector),20)
        current=self.client.get(f'/api/analysis-runs/{run_id}').json()
        self.assertEqual(current['status'],'stopped')
        self.assertIsNone(current['result_paths'])

    def test_websocket_snapshot_reconnect_and_origin(self):
        self.add_model(); run_id=self.start()
        url=f'/api/analysis-runs/ws?selected_id={run_id}'
        with self.client.websocket_connect(url,headers={'origin':'http://127.0.0.1:5173'}) as socket:
            data=socket.receive_json()
            self.assertEqual(data['selected']['status'],'pending')
        self.client.post(f'/api/analysis-runs/{run_id}/cancel')
        with self.client.websocket_connect(url,headers={'origin':'http://127.0.0.1:5173'}) as socket:
            self.assertEqual(socket.receive_json()['selected']['status'],'stopped')
        with self.assertRaises(Exception):
            with self.client.websocket_connect(url,headers={'origin':'http://untrusted.invalid'}): pass

    def test_websocket_real_worker_progress(self):
        self.add_model(); run_id=self.start(analysis_fps=10)
        ready=threading.Event()
        class SlowTestDetector(TestDetector):
            def detect(self,*args):
                ready.set(); time.sleep(.3)
                return super().detect(*args)
        codes=[]
        def work():
            with WorkerLease(self.engine) as lease:
                codes.append(run_job(lease,claim(self.engine),self.settings,SlowTestDetector))
        thread=threading.Thread(target=work)
        thread.start()
        try:
            self.assertTrue(ready.wait(timeout=10))
            observed=[]
            with self.client.websocket_connect(f'/api/analysis-runs/ws?selected_id={run_id}',headers={'origin':'http://127.0.0.1:5173'}) as socket:
                for _ in range(8):
                    item=socket.receive_json()['selected']
                    observed.append(item)
                    if item['status'] in ('completed','failed','stopped'): break
            self.assertTrue(any(item['status']=='running' and 0<item['progress']<1 for item in observed),observed)
            self.assertEqual(observed[-1]['status'],'completed')
            self.assertEqual(observed[-1]['progress'],1)
        finally: thread.join(timeout=15)
        self.assertEqual(codes,[0])

    def test_actual_process_crash_releases_lease(self):
        self.add_model(); run_id=self.start()
        script="from tests.analysis_test_app import engine; from backend.app.analysis_worker import WorkerLease,claim; import os; lease=WorkerLease(engine); lease.__enter__(); assert claim(engine); os._exit(0)"
        environment={**os.environ,'FIREVISION_ANALYSIS_TEST_DATABASE':self.name,'STORAGE_ROOT':str(self.settings.storage_root)}
        subprocess.run([str(PROJECT_ROOT/'.venv-api/Scripts/python.exe'),'-c',script],env=environment,cwd=PROJECT_ROOT,capture_output=True,check=True,timeout=20)
        for _ in range(30):
            response=self.client.get(f'/api/analysis-runs/{run_id}')
            if response.json().get('status')=='failed': break
            time.sleep(.1)
        self.assertEqual(response.json()['status'],'failed',response.text)

    def browser(self,mode):
        def free_port():
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0)); return probe.getsockname()[1]
        port,ui=free_port(),free_port()
        environment={**os.environ,'FIREVISION_ANALYSIS_TEST_DATABASE':self.name,'STORAGE_ROOT':str(self.settings.storage_root),'CORS_ORIGINS':f'http://127.0.0.1:{ui}'}
        server=subprocess.Popen([str(PROJECT_ROOT/'.venv-api/Scripts/python.exe'),'-m','uvicorn','tests.analysis_test_app:app','--host','127.0.0.1','--port',str(port),'--ws','wsproto'],cwd=PROJECT_ROOT,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                try:
                    with urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1): break
                except OSError: time.sleep(.1)
            subprocess.run(['node','scripts/analysis-browser.mjs',f'http://127.0.0.1:{port}',str(ui),mode,str(self.sandbox/f'browser-{mode}-TEST-ONLY.png')],cwd=PROJECT_ROOT,env=environment,check=True,timeout=90)
        finally:
            server.terminate()
            server.wait(timeout=10)

    def test_browser_empty_start_cancel_and_reconnect(self):
        self.browser('empty')

    def test_browser_results_and_seek(self):
        self.add_model(); self.start()
        with WorkerLease(self.engine) as lease:
            self.assertEqual(run_job(lease,claim(self.engine),self.settings,TestDetector),0)
        self.browser('results')


if __name__=='__main__': unittest.main()
