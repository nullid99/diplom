import json
import subprocess
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

from fastapi import HTTPException

from backend.app.config import Settings


def number(value, *, positive=False, maximum=Decimal('9999999999')) -> Decimal | None:
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or (positive and result == 0) or result > maximum:
            return None
        return result
    except (InvalidOperation, ValueError):
        return None


def frame_rate(value) -> tuple[str | None, Decimal | None]:
    try:
        rate = Fraction(str(value))
        if rate <= 0 or rate > 999999:
            return None, None
        return str(value), Decimal(rate.numerator) / Decimal(rate.denominator)
    except (ValueError, ZeroDivisionError):
        return None, None


def parse_probe(payload: dict) -> dict:
    streams = [item for item in payload.get('streams', []) if item.get('codec_type') == 'video' and not item.get('disposition', {}).get('attached_pic')]
    if not streams:
        raise HTTPException(422, 'Файл не містить відеопотоку.')
    stream = streams[0]
    container = payload.get('format', {})
    average, fps = frame_rate(stream.get('avg_frame_rate'))
    nominal, _ = frame_rate(stream.get('r_frame_rate'))
    duration = number(stream.get('duration'))
    if duration is None:
        duration = number(container.get('duration'))
    return {
        'container_format': container.get('format_name') or None,
        'video_codec': stream.get('codec_name') or None,
        'duration_seconds': duration,
        'width': int(stream['width']) if number(stream.get('width'), positive=True, maximum=Decimal(2147483647)) else None,
        'height': int(stream['height']) if number(stream.get('height'), positive=True, maximum=Decimal(2147483647)) else None,
        'fps': fps, 'avg_frame_rate': average, 'r_frame_rate': nominal,
    }


def probe_video(path: Path, settings: Settings) -> dict:
    try:
        result = subprocess.run([
            str(settings.ffprobe_path), '-v', 'error', '-protocol_whitelist', 'file',
            '-format_whitelist', 'mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,asf,mpeg,mpegts,ogg,flv',
            '-show_entries', 'format=format_name,duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration:stream_disposition=attached_pic',
            '-of', 'json', str(path),
        ], shell=False, capture_output=True, timeout=settings.ffprobe_timeout_seconds)
    except subprocess.TimeoutExpired:
        raise HTTPException(422, 'Перевірка відео перевищила дозволений час.') from None
    except OSError:
        raise HTTPException(503, 'Інструмент перевірки відео недоступний. Перевірте FFPROBE_PATH.') from None
    if result.returncode != 0 or result.stderr.strip():
        raise HTTPException(422, 'Не вдалося прочитати відео: файл пошкоджений або формат не підтримується.')
    try:
        return parse_probe(json.loads(result.stdout))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503, 'Інструмент перевірки повернув некоректні метадані.') from None


def video_media_type(container: str | None) -> str:
    formats = set((container or '').split(','))
    if 'mp4' in formats:
        return 'video/mp4'
    if 'webm' in formats:
        return 'video/webm'
    if 'ogg' in formats:
        return 'video/ogg'
    return 'application/octet-stream'
