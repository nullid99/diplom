"""Один виконавець, PostgreSQL-черга, fenced ownership і окремий процес."""
import argparse
import contextlib
import logging
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.analysis_media import MediaError
from backend.app.analysis_processing import process_video
from backend.app.analysis_service import AnalysisSettings, WORKER_LOCK, checksum, model_file
from backend.app.config import PROJECT_ROOT, get_settings, storage_path
from backend.app.database import get_engine
from backend.app.models import AnalysisRun, ModelVersion, VideoSource
from backend.app.event_evidence import EvidenceWriter, interrupt_events

log=logging.getLogger('firevision.analysis')


class Cancelled(Exception): pass
class OwnershipLost(Exception): pass


def cleanup(path,root):
    base=root.resolve()
    target=path.resolve()
    if not target.is_relative_to(base) or target==base:
        raise ValueError('Unsafe cleanup target')
    if target.exists(): shutil.rmtree(target)


@contextlib.contextmanager
def gpu_reservation(settings):
    if not settings.analysis_allow_gpu: raise MediaError('GPU для аналізу вимкнено.')
    import msvcrt
    path=PROJECT_ROOT/'.cache/full-training-gpu0.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size==0: stream.write(b'0'); stream.flush()
        stream.seek(0)
        try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise MediaError('GPU зарезервовано іншим процесом, зокрема навчанням.') from None
        try: yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


class WorkerLease:
    def __init__(self,engine): self.engine=engine; self.connection=None

    def __enter__(self):
        self.connection=self.engine.connect().execution_options(isolation_level='AUTOCOMMIT')
        try:
            acquired=False
            for attempt in range(5):
                if self.connection.scalar(sa.text('SELECT pg_try_advisory_lock(:key)'),{'key':WORKER_LOCK}):
                    acquired=True
                    break
                time.sleep(.05)
            if not acquired:
                raise RuntimeError('Інший worker уже працює в цій БД.')
            self.backend_pid=self.connection.scalar(sa.text('SELECT pg_backend_pid()'))
            return self
        except BaseException:
            self.connection.close()
            self.connection=None
            raise

    def check(self):
        if self.connection.scalar(sa.text('SELECT pg_backend_pid()'))!=self.backend_pid:
            raise OwnershipLost('Втрачено сесію блокування worker.')

    def __exit__(self,*args):
        try:
            self.connection.execute(sa.text('SELECT pg_advisory_unlock(:key)'),{'key':WORKER_LOCK})
        except Exception: pass
        finally: self.connection.close()

    def recover(self,settings):
        # Сюди можна потрапити лише після отримання глобального session lock.
        self.check()
        with Session(self.engine) as session:
            rows=session.scalars(sa.select(AnalysisRun).where(AnalysisRun.status=='running').with_for_update()).all()
            old=[]
            for run in rows:
                old.append((run.id,run.worker_id))
                run.status='stopped' if run.cancel_requested_at else 'failed'
                run.error_message=None if run.cancel_requested_at else 'Попередній worker аварійно завершився. Створіть новий запуск для повторення.'
                run.finished_at=datetime.now(timezone.utc)
                run.result_paths=None
            interrupt_events(session,[run.id for run in rows])
            session.commit()
        for run_id,token in old:
            if token:
                for relative in (f'tmp/analysis/{run_id}-{token}',f'results/analysis/{run_id}/{token}'):
                    cleanup(storage_path(relative,settings.storage_root),settings.storage_root)
        # API міг уже позначити аварію; прибрати лише відомі каталоги terminal-job.
        with Session(self.engine) as session:
            terminal=session.execute(sa.select(AnalysisRun.id,AnalysisRun.worker_id).where(AnalysisRun.status.in_(('failed','stopped')),AnalysisRun.worker_id.is_not(None))).all()
            interrupt_events(session,[run_id for run_id,_ in terminal])
            session.commit()
        for run_id,token in terminal:
            for relative in (f'tmp/analysis/{run_id}-{token}',f'results/analysis/{run_id}/{token}'):
                cleanup(storage_path(relative,settings.storage_root),settings.storage_root)
        return len(old)


