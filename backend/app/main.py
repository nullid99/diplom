import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import DatabaseConfigurationError
from backend.app.database import get_engine
from backend.app.event_api import router as event_router
from backend.app.video_sources import router as video_sources_router
from backend.app.analysis_api import router as analysis_router

load_dotenv(Path(__file__).resolve().parents[2] / '.env', interpolate=False)

app = FastAPI(title='FireVision API', version='0.1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            'CORS_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173'
        ).split(',')
        if origin.strip()
    ],
    allow_methods=['GET', 'POST', 'PUT', 'PATCH'],
    allow_headers=['Accept', 'Content-Type', 'Range'],
    expose_headers=['Content-Range', 'Accept-Ranges'],
)
app.include_router(video_sources_router)
app.include_router(analysis_router)
app.include_router(event_router)


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(DatabaseConfigurationError)
async def database_error_handler(request, error):
    return JSONResponse(status_code=503, content={'detail': 'База даних недоступна або операцію збереження не виконано.'})


class HealthResponse(BaseModel):
    status: Literal['ok']
    service: Literal['api']


@app.get('/api/health', response_model=HealthResponse)
async def health() -> HealthResponse:
    """Перевірка працездатності API."""
    return HealthResponse(status='ok', service='api')


@app.get('/api/health/db', responses={503: {'description': 'База даних недоступна'}})
def database_health():
    try:
        with get_engine().connect() as connection:
            connection.execute(text('SELECT 1')).scalar_one()
        return {'status': 'ok', 'service': 'database'}
    except (DatabaseConfigurationError, SQLAlchemyError):
        return JSONResponse(
            status_code=503,
            content={'status': 'unavailable', 'service': 'database'},
        )
