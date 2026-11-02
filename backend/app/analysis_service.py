import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session, joinedload

from backend.app.config import Settings, storage_path
from backend.app.models import AnalysisRun, ModelVersion, VideoSource
from backend.app.temporal import TemporalConfig, Zone

QUEUE_LOCK=76314101
WORKER_LOCK=76314102
TERMINAL={'completed','failed','stopped'}


class AnalysisSettings(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True,allow_inf_nan=False)
    smoke_threshold: float=Field(.25,ge=.01,le=1)
    fire_threshold: float=Field(.25,ge=.01,le=1)
    imgsz: int=Field(640,ge=320,le=1280,strict=True)
    analysis_fps: float=Field(2,ge=.1,le=60)
    device: str=Field('cpu',pattern=r'^(cpu|cuda:0)$')
    temporal: TemporalConfig|None=None
    zones: list[Zone]=Field(default_factory=list,max_length=32)

    @model_validator(mode='after')
    def stride(self):
        if self.imgsz%32:
            raise ValueError('imgsz має бути кратним 32.')
        if self.temporal: self.temporal.validate_frequency(self.analysis_fps)
        return self


class CreateAnalysis(BaseModel):
    model_config=ConfigDict(extra='forbid')
    video_source_id: uuid.UUID
    model_version_id: uuid.UUID
    settings: AnalysisSettings=Field(default_factory=AnalysisSettings)


def checksum(path: Path) -> str:
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            result.update(chunk)
    return result.hexdigest()


def model_file(model: ModelVersion, settings: Settings, verify=True) -> Path:
    if model.class_mapping!={'0':'smoke','1':'fire'} or model.architecture!='YOLO11n':
        raise HTTPException(409,'Версія моделі не має перевіреної архітектури YOLO11n і класів smoke/fire.')
    try:
        path=storage_path(model.weights_path,settings.storage_root)
        if not path.is_file():
            raise HTTPException(409,'Файл зареєстрованої моделі недоступний.')
        if verify and checksum(path)!=model.weights_sha256:
            raise HTTPException(409,'Контрольна сума ваг не збігається із зареєстрованою.')
        return path
    except (ValueError,OSError):
        raise HTTPException(409,'Файл зареєстрованої моделі недоступний або шлях некоректний.') from None


def model_view(model,settings):
    reason=None
    try: model_file(model,settings)
    except HTTPException as error: reason=error.detail
    return dict(id=str(model.id),name=model.name,architecture=model.architecture,
                weights_path=model.weights_path,weights_sha256=model.weights_sha256,
                class_mapping=model.class_mapping,created_at=model.created_at.isoformat(),
                available=reason is None,unavailable_reason=reason)


def run_view(run):
    return dict(id=str(run.id),video_source_id=str(run.video_source_id),model_version_id=str(run.model_version_id),
                video_source_name=run.video_source.name,model_version_name=run.model_version.name,
                mode=run.mode,status=run.status,settings_snapshot=run.settings_snapshot,progress=float(run.progress),
                error_message=run.error_message,cancel_requested_at=run.cancel_requested_at,
                created_at=run.created_at,started_at=run.started_at,finished_at=run.finished_at,
                heartbeat_at=run.heartbeat_at,summary_metrics=run.summary_metrics,
                result_paths=run.result_paths if run.status=='completed' else None)