def claim(engine):
    with Session(engine) as session:
        run=session.scalar(sa.select(AnalysisRun).where(AnalysisRun.status=='pending',AnalysisRun.cancel_requested_at.is_(None)).order_by(AnalysisRun.created_at,AnalysisRun.id).with_for_update(skip_locked=True).limit(1))
        if run is None: return None
        run.status='running'
        run.worker_id=uuid.uuid4()
        run.started_at=max(run.created_at,session.scalar(sa.select(sa.func.clock_timestamp())))
        run.heartbeat_at=run.started_at
        run.progress=0
        run.summary_metrics={'stage':'checking'}
        identity=(run.id,run.worker_id)
        session.commit()
        return identity


class Heartbeat:
    def __init__(self,lease,run_id,token):
        self.lease=lease; self.run_id=run_id; self.token=token
        self.stop_event=threading.Event(); self.cancelled=threading.Event(); self.lost=threading.Event()
        self.thread=threading.Thread(target=self.loop,daemon=True)

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.lease.check()
                with Session(self.lease.engine) as session:
                    run=session.scalar(sa.select(AnalysisRun).where(AnalysisRun.id==self.run_id,AnalysisRun.worker_id==self.token,AnalysisRun.status=='running'))
                    if run is None: raise OwnershipLost()
                    if run.cancel_requested_at: self.cancelled.set()
                    run.heartbeat_at=datetime.now(timezone.utc)
                    session.commit()
            except Exception:
                self.lost.set()
                return
            self.stop_event.wait(1)

    def control(self):
        if self.lost.is_set(): raise OwnershipLost('Втрачено зв’язок із БД або право виконання.')
        if self.cancelled.is_set(): raise Cancelled()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=10)


def fail_job(engine,run_id,token,status,message):
    try:
        with Session(engine) as session:
            run=session.scalar(sa.select(AnalysisRun).where(AnalysisRun.id==run_id).with_for_update())
            if run and run.worker_id==token and run.status=='running':
                run.status='stopped' if run.cancel_requested_at else status
                run.finished_at=datetime.now(timezone.utc)
                run.error_message=None if run.status=='stopped' else message
                run.result_paths=None
                interrupt_events(session,[run_id],'cancelled' if run.status=='stopped' else 'failed')
                session.commit()
                return True
            return bool(run and run.worker_id==token and run.status in ('failed','stopped'))
    except Exception:
        # Невідомий результат COMMIT: не видаляти потенційно опубліковані файли.
        return False


