"""Evidence is published before an idempotent event aggregate; no per-frame SQL rows."""
import json
import os
import shutil
import subprocess
import time
import uuid
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from backend.app.analysis_media import MediaError
from backend.app.config import storage_path
from backend.app.models import AnalysisRun, Event


def interrupt_events(session,run_ids,reason='worker_interrupted'):
    if run_ids:
        session.execute(sa.update(Event).where(Event.analysis_run_id.in_(run_ids),sa.or_(Event.automatic_status=='confirmed',Event.closure_reason=='eof')).values(
            automatic_status='interrupted',closure_reason=reason,closed_seconds=None,end_seconds=None,updated_at=sa.func.clock_timestamp()))


class EvidenceWriter:
    def __init__(self,engine,run_id,token,source,settings,control,timeline=None):
        self.engine=engine;self.run_id=run_id;self.token=token
        self.source=source;self.settings=settings;self.control=control
        self.timeline=timeline

    def __call__(self,event,frame,metadata,config):
        import cv2
        identifier=uuid.uuid5(self.run_id,event['track_key'])
        relative=f'event-evidence/{self.run_id}/{identifier}'
        final=storage_path(relative,self.settings.storage_root)
        if not final.exists():
            private=storage_path(f'tmp/event-evidence/{identifier}-{uuid.uuid4().hex}',self.settings.storage_root)
            private.mkdir(parents=True)
            try:
                if frame is None: raise MediaError('Відсутній кадр підтвердження події.')
                image=frame.copy();height,width=image.shape[:2]
                box=event['region']['xyxy'];coords=[round(v*(width if i%2==0 else height)) for i,v in enumerate(box)]
                cv2.rectangle(image,tuple(coords[:2]),tuple(coords[2:]),(0,100,255) if event['feature_type']=='fire' else (220,180,0),3)
                if not cv2.imwrite(str(private/'frame.jpg'),image): raise MediaError('Не вдалося зберегти кадр події.')
                start=max(0,event['confirmed_seconds']-config.clip_before_seconds)
                end=min(metadata['duration_seconds'],event['confirmed_seconds']+config.clip_after_seconds)
                # Snap outward to real frame boundaries; arbitrary requested seconds
                # may lie between VFR frames and must not mislabel clip time zero.
                if self.timeline:
                    requested_start,requested_end=start,end
                    start=0.;end=metadata['duration_seconds']
                    with self.timeline.open(encoding='utf-8') as times:
                        for line in times:
                            when=json.loads(line)['time_seconds']
                            if when<=requested_start+1e-9: start=when
                            if when>=requested_end-1e-9:
                                end=when
                                break
                command=[str(self.settings.ffmpeg_path),'-v','error','-nostdin','-n','-threads','1','-i',str(self.source),'-ss',str(start),'-t',str(end-start),'-map','0:v:0','-an','-sn',
                         '-vf','setpts=PTS-STARTPTS,pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-threads','1','-preset','veryfast','-pix_fmt','yuv420p','-fps_mode','vfr','-movflags','+faststart',str(private/'clip.mp4')]
                with (private/'ffmpeg.log').open('wb') as log:
                    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=log)
                    started=time.monotonic()
                    try:
                        while process.poll() is None:
                            self.control()
                            if time.monotonic()-started>self.settings.analysis_io_timeout_seconds: raise MediaError('Тайм-аут фрагмента події.')
                            time.sleep(.03)
                        if process.returncode: raise MediaError('Не вдалося сформувати фрагмент події.')
                    finally:
                        if process.poll() is None: process.kill();process.wait()
                probe=subprocess.run([str(self.settings.ffprobe_path),'-v','error','-select_streams','v:0','-show_entries','stream=codec_type:format=duration','-of','json',str(private/'clip.mp4')],capture_output=True,timeout=self.settings.ffprobe_timeout_seconds,check=True)
                info=json.loads(probe.stdout)
                if not info.get('streams') or float(info['format'].get('duration',0))<=0: raise MediaError('Перевірка фрагмента події не пройшла.')
                manifest=dict(clip_start_seconds=start,clip_end_seconds=end,confirmation_seconds=event['confirmed_seconds'],clip_confirmation_seconds=event['confirmed_seconds']-start,source_duration_seconds=metadata['duration_seconds'],clip_measured_duration_seconds=float(info['format']['duration']))
                (private/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
                for name in ('frame.jpg','clip.mp4','manifest.json'):
                    with (private/name).open('rb+') as stream: os.fsync(stream.fileno())
                final.parent.mkdir(parents=True,exist_ok=True)
                private.rename(final)
            finally:
                if private.exists(): shutil.rmtree(private)
        manifest=json.loads((final/'manifest.json').read_text(encoding='utf-8'))
        values={key:value for key,value in event.items() if key in ('track_key','feature_type','automatic_status','start_seconds','confirmed_seconds','last_seen_seconds','closed_seconds','closure_reason','confidence')}
        values.update(id=identifier,analysis_run_id=self.run_id,end_seconds=event['closed_seconds'],region={**event['region'],**manifest},frame_path=relative+'/frame.jpg',clip_path=relative+'/clip.mp4')
        with Session(self.engine) as session:
            owner=session.scalar(sa.select(AnalysisRun).where(AnalysisRun.id==self.run_id).with_for_update())
            if owner.status!='running' or owner.worker_id!=self.token: raise MediaError('Втрачено право збереження події.')
            query=insert(Event).values(**values)
            updates={k:v for k,v in values.items() if k not in ('id','analysis_run_id','track_key')}
            updates['updated_at']=sa.func.clock_timestamp()
            session.execute(query.on_conflict_do_update(constraint='uq_events_run_track',set_=updates))
            session.commit()
