import hashlib
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic import command
from fastapi import HTTPException
from psycopg import sql
from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.database import build_engine
from backend.app.video_probe import parse_probe, probe_video
from scripts.db import connect, migration_config


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class ProbeTests(unittest.TestCase):
    def test_unknown_and_variable_rates(self):
        result = parse_probe({'streams': [{
            'codec_type': 'video', 'codec_name': 'h264', 'width': 320, 'height': 240,
            'avg_frame_rate': '24000/1001', 'r_frame_rate': '30/1',
        }], 'format': {'format_name': 'mov,mp4'}})
        self.assertIsNone(result['duration_seconds'])
        self.assertEqual(result['avg_frame_rate'], '24000/1001')
        self.assertEqual(result['r_frame_rate'], '30/1')
        self.assertAlmostEqual(result['fps'], Decimal(24000) / 1001)
        unknown = parse_probe({'streams': [{'codec_type': 'video', 'avg_frame_rate': '0/0'}]})
        self.assertIsNone(unknown['fps'])
        self.assertIsNone(unknown['width'])

    def test_no_video_timeout_and_tool_failure(self):
        with self.assertRaises(HTTPException) as raised:
            parse_probe({'streams': [{'codec_type': 'audio'}]})
        self.assertEqual(raised.exception.status_code, 422)
        for failure, status in ((OSError(), 503), (subprocess.TimeoutExpired('ffprobe', 1), 422)):
            with patch('backend.app.video_probe.subprocess.run', side_effect=failure):
                with self.assertRaises(HTTPException) as raised:
                    probe_video(Path('unused'), get_settings())
                self.assertEqual(raised.exception.status_code, status)


class VideoPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = 'firevision_video_test_' + uuid.uuid4().hex
        cls.created = False
        cls.server = None
        cls.engine = None
        cls.sandbox = Path(tempfile.mkdtemp(prefix='video-test-', dir=PROJECT_ROOT / '.tmp'))
        cls.storage = cls.sandbox / 'storage'
        cls.port = free_port()
        cls.ui_port = free_port()
        cls.addClassCleanup(cls.cleanup)
        try:
            with connect('postgres') as connection:
                connection.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(cls.name)))
                cls.created = True
            cls.engine = build_engine(get_settings().database_url().set(database=cls.name))
            with cls.engine.begin() as connection:
                command.upgrade(migration_config(connection), 'head')
                connection.execute(sa.text("ALTER TABLE video_sources ADD CONSTRAINT test_save_failure CHECK (name <> '__force_db_failure__')"))
            cls.sample = cls.sandbox / 'technical-test-not-training.mp4'
            subprocess.run([
                str(get_settings().ffmpeg_path), '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=30', '-t', '4',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(cls.sample),
            ], check=True, timeout=30, capture_output=True)
            cls.audio = cls.sandbox / 'audio-only.m4a'
            subprocess.run([
                str(get_settings().ffmpeg_path), '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'anullsrc', '-t', '1', '-c:a', 'aac', str(cls.audio),
            ], check=True, timeout=30, capture_output=True)
            cls.start_server()
        except Exception:
            raise RuntimeError('Не вдалося підготувати ізольовану перевірку відео. Перевірте БД, CREATEDB та FFmpeg; секрети приховано.') from None

    @classmethod
    def start_server(cls, extra_environment=None):
        cls.server = subprocess.Popen([
            sys.executable, '-m', 'uvicorn', 'tests.video_test_app:app',
            '--host', '127.0.0.1', '--port', str(cls.port),
        ], cwd=PROJECT_ROOT, env={
            **os.environ, 'FIREVISION_VIDEO_TEST_DATABASE': cls.name,
            'STORAGE_ROOT': str(cls.storage), 'UPLOAD_MAX_BYTES': '2097152',
            'CORS_ORIGINS': f'http://127.0.0.1:{cls.ui_port}',
            **(extra_environment or {}),
        }, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError('Тестовий API не запустився.')
            try:
                if cls.request('GET', '/api/health')[0] == 200:
                    return
            except OSError:
                time.sleep(.1)
        raise RuntimeError('Час очікування тестового API вичерпано.')

    @classmethod
    def cleanup(cls):
        if cls.server and cls.server.poll() is None:
            cls.server.terminate()
            cls.server.wait(timeout=10)
        if cls.engine:
            cls.engine.dispose()
        if cls.created:
            with connect('postgres') as connection:
                connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
        # Матеріали перевірки зберігаються тільки в .tmp, чинне сховище не змінюється.

    @classmethod
    def request(cls, method, path, body=None, headers=None, chunked=False):
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=40)
        try:
            connection.request(method, path, body=body, headers=headers or {}, encode_chunked=chunked)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def upload(self, data, name='Технічний тест — не навчальні дані', filename='тест.mp4', chunked=False):
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        payload = (body[index:index+4096] for index in range(0, len(body), 4096)) if chunked else body
        return self.request('POST', '/api/video-sources', payload, {'Content-Type': f'multipart/form-data; boundary={boundary}'}, chunked)

    def current_files(self):
        return {path.relative_to(self.storage) for path in self.storage.rglob('*') if path.is_file()}

    def test_upload_persistence_restart_and_ranges(self):
        data = self.sample.read_bytes()
        status, _, body = self.upload(data, filename='справжнє-відео.txt', chunked=True)
        self.assertEqual(status, 201, body)
        source = json.loads(body)
        self.assertEqual(source['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(source['file_size_bytes'], len(data))
        self.assertEqual((source['width'], source['height']), (320, 240))
        self.assertEqual(source['video_codec'], 'h264')
        with self.engine.connect() as connection:
            path = connection.scalar(sa.text('SELECT file_path FROM video_sources WHERE id = :id'), {'id': source['id']})
        self.assertFalse(Path(path).is_absolute())
        self.assertEqual((self.storage / path).read_bytes(), data)
        self.assertEqual(self.request('GET', '/api/video-sources/' + source['id'])[0], 200)
        status, headers, partial = self.request('GET', '/api/video-sources/' + source['id'] + '/content', headers={'Range': 'bytes=0-127'})
        self.assertEqual(status, 206)
        self.assertEqual(partial, data[:128])
        self.assertEqual(headers['content-range'], f'bytes 0-127/{len(data)}')
        self.assertEqual(self.request('GET', '/api/video-sources/' + source['id'] + '/content', headers={'Range': f'bytes={len(data)+100}-'})[0], 416)
        self.server.terminate()
        self.server.wait(timeout=10)
        type(self).start_server()
        listing = json.loads(self.request('GET', '/api/video-sources?page=1&page_size=100')[2])
        self.assertIn(source['id'], [item['id'] for item in listing['items']])

    def test_invalid_files_limit_and_failed_commit_cleanup(self):
        before = self.current_files()
        before_count = json.loads(self.request('GET', '/api/video-sources')[2])['total']
        for payload, expected in ((b'', 422), (b'not-a-video', 422), (self.audio.read_bytes(), 422), (b'x' * 2097153, 413)):
            with self.subTest(expected=expected, size=len(payload)):
                self.assertEqual(self.upload(payload, chunked=True)[0], expected)
                self.assertEqual(self.current_files(), before)
        self.assertEqual(self.upload(self.sample.read_bytes(), name='__force_db_failure__')[0], 503)
        self.assertEqual(self.current_files(), before)
        self.assertEqual(json.loads(self.request('GET', '/api/video-sources')[2])['total'], before_count)
        missing = str(uuid.uuid4())
        self.assertEqual(self.request('GET', '/api/video-sources/' + missing)[0], 404)
        self.assertEqual(self.request('GET', '/api/video-sources/' + missing + '/content')[0], 404)
        self.assertEqual(self.request('GET', '/api/video-sources?page=0')[0], 422)

    def test_browser_upload_seek_and_reload(self):
        result = subprocess.run([
            'node', 'scripts/video-browser.mjs', f'http://127.0.0.1:{self.port}', str(self.ui_port), str(self.sample),
        ], cwd=PROJECT_ROOT, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        print(result.stdout.decode('utf-8'))

    def test_unavailable_tool_cleanup(self):
        before = self.current_files()
        self.server.terminate()
        self.server.wait(timeout=10)
        try:
            type(self).start_server({'FFPROBE_PATH': str(self.sandbox / 'missing-ffprobe.exe')})
            self.assertEqual(self.upload(self.sample.read_bytes())[0], 503)
            self.assertEqual(self.current_files(), before)
        finally:
            self.server.terminate()
            self.server.wait(timeout=10)
            type(self).start_server()

    def test_real_variable_frame_rate(self):
        variable = self.sandbox / 'technical-variable-rate.mp4'
        subprocess.run([
            str(get_settings().ffmpeg_path), '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=30', '-t', '4',
            '-vf', "select='if(lt(t,2),not(mod(n,2)),1)'", '-fps_mode', 'vfr',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(variable),
        ], check=True, timeout=30, capture_output=True)
        status, _, body = self.upload(variable.read_bytes(), name='Технічна перевірка змінної частоти')
        self.assertEqual(status, 201, body)
        source = json.loads(body)
        self.assertIsNotNone(source['avg_frame_rate'])
        self.assertIsNotNone(source['r_frame_rate'])
        self.assertNotEqual(source['avg_frame_rate'], source['r_frame_rate'])
        self.assertTrue(Decimal(source['fps']) < 30)


if __name__ == '__main__':
    unittest.main()
