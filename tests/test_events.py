import json
import uuid
from unittest.mock import patch
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from tests import test_analysis as base
from backend.app.analysis_worker import WorkerLease,claim,run_job
from backend.app.event_evidence import EvidenceWriter
from backend.app.models import Event


class EventTests(base.AnalysisTests):
    def setUp(self):
        super().setUp()
        from backend.app.models import AppSetting
        with Session(self.engine) as session:
            session.query(AppSetting).delete()
            session.commit()
    def test_zones_defaults_and_immutable_snapshots(self):
        self.add_model()
        zone=dict(id='a',name='Зона',mode='exclude',x1=.1,y1=.2,x2=.3,y2=.4)
        url=f'/api/video-sources/{self.source_id}/zones'
        self.assertEqual(self.client.put(url,json={'zones':[zone]}).status_code,200)
        self.assertEqual(self.client.get(url).json()['zones'],[zone])
        self.assertEqual(self.client.put(url,json={'zones':[zone,zone]}).status_code,422)
        defaults=self.client.get('/api/analysis-defaults').json()
        defaults['temporal']['min_hits']=2
        defaults['temporal']['min_span_seconds']=.5
        self.assertEqual(self.client.put('/api/analysis-defaults',json=defaults).status_code,200)
        created=self.client.post('/api/analysis-runs',json=self.payload()).json()
        self.assertEqual(created['settings_snapshot']['zones'],[zone])
        self.client.put(url,json={'zones':[]})
        self.assertEqual(self.client.get('/api/analysis-runs/'+created['id']).json()['settings_snapshot']['zones'],[zone])
        defaults['temporal']['min_hits']=5
        self.client.put('/api/analysis-defaults',json=defaults)
        self.assertEqual(self.client.get('/api/analysis-runs/'+created['id']).json()['settings_snapshot']['temporal']['min_hits'],2)
        following=self.client.post('/api/analysis-runs',json=self.payload()).json()
        self.assertEqual(following['settings_snapshot']['temporal']['min_hits'],5)
        self.assertEqual(following['settings_snapshot']['zones'],[])
        bad={**defaults,'analysis_fps':.1}
        self.assertEqual(self.client.put('/api/analysis-defaults',json=bad).status_code,422)

    def test_real_worker_evidence_review_filters_and_idempotent_save(self):
        self.add_model()
        options=self.payload(analysis_fps=10,temporal=dict(min_hits=2,min_span_seconds=.1))
        created=self.client.post('/api/analysis-runs',json=options)
        self.assertEqual(created.status_code,201,created.text)
        identity=created.json()['id']
        # The only detector is an isolated fixture in the inherited temporary DB/storage.
        with WorkerLease(self.engine) as lease:
            lease.recover(self.settings)
            original=EvidenceWriter.__call__
            def save_twice(writer,*args):
                original(writer,*args)
                if args[0]['closure_reason'] is None:
                    with Session(self.engine) as session:
                        event=session.scalar(select(Event))
                        event.review_status='needs_review'
                        session.commit()
                original(writer,*args)
            with patch.object(EvidenceWriter,'__call__',save_twice):
                self.assertEqual(run_job(lease,claim(self.engine),self.settings,base.TestDetector),0)
        events=self.client.get('/api/events?feature_type=smoke&page_size=1').json()
        self.assertEqual(events['total'],1)
        event_id=events['items'][0]['id']
        event=self.client.get('/api/events/'+event_id).json()
        self.assertEqual(event['automatic_status'],'completed')
        self.assertEqual(event['closure_reason'],'eof')
        self.assertEqual(event['review_status'],'needs_review')
        self.assertIsNotNone(event['last_seen_seconds'])
        for kind in ('frame','clip'):
            self.assertEqual(self.client.get(f'/api/events/{event_id}/files/{kind}').status_code,200)
        review=dict(review_status='false_positive',operator_comment='Тестова перевірка українською',expected_updated_at=event['updated_at'])
        reply=self.client.patch(f'/api/events/{event_id}/review',json=review)
        self.assertEqual(reply.status_code,200,reply.text)
        self.assertEqual(self.client.patch(f'/api/events/{event_id}/review',json=review).status_code,409)
        self.assertEqual(self.client.get('/api/events?review_status=false_positive').json()['total'],1)
        self.assertEqual(self.client.get('/api/events?feature_type=fire').json()['total'],0)
        self.assertEqual(self.client.get('/api/events?since=2026-01-01T00:00:00').status_code,422)
        with Session(self.engine) as session:
            saved=session.get(Event,uuid.UUID(event_id))
            self.assertEqual(saved.operator_comment,review['operator_comment'])
            self.assertEqual(session.scalar(select(func.count()).select_from(Event)),1)

    def test_confirmed_event_is_interrupted_on_cancel_or_failure(self):
        from backend.app.analysis_worker import Cancelled
        from backend.app.analysis_media import MediaError
        self.add_model()
        self.client.post('/api/analysis-runs',json=self.payload(analysis_fps=10,temporal=dict(min_hits=2,min_span_seconds=.1)))
        class CancellingDetector(base.TestDetector):
            calls=0
            def detect(self,frame,thresholds):
                self.calls+=1
                if self.calls==3: raise Cancelled()
                return super().detect(frame,thresholds)
        with WorkerLease(self.engine) as lease:
            self.assertEqual(run_job(lease,claim(self.engine),self.settings,CancellingDetector),20)
        event=self.client.get('/api/events').json()['items'][0]
        self.assertEqual(event['automatic_status'],'interrupted')
        self.assertEqual(event['closure_reason'],'cancelled')
        self.assertTrue(event['has_frame'] and event['has_clip'])

    def test_failure_is_not_eof(self):
        from backend.app.analysis_media import MediaError
        self.add_model()
        self.client.post('/api/analysis-runs',json=self.payload(analysis_fps=10,temporal=dict(min_hits=2,min_span_seconds=.1)))
        class FailingDetector(base.TestDetector):
            calls=0
            def detect(self,frame,thresholds):
                self.calls+=1
                if self.calls==3: raise MediaError('Isolated failure')
                return super().detect(frame,thresholds)
        with WorkerLease(self.engine) as lease:
            self.assertEqual(run_job(lease,claim(self.engine),self.settings,FailingDetector),1)
        event=self.client.get('/api/events').json()['items'][0]
        self.assertEqual(event['automatic_status'],'interrupted')
        self.assertEqual(event['closure_reason'],'failed')

    def test_vfr_clip_boundaries_and_pagination(self):
        self.add_model()
        self.client.post('/api/analysis-runs',json=self.payload(analysis_fps=10,temporal=dict(min_hits=4,min_span_seconds=.6,clip_before_seconds=.05,clip_after_seconds=.2)))
        with WorkerLease(self.engine) as lease:
            self.assertEqual(run_job(lease,claim(self.engine),self.settings,base.TestDetector),0)
        event=self.client.get('/api/events').json()['items'][0]
        detail=self.client.get('/api/events/'+event['id']).json()
        region=detail['region']
        self.assertAlmostEqual(region['clip_start_seconds'],.4)
        self.assertAlmostEqual(region['clip_end_seconds'],.8)
        self.assertAlmostEqual(region['clip_confirmation_seconds'],.2)
        self.assertLessEqual(region['clip_measured_duration_seconds'],.401)
        with Session(self.engine) as session:
            original=session.get(Event,uuid.UUID(event['id']))
            # Extra aggregate only in the isolated DB, to exercise page boundaries.
            session.add(Event(analysis_run_id=original.analysis_run_id,track_key='pagination-fixture',feature_type='fire',automatic_status='completed',start_seconds=0,confirmed_seconds=.2,last_seen_seconds=.3,end_seconds=.4,closed_seconds=.4,closure_reason='absence'))
            session.commit()
        first=self.client.get('/api/events?page_size=1&page=1').json()
        second=self.client.get('/api/events?page_size=1&page=2').json()
        self.assertEqual(first['total'],2)
        self.assertNotEqual(first['items'][0]['id'],second['items'][0]['id'])
        self.assertEqual(self.client.get('/api/events?page_size=1&page=3').json()['items'],[])

    def test_excluded_detections_never_reach_events(self):
        self.add_model()
        zone=dict(id='all',name='Виключити весь кадр',mode='exclude',x1=0,y1=0,x2=1,y2=1)
        self.client.put(f'/api/video-sources/{self.source_id}/zones',json={'zones':[zone]})
        response=self.client.post('/api/analysis-runs',json=self.payload(analysis_fps=10,temporal=dict(min_hits=2,min_span_seconds=.1)))
        with WorkerLease(self.engine) as lease:
            self.assertEqual(run_job(lease,claim(self.engine),self.settings,base.TestDetector),0)
        detail=self.client.get('/api/analysis-runs/'+response.json()['id']).json()
        self.assertEqual(detail['summary_metrics']['detections_by_class'],{'smoke':0,'fire':0})
        self.assertEqual(self.client.get('/api/events').json()['total'],0)
        self.assertEqual(detail['summary_metrics']['frames_read'],9)

    def test_crash_closes_confirmed_event_without_invented_video_time(self):
        self.add_model()
        response=self.client.post('/api/analysis-runs',json=self.payload())
        with WorkerLease(self.engine):
            identity=claim(self.engine)
            with Session(self.engine) as session:
                session.add(Event(analysis_run_id=identity[0],feature_type='smoke',track_key='crash-fixture',automatic_status='confirmed',start_seconds=0,confirmed_seconds=.5,last_seen_seconds=.7))
                session.commit()
        # Lease is gone, as after a crash; API reconciles without trusting a PID.
        self.assertEqual(self.client.get('/api/analysis-runs/'+response.json()['id']).json()['status'],'failed')
        event=self.client.get('/api/events').json()['items'][0]
        self.assertEqual(event['automatic_status'],'interrupted')
        self.assertEqual(event['closure_reason'],'worker_interrupted')
        self.assertIsNone(event['closed_seconds'])
        self.assertAlmostEqual(float(event['last_seen_seconds']),.7)

    def test_browser_real_transport_in_isolated_database(self):
        import os,socket,subprocess,time
        from urllib.request import urlopen
        from backend.app.config import PROJECT_ROOT
        self.add_model()
        self.client.post('/api/analysis-runs',json=self.payload(analysis_fps=10,temporal=dict(min_hits=2,min_span_seconds=.1)))
        with WorkerLease(self.engine) as lease:
            self.assertEqual(run_job(lease,claim(self.engine),self.settings,base.TestDetector),0)
        def free_port():
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));return probe.getsockname()[1]
        port,ui=free_port(),free_port()
        environment={**os.environ,'FIREVISION_ANALYSIS_TEST_DATABASE':self.name,'STORAGE_ROOT':str(self.settings.storage_root),'CORS_ORIGINS':f'http://127.0.0.1:{ui}'}
        server=subprocess.Popen([str(PROJECT_ROOT/'.venv-api/Scripts/python.exe'),'-m','uvicorn','tests.analysis_test_app:app','--host','127.0.0.1','--port',str(port),'--ws','wsproto'],cwd=PROJECT_ROOT,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                try:
                    with urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1):break
                except OSError:time.sleep(.1)
            subprocess.run(['node','scripts/events-browser-isolated.mjs',f'http://127.0.0.1:{port}',str(ui)],env=environment,cwd=PROJECT_ROOT,check=True,timeout=90)
        finally: server.terminate();server.wait(timeout=10)
