import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatabaseConfigurationError(ValueError):
    """Відсутня або некоректна конфігурація БД; секрети не включаються."""


@dataclass(frozen=True)
class Settings:
    db_host: str = ''
    db_port: str = '5432'
    db_name: str = 'firevision_db'
    db_user: str = ''
    db_password: str = field(default='', repr=False)
    storage_root: Path = PROJECT_ROOT / 'storage'
    ffmpeg_path: Path = PROJECT_ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'
    ffprobe_path: Path = PROJECT_ROOT / 'tools/ffmpeg/bin/ffprobe.exe'
    upload_max_bytes: int = 1024 * 1024 * 1024
    ffprobe_timeout_seconds: int = 30
    analysis_queue_limit: int = 10
    analysis_allow_gpu: bool = False
    analysis_io_timeout_seconds: int = 60
    analysis_max_pixels: int = 3840 * 2160

    def database_url(self) -> URL:
        fields = {
            'DB_HOST': self.db_host, 'DB_PORT': self.db_port,
            'DB_NAME': self.db_name, 'DB_USER': self.db_user,
            'DB_PASSWORD': self.db_password,
        }
        missing = [key for key, value in fields.items() if not value or value.startswith('<')]
        if missing:
            raise DatabaseConfigurationError('Заповніть локально: ' + ', '.join(missing))
        try:
            port = int(self.db_port)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise DatabaseConfigurationError('DB_PORT має бути від 1 до 65535.') from None
        if self.db_name != 'firevision_db':
            raise DatabaseConfigurationError('DB_NAME має бути firevision_db.')
        return URL.create(
            'postgresql+psycopg', username=self.db_user, password=self.db_password,
            host=self.db_host, port=port, database=self.db_name,
        )


def get_settings() -> Settings:
    # Інтерполяцію вимкнено: ${...} у паролі має залишатися буквальним текстом.
    values = {**dotenv_values(PROJECT_ROOT / '.env', interpolate=False), **os.environ}
    storage = Path(values.get('STORAGE_ROOT') or './storage').expanduser()
    if not storage.is_absolute():
        storage = PROJECT_ROOT / storage
    def tool_path(name: str, default: str) -> Path:
        path = Path(values.get(name) or default)
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    def positive_integer(name: str, default: int) -> int:
        try:
            result = int(values.get(name) or default)
            if result <= 0:
                raise ValueError
            return result
        except ValueError:
            raise ValueError(f'{name} має бути додатним цілим числом.') from None
    return Settings(
        db_host=values.get('DB_HOST') or '', db_port=values.get('DB_PORT') or '',
        db_name=values.get('DB_NAME') or '', db_user=values.get('DB_USER') or '',
        db_password=values.get('DB_PASSWORD') or '', storage_root=storage.resolve(),
        ffmpeg_path=tool_path('FFMPEG_PATH', 'tools/ffmpeg/bin/ffmpeg.exe'),
        ffprobe_path=tool_path('FFPROBE_PATH', 'tools/ffmpeg/bin/ffprobe.exe'),
        upload_max_bytes=positive_integer('UPLOAD_MAX_BYTES', 1024 * 1024 * 1024),
        ffprobe_timeout_seconds=positive_integer('FFPROBE_TIMEOUT_SECONDS', 30),
        analysis_queue_limit=positive_integer('ANALYSIS_QUEUE_LIMIT', 10),
        analysis_allow_gpu=str(values.get('ANALYSIS_ALLOW_GPU', 'false')).lower() == 'true',
        analysis_io_timeout_seconds=positive_integer('ANALYSIS_IO_TIMEOUT_SECONDS', 60),
        analysis_max_pixels=positive_integer('ANALYSIS_MAX_PIXELS', 3840 * 2160),
    )


def storage_path(relative_path: str, root: Path | None = None) -> Path:
    """Перевіряє переносний шлях і не дозволяє вихід за корінь сховища."""
    if (
        not relative_path or ':' in relative_path or '\\' in relative_path
        or any(part in ('', '.', '..') for part in relative_path.split('/'))
    ):
        raise ValueError('Потрібен відносний шлях зі звичайними компонентами через /.')
    base = (root or get_settings().storage_root).resolve()
    candidate = (base / relative_path).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError('Шлях виходить за межі сховища.')
    return candidate