def run_job(lease,identity,settings,detector_factory=None):
    engine=lease.engine
    run_id,token=identity
    private=storage_path(f'tmp/analysis/{run_id}-{token}',settings.storage_root)
    final=storage_path(f'results/analysis/{run_id}/{token}',settings.storage_root)
    heartbeat=Heartbeat(lease,run_id,token)
    heartbeat.thread.start()
    last_update=[0.]
    def progress(value,metrics):
        heartbeat.control()
        if time.monotonic()-last_update[0]<1 and metrics.get('stage')!='verifying': return
        with Session(engine) as session:
            updated=session.execute(sa.update(AnalysisRun).where(AnalysisRun.id==run_id,AnalysisRun.worker_id==token,AnalysisRun.status=='running').values(progress=value,summary_metrics=metrics))
            if updated.rowcount!=1: raise OwnershipLost()
            session.commit()
        last_update[0]=time.monotonic()
    try:
        private.mkdir(parents=True,exist_ok=False)
        with Session(engine) as session:
            run=session.get(AnalysisRun,run_id)
            options=AnalysisSettings.model_validate({k:v for k,v in run.settings_snapshot.items() if k in AnalysisSettings.model_fields})
            model=session.get(ModelVersion,run.model_version_id)
            weights=model_file(model,settings)
            if model.weights_sha256!=run.settings_snapshot.get('model_sha256'):
                raise MediaError('Версія ваг більше не відповідає знімку запуску.')
            video=session.get(VideoSource,run.video_source_id)
            source=storage_path(video.file_path,settings.storage_root)
            expected=run.settings_snapshot.get('source_sha256')
            if not expected or not source.is_file() or checksum(source)!=expected:
                raise MediaError('Файл відео відсутній або його SHA-256 змінився.')
        if detector_factory is None:
            from backend.app.analysis_detector import YoloDetector
            detector_factory=YoloDetector
        reservation=gpu_reservation(settings) if options.device=='cuda:0' else contextlib.nullcontext()
        with reservation:
            summary=process_video(source,weights,options,private,settings,heartbeat.control,progress,detector_factory,
                                  EvidenceWriter(engine,run_id,token,source,settings,heartbeat.control,private/'timeline.jsonl'))
        heartbeat.control()
        with Session(engine) as session:
            run=session.scalar(sa.select(AnalysisRun).where(AnalysisRun.id==run_id).with_for_update())
            if run.worker_id!=token or run.status!='running': raise OwnershipLost()
            if run.cancel_requested_at: raise Cancelled()
            final.parent.mkdir(parents=True,exist_ok=True)
            private.rename(final)
            prefix=final.relative_to(settings.storage_root).as_posix()
            run.result_paths={key:f'{prefix}/{name}' for key,name in {'video':'annotated.mp4','detections':'detections.jsonl','summary':'summary.json'}.items()}
            run.summary_metrics={**summary,'stage':'completed'}
            run.status='completed'
            run.progress=1
            run.finished_at=datetime.now(timezone.utc)
            session.commit()
        log.info('completed run=%s',run_id)
        return 0
    except BaseException as error:
        cancelled=isinstance(error,Cancelled)
        message=error.detail if isinstance(error,HTTPException) else str(error) if isinstance(error,MediaError) else 'Обробку перервано або сталася помилка worker. Перевірте його локальний журнал.'
        if cancelled: message='Аналіз скасовано на запит користувача.'
        if type(error).__name__=='OutOfMemoryError' or 'cuda out of memory' in str(error).lower():
            message='Недостатньо пам’яті пристрою. Запуск зупинено; параметри й пристрій не змінювалися автоматично.'
        safe=fail_job(engine,run_id,token,'stopped' if cancelled else 'failed',message)
        if safe:
            diagnostic=storage_path(f'logs/analysis/{run_id}-{token}',settings.storage_root)
            diagnostic.mkdir(parents=True,exist_ok=True)
            for path in private.glob('*.log'):
                # FFmpeg-only diagnostics, bounded; no SQL, credentials or .env.
                with path.open('rb') as source_log,(diagnostic/path.name).open('wb') as saved_log:
                    saved_log.write(source_log.read(1024*1024))
            cleanup(private,settings.storage_root)
            cleanup(final,settings.storage_root)
        # Жодних сирих SQL/URL чи параметрів у логах.
        (log.info if cancelled else log.error)('run=%s status=%s exception=%s message=%s',run_id,'stopped' if cancelled else 'failed',type(error).__name__,message)
        if isinstance(error,(KeyboardInterrupt,SystemExit,OwnershipLost)) or not safe: raise OwnershipLost() from None
        return 20 if cancelled else 1
    finally:
        heartbeat.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    settings=get_settings()
    log_dir=settings.storage_root/'logs'
    log_dir.mkdir(parents=True,exist_ok=True)
    log_file=log_dir/f'analysis-worker-{os.getpid()}-{int(time.time())}.log'
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[logging.StreamHandler(),logging.FileHandler(log_file,encoding='utf-8')])
    engine=get_engine()
    try:
        with WorkerLease(engine) as lease:
            log.info('worker started pid=%s recovered=%s',os.getpid(),lease.recover(settings))
            while True:
                lease.check()
                identity=claim(engine)
                if identity:
                    code=run_job(lease,identity,settings)
                    # Активне скасування завершує цей процес; PS supervisor перезапускає його.
                    if code==20 or args.once: return code
                elif args.once: return 0
                else: time.sleep(1)
    except KeyboardInterrupt: return 130
    except Exception as error:
        log.error('worker stopped exception=%s (database/lease/configuration unavailable)',type(error).__name__)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
