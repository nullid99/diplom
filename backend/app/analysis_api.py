import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.app.config import get_settings, storage_path
from backend.app.database import get_engine, get_session
from backend.app.models import ModelVersion
from backend.app.analysis_service import CreateAnalysis, create_run, find_run, list_runs, model_view, request_cancel, run_view, reconcile_abandoned

router=APIRouter(prefix='/api',tags=['Аналіз відео'])


@router.get('/model-versions')
def models(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),session:Session=Depends(get_session)):
    settings=get_settings()
    items=session.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc(),ModelVersion.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return dict(items=[model_view(model,settings) for model in items],total=session.scalar(select(func.count()).select_from(ModelVersion)),page=page,page_size=page_size,gpu_enabled=settings.analysis_allow_gpu,queue_limit=settings.analysis_queue_limit)


@router.post('/analysis-runs',status_code=201)
def start_analysis(payload:CreateAnalysis,session:Session=Depends(get_session)):
    return create_run(session,payload,get_settings())


@router.get('/analysis-runs')
def history(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),session:Session=Depends(get_session)):
    reconcile_abandoned(session)
    return list_runs(session,page,page_size)


# Статичний маршрут до /{run_id}.
@router.websocket('/analysis-runs/ws')
async def run_updates(websocket:WebSocket,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),selected_id:uuid.UUID|None=None):
    allowed={value.strip() for value in os.getenv('CORS_ORIGINS','http://127.0.0.1:5173,http://localhost:5173').split(',')}
    if websocket.headers.get('origin') not in allowed:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    def snapshot():
        with Session(get_engine()) as session:
            reconcile_abandoned(session)
            selected=None
            if selected_id:
                try: selected=run_view(find_run(session,selected_id))
                except HTTPException: pass
            return dict(type='snapshot',runs=list_runs(session,page,page_size),selected=selected)
    try:
        while True:
            try:
                body=await run_in_threadpool(snapshot)
            except Exception:
                await websocket.send_json({'type':'unavailable','detail':'Стан запусків тимчасово недоступний.'})
                await websocket.close(code=1013)
                break
            await websocket.send_json(jsonable_encoder(body))
            try: await asyncio.wait_for(websocket.receive_text(),timeout=1)
            except asyncio.TimeoutError: pass
    except WebSocketDisconnect:
        pass


@router.get('/analysis-runs/{run_id}')
def details(run_id:uuid.UUID,session:Session=Depends(get_session)):
    reconcile_abandoned(session)
    return run_view(find_run(session,run_id))


@router.post('/analysis-runs/{run_id}/cancel')
def cancel(run_id:uuid.UUID,session:Session=Depends(get_session)):
    return request_cancel(session,run_id)


@router.get('/analysis-runs/{run_id}/files/{kind}')
def result_file(run_id:uuid.UUID,kind:str,download:bool=False,session:Session=Depends(get_session)):
    run=find_run(session,run_id)
    if run.status!='completed': raise HTTPException(409,'Готові результати цього запуску відсутні.')
    types={'video':'video/mp4','detections':'application/x-ndjson','summary':'application/json'}
    if kind not in types or not run.result_paths or kind not in run.result_paths:
        raise HTTPException(404,'Файл результату не знайдено.')
    try:
        path=storage_path(run.result_paths[kind])
        if not path.is_file(): raise ValueError
    except (ValueError,OSError): raise HTTPException(404,'Файл результату недоступний.') from None
    return FileResponse(path,media_type=types[kind],filename=path.name,content_disposition_type='attachment' if download else 'inline')
