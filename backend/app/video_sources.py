import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.app.config import get_settings, storage_path
from backend.app.database import get_session
from backend.app.models import VideoSource
from backend.app.video_probe import probe_video, video_media_type
from backend.app.video_upload import VideoUpload

router = APIRouter(prefix='/api/video-sources', tags=['Відеоджерела'])
DatabaseSession = Annotated[Session, Depends(get_session)]


class VideoSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    original_filename: str
    file_size_bytes: int | None
    sha256: str | None
    duration_seconds: Decimal | None
    width: int | None
    height: int | None
    fps: Decimal | None
    container_format: str | None
    video_codec: str | None
    avg_frame_rate: str | None
    r_frame_rate: str | None
    created_at: datetime


class VideoSourcePage(BaseModel):
    items: list[VideoSourceResponse]
    total: int
    page: int
    page_size: int
    upload_limit_bytes: int


def find_source(source_id: uuid.UUID, session: Session) -> VideoSource:
    source = session.get(VideoSource, source_id)
    if source is None:
        raise HTTPException(404, 'Відеоджерело не знайдено.')
    return source


def save_upload(upload: VideoUpload, session: Session) -> VideoSourceResponse:
    metadata = probe_video(upload.path, upload.settings)
    source_id = uuid.uuid4()
    formats = (metadata['container_format'] or '').split(',')
    extension = next((extension for kind, extension in (
        ('mp4', '.mp4'), ('matroska', '.mkv'), ('webm', '.webm'), ('avi', '.avi'), ('ogg', '.ogg'), ('mpegts', '.ts'),
    ) if kind in formats), '.video')
    relative = f'videos/originals/{source_id.hex}{extension}'
    destination = storage_path(relative, upload.settings.storage_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = VideoSource(
        id=source_id, name=upload.name, original_filename=upload.original_filename,
        file_path=relative, file_size_bytes=upload.size, sha256=upload.digest.hexdigest(), **metadata,
    )
    moved = False
    try:
        # Rename в одному сховищі: завершений оригінал з’являється до COMMIT БД.
        upload.path.rename(destination)
        moved = True
        session.add(source)
        session.flush()
        result = VideoSourceResponse.model_validate(source)
        session.commit()
        return result
    except BaseException:
        session.rollback()
        if moved:
            destination.unlink(missing_ok=True)
        raise


@router.post('', response_model=VideoSourceResponse, status_code=201, openapi_extra={
    'requestBody': {'required': True, 'content': {'multipart/form-data': {'schema': {
        'type': 'object', 'required': ['name', 'file'], 'properties': {
            'name': {'type': 'string', 'maxLength': 255}, 'file': {'type': 'string', 'format': 'binary'},
        },
    }}}},
})
async def upload_source(request: Request, session: DatabaseSession):
    upload = None
    try:
        upload = VideoUpload(get_settings())
        await upload.receive(request)
        return await run_in_threadpool(save_upload, upload, session)
    except OSError:
        raise HTTPException(503, 'Не вдалося зберегти файл у сховищі.') from None
    finally:
        if upload:
            upload.cleanup()


@router.get('', response_model=VideoSourcePage)
def list_sources(session: DatabaseSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    sources = session.scalars(select(VideoSource).order_by(VideoSource.created_at.desc(), VideoSource.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return VideoSourcePage(
        items=[VideoSourceResponse.model_validate(source) for source in sources],
        total=session.scalar(select(func.count()).select_from(VideoSource)), page=page, page_size=page_size,
        upload_limit_bytes=get_settings().upload_max_bytes,
    )


@router.get('/{source_id}', response_model=VideoSourceResponse)
def source_details(source_id: uuid.UUID, session: DatabaseSession):
    return find_source(source_id, session)


@router.get('/{source_id}/content')
def source_content(source_id: uuid.UUID, session: DatabaseSession):
    source = find_source(source_id, session)
    try:
        path = storage_path(source.file_path)
    except ValueError:
        raise HTTPException(503, 'Шлях відео у сховищі некоректний.') from None
    if not path.is_file():
        raise HTTPException(404, 'Файл відеоджерела відсутній у сховищі.')
    return FileResponse(
        path, media_type=video_media_type(source.container_format),
        filename=source.original_filename, content_disposition_type='inline',
    )