def list_runs(session,page=1,page_size=20):
    rows=session.scalars(sa.select(AnalysisRun).options(joinedload(AnalysisRun.video_source),joinedload(AnalysisRun.model_version)).order_by(AnalysisRun.created_at.desc(),AnalysisRun.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return dict(items=[run_view(run) for run in rows],total=session.scalar(sa.select(sa.func.count()).select_from(AnalysisRun)),page=page,page_size=page_size)


def reconcile_abandoned(session):
    """DB-lock доводить відсутність власника; heartbeat сам по собі не є доказом."""
    if session.scalar(sa.text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':WORKER_LOCK}):
        from backend.app.event_evidence import interrupt_events
        interrupted=session.scalars(sa.select(AnalysisRun.id).where(AnalysisRun.status=='running')).all()
        interrupt_events(session,interrupted)
        session.execute(sa.update(AnalysisRun).where(AnalysisRun.status=='running').values(
            status=sa.case((AnalysisRun.cancel_requested_at.is_not(None),'stopped'),else_='failed'),
            error_message=sa.case((AnalysisRun.cancel_requested_at.is_not(None),None),else_='Worker аварійно завершився. Створіть новий запуск для повторення.'),
            finished_at=sa.func.clock_timestamp(),result_paths=None))
    session.commit()


def find_run(session,run_id,lock=False):
    query=sa.select(AnalysisRun).where(AnalysisRun.id==run_id)
    if lock: query=query.with_for_update()
    run=session.scalar(query)
    if run is None: raise HTTPException(404,'Запуск аналізу не знайдено.')
    return run


def create_run(session:Session,payload:CreateAnalysis,settings:Settings):
    model=session.get(ModelVersion,payload.model_version_id)
    if model is None: raise HTTPException(409,'Готова зареєстрована модель відсутня. Спочатку зареєструйте перевірені фінальні ваги.')
    model_file(model,settings)
    if not settings.ffmpeg_path.is_file() or not settings.ffprobe_path.is_file():
        raise HTTPException(409,'FFmpeg або ffprobe недоступні. Перевірте конфігурацію проєкту.')
    if payload.settings.device!='cpu' and not settings.analysis_allow_gpu:
        raise HTTPException(409,'GPU для аналізу вимкнено. Не використовуйте GPU під час навчання.')
    source=session.get(VideoSource,payload.video_source_id)
    if source is None: raise HTTPException(404,'Відеоджерело не знайдено.')
    if not source.sha256: raise HTTPException(409,'Відеоджерело не має перевіреної контрольної суми.')
    try:
        if not storage_path(source.file_path,settings.storage_root).is_file():
            raise HTTPException(409,'Файл відеоджерела відсутній.')
    except (ValueError,OSError): raise HTTPException(409,'Файл відеоджерела недоступний.') from None
    session.execute(sa.text('SELECT pg_advisory_xact_lock(:key)'),{'key':QUEUE_LOCK})
    size=session.scalar(sa.select(sa.func.count()).select_from(AnalysisRun).where(AnalysisRun.status.in_(('pending','running'))))
    if size>=settings.analysis_queue_limit: raise HTTPException(429,'Черга аналізу заповнена. Дочекайтеся завершення або скасуйте запуск.')
    from backend.app.event_api import defaults
    options=payload.settings.model_dump()
    options['temporal']=(payload.settings.temporal or defaults(session).temporal).model_dump()
    options['zones']=source.observation_zones
    if 'analysis_fps' not in payload.settings.model_fields_set: options['analysis_fps']=defaults(session).analysis_fps
    try: AnalysisSettings.model_validate(options)
    except ValueError: raise HTTPException(422,'Часові налаштування несумісні з частотою аналізу.') from None
    run=AnalysisRun(video_source_id=source.id,model_version_id=model.id,mode='full',settings_snapshot={
        **options,'schema_version':2,'model_sha256':model.weights_sha256,
        'source_sha256':source.sha256,'class_mapping':model.class_mapping,
    })
    session.add(run)
    session.flush()
    result=run_view(run)
    session.commit()
    return result


def request_cancel(session,run_id):
    run=find_run(session,run_id,lock=True)
    if run.status not in TERMINAL:
        run.cancel_requested_at=run.cancel_requested_at or datetime.now(timezone.utc)
        if run.status=='pending':
            run.status='stopped'
            run.finished_at=datetime.now(timezone.utc)
    session.flush()
    result=run_view(run)
    session.commit()
    return result
