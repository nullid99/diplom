import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from backend.app.config import storage_path
from backend.app.database import get_session
from backend.app.models import AnalysisRun, AppSetting, Event, VideoSource
from backend.app.temporal import EventDefaults, Zone

router=APIRouter(prefix='/api',tags=['Події та зони'])


def defaults(session):
    row=session.get(AppSetting,'analysis')
    return EventDefaults.model_validate(row.value) if row else EventDefaults()


@router.get('/analysis-defaults')
def get_defaults(session:Session=Depends(get_session)):
    return defaults(session).model_dump()


@router.put('/analysis-defaults')
def save_defaults(payload:EventDefaults,session:Session=Depends(get_session)):
    query=insert(AppSetting).values(key='analysis',value=payload.model_dump())
    session.execute(query.on_conflict_do_update(index_elements=['key'],set_={'value':payload.model_dump(),'updated_at':sa.func.clock_timestamp()}))
    session.commit()
    return payload


class ZoneSettings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    zones: list[Zone]=Field(default_factory=list,max_length=32)

    @model_validator(mode='after')
    def unique(self):
        if len({zone.id for zone in self.zones})!=len(self.zones): raise ValueError('Ідентифікатори зон повинні бути унікальними.')
        return self


@router.get('/video-sources/{source_id}/zones')
def get_zones(source_id:uuid.UUID,session:Session=Depends(get_session)):
    source=session.get(VideoSource,source_id)
    if source is None: raise HTTPException(404,'Відеоджерело не знайдено.')
    return dict(zones=source.observation_zones,width=source.width,height=source.height)


@router.put('/video-sources/{source_id}/zones')
def save_zones(source_id:uuid.UUID,payload:ZoneSettings,session:Session=Depends(get_session)):
    source=session.scalar(sa.select(VideoSource).where(VideoSource.id==source_id).with_for_update())
    if source is None: raise HTTPException(404,'Відеоджерело не знайдено.')
    source.observation_zones=[zone.model_dump() for zone in payload.zones]
    session.commit()
    return dict(zones=source.observation_zones,width=source.width,height=source.height)


def event_view(event,run,source,detail=False):
    data=dict(id=str(event.id),analysis_run_id=str(run.id),video_source_id=str(source.id),
              source_name=source.name,model_version_id=str(run.model_version_id),feature_type=event.feature_type,
              automatic_status=event.automatic_status,start_seconds=event.start_seconds,confirmed_seconds=event.confirmed_seconds,
              last_seen_seconds=event.last_seen_seconds,end_seconds=event.end_seconds,closed_seconds=event.closed_seconds,
              closure_reason=event.closure_reason,confidence=event.confidence,review_status=event.review_status,
              operator_comment=event.operator_comment,created_at=event.created_at,updated_at=event.updated_at,
              has_frame=bool(event.frame_path),has_clip=bool(event.clip_path))
    if detail: data.update(region=event.region,settings_snapshot=run.settings_snapshot,run_status=run.status)
    return data


def find_event(session,event_id):
    row=session.execute(sa.select(Event,AnalysisRun,VideoSource).join(AnalysisRun,Event.analysis_run_id==AnalysisRun.id)
                        .join(VideoSource,AnalysisRun.video_source_id==VideoSource.id).where(Event.id==event_id)).first()
    if row is None: raise HTTPException(404,'Подію не знайдено.')
    return row


@router.get('/events')
def events(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),source_id:uuid.UUID|None=None,
           feature_type:str|None=Query(None,pattern='^(smoke|fire)$'),
           review_status:str|None=Query(None,pattern='^(unreviewed|confirmed|false_positive|needs_review)$'),
           since:datetime|None=None,until:datetime|None=None,session:Session=Depends(get_session)):
    for value in (since,until):
        if value is not None and value.utcoffset() is None: raise HTTPException(422,'Період повинен містити часовий пояс.')
    if since and until and since>until: raise HTTPException(422,'Початок періоду пізніше завершення.')
    query=sa.select(Event,AnalysisRun,VideoSource).join(AnalysisRun,Event.analysis_run_id==AnalysisRun.id).join(VideoSource,AnalysisRun.video_source_id==VideoSource.id)
    for condition in ([AnalysisRun.video_source_id==source_id] if source_id else [])+([Event.feature_type==feature_type] if feature_type else [])+([Event.review_status==review_status] if review_status else [])+([Event.created_at>=since] if since else [])+([Event.created_at<=until] if until else []): query=query.where(condition)
    total=session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
    rows=session.execute(query.order_by(Event.created_at.desc(),Event.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return dict(items=[event_view(*row) for row in rows],total=total,page=page,page_size=page_size)


@router.get('/events/{event_id}')
def event_detail(event_id:uuid.UUID,session:Session=Depends(get_session)):
    return event_view(*find_event(session,event_id),detail=True)


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    review_status:str=Field(pattern='^(unreviewed|confirmed|false_positive|needs_review)$')
    operator_comment:str=Field('',max_length=4000)
    expected_updated_at:datetime


@router.patch('/events/{event_id}/review')
def review(event_id:uuid.UUID,payload:Review,session:Session=Depends(get_session)):
    if payload.expected_updated_at.utcoffset() is None: raise HTTPException(422,'Потрібен часовий пояс версії картки.')
    updated=session.execute(sa.update(Event).where(Event.id==event_id,Event.updated_at==payload.expected_updated_at)
                            .values(review_status=payload.review_status,operator_comment=payload.operator_comment.strip() or None,
                                    updated_at=sa.func.clock_timestamp()))
    if updated.rowcount!=1:
        find_event(session,event_id)
        raise HTTPException(409,'Картка вже змінилася. Оновіть її перед збереженням.')
    session.commit()
    return event_view(*find_event(session,event_id),detail=True)


@router.get('/events/{event_id}/files/{kind}')
def event_file(event_id:uuid.UUID,kind:str,session:Session=Depends(get_session)):
    event,_,_=find_event(session,event_id)
    relative=event.frame_path if kind=='frame' else event.clip_path if kind=='clip' else None
    if not relative: raise HTTPException(404,'Матеріал події недоступний.')
    try:
        path=storage_path(relative)
        if not path.is_file(): raise ValueError()
    except (ValueError,OSError): raise HTTPException(404,'Матеріал події недоступний.') from None
    return FileResponse(path,media_type='image/jpeg' if kind=='frame' else 'video/mp4')
