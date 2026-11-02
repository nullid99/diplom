import io
import json
import os
import subprocess
import sys
import time
import unittest
import uuid
from contextlib import redirect_stdout
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, DatabaseConfigurationError, Settings, get_settings, storage_path
from backend.app.database import build_engine
from backend.app.models import AnalysisRun, Base, Event, ModelVersion, VideoSource


class ConfigurationTests(unittest.TestCase):
    def test_special_password_url(self):
        secret = 'synthetic@:/?#%${LITERAL} пароль'
        settings = Settings(db_host='127.0.0.1', db_user='existing', db_password=secret)
        url = settings.database_url()
        from sqlalchemy.engine import make_url
        self.assertEqual(make_url(url.render_as_string(hide_password=False)).password, secret)
        self.assertNotIn(secret, repr(settings))
        engine = build_engine(url)
        try:
            _, params = engine.dialect.create_connect_args(url)
            self.assertEqual(params['password'], secret)
        finally:
            engine.dispose()

    def test_dotenv_no_interpolation(self):
        with patch('backend.app.config.dotenv_values', return_value={
            'DB_HOST': '127.0.0.1', 'DB_PORT': '5432', 'DB_NAME': 'firevision_db',
            'DB_USER': 'existing', 'DB_PASSWORD': '${LITERAL}%#@',
        }) as reader, patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_settings().database_url().password, '${LITERAL}%#@')
            reader.assert_called_once_with(PROJECT_ROOT / '.env', interpolate=False)

    def test_missing_password_and_invalid_port(self):
        settings = Settings(db_host='127.0.0.1', db_user='existing')
        with self.assertRaises(DatabaseConfigurationError):
            settings.database_url()
        for port in ('0', '65536', 'invalid'):
            with self.assertRaises(DatabaseConfigurationError):
                replace(settings, db_password='synthetic', db_port=port).database_url()

    def test_storage_paths(self):
        for invalid in ('/absolute', 'D:/absolute', '../outside', 'a/../outside', 'a\\b', 'a//b', '.'):
            with self.assertRaises(ValueError):
                storage_path(invalid)
        self.assertEqual(storage_path('videos/example.mp4'), get_settings().storage_root / 'videos' / 'example.mp4')

    def test_offline_migration(self):
        output = io.StringIO()
        config = Config(str(PROJECT_ROOT / 'alembic.ini'), output_buffer=output)
        command.upgrade(config, 'head', sql=True)
        sql = output.getvalue()
        for table in Base.metadata.tables:
            self.assertIn('CREATE TABLE ' + table, sql)
        self.assertIn('CREATE TRIGGER lock_analysis_run_settings', sql)
        self.assertNotIn('source_id', Base.metadata.tables['events'].c)


class HealthTests(unittest.TestCase):
    def request_json(self, path):
        try:
            with urlopen(f'http://127.0.0.1:{self.port}' + path, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def check_server(self, environment, expected):
        import socket
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        child = subprocess.Popen([
            sys.executable, '-m', 'uvicorn', 'backend.app.main:app',
            '--host', '127.0.0.1', '--port', str(self.port),
        ], cwd=PROJECT_ROOT, env={**os.environ, **environment}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                if child.poll() is not None:
                    self.fail('API не запустилося.')
                try:
                    status, body = self.request_json('/api/health')
                    break
                except URLError:
                    time.sleep(0.1)
            else:
                self.fail('Час очікування API вичерпано.')
            self.assertEqual((status, body), (200, {'status': 'ok', 'service': 'api'}))
            self.assertEqual(self.request_json('/api/health/db'), expected)
        finally:
            child.terminate()
            child.wait(timeout=10)

    def test_unconfigured(self):
        self.check_server({'DB_PASSWORD': ''}, (503, {'status': 'unavailable', 'service': 'database'}))

    def test_unavailable(self):
        self.check_server({
            'DB_HOST': '127.0.0.1', 'DB_PORT': '1', 'DB_NAME': 'firevision_db',
            'DB_USER': 'synthetic', 'DB_PASSWORD': 'synthetic@%secret',
        }, (503, {'status': 'unavailable', 'service': 'database'}))

    @unittest.skipUnless(os.environ.get('FIREVISION_TEST_DB') == '1', 'Потрібна налаштована БД')
    def test_real_database(self):
        self.check_server({}, (200, {'status': 'ok', 'service': 'database'}))


@unittest.skipUnless(os.environ.get('FIREVISION_TEST_DB') == '1', 'Потрібна налаштована БД')
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = build_engine(get_settings().database_url())
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, join_transaction_mode='create_savepoint')

    def tearDown(self):
        self.session.close()
        self.transaction.rollback()
        self.connection.close()
        self.engine.dispose()

    def test_schema_roundtrip_and_constraints(self):
        self.assertEqual(self.connection.scalar(sa.text('SELECT 1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SHOW server_encoding')), 'UTF8')
        head = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / 'alembic.ini'))).get_current_head()
        self.assertEqual(self.connection.scalar(sa.text('SELECT version_num FROM alembic_version')), head)
        inspector = sa.inspect(self.connection)
        self.assertEqual(set(inspector.get_table_names()), set(Base.metadata.tables) | {'alembic_version'})
        self.assertEqual(len(inspector.get_foreign_keys('analysis_runs')), 2)
        self.assertEqual(len(inspector.get_foreign_keys('events')), 1)
        source = VideoSource(name='Перевірка українського тексту ї є ґ', original_filename='відео.mp4', file_path='videos/test.mp4')
        model = ModelVersion(name='Тест із відкатом', architecture='test', weights_path='weights/test.pt', weights_sha256='a' * 64, class_mapping={'1': 'fire', '0': 'smoke'})
        self.session.add_all([source, model])
        self.session.flush()
        run = AnalysisRun(video_source_id=source.id, model_version_id=model.id, mode='full', settings_snapshot={'threshold': 0.5})
        self.session.add(run)
        self.session.flush()
        event = Event(analysis_run_id=run.id, feature_type='fire', start_seconds=Decimal('1.25'), operator_comment='Потребує перевірки оператором')
        self.session.add(event)
        self.session.flush()
        self.session.expire_all()
        self.assertEqual(source.name, 'Перевірка українського тексту ї є ґ')
        self.assertIsNone(source.duration_seconds)
        self.assertIsNone(source.width)
        self.assertIsNone(source.file_size_bytes)
        self.assertEqual(event.start_seconds, Decimal('1.250000'))
        self.assertIsNotNone(source.created_at.tzinfo)
        previous_update = event.updated_at
        event.operator_comment = 'Оновлений український коментар'
        self.session.flush()
        self.session.refresh(event)
        self.assertGreaterEqual(event.updated_at, previous_update)

        invalid_statements = [
            sa.update(AnalysisRun).where(AnalysisRun.id == run.id).values(settings_snapshot={'changed': True}),
            sa.update(AnalysisRun).where(AnalysisRun.id == run.id).values(progress=2),
            sa.update(AnalysisRun).where(AnalysisRun.id == run.id).values(result_paths={'video': 'D:/absolute.mp4'}),
            sa.update(AnalysisRun).where(AnalysisRun.id == run.id).values(video_source_id=uuid.uuid4()),
            sa.update(Event).where(Event.id == event.id).values(analysis_run_id=uuid.uuid4()),
            sa.update(Event).where(Event.id == event.id).values(automatic_status='confirmed'),
            sa.update(Event).where(Event.id == event.id).values(confidence=2),
            sa.update(VideoSource).where(VideoSource.id == source.id).values(file_path='../outside.mp4'),
            sa.update(ModelVersion).where(ModelVersion.id == model.id).values(class_mapping={'bad': 'fire'}),
            sa.delete(VideoSource).where(VideoSource.id == source.id),
            sa.delete(ModelVersion).where(ModelVersion.id == model.id),
            sa.delete(AnalysisRun).where(AnalysisRun.id == run.id),
        ]
        for statement in invalid_statements:
            with self.subTest(statement_type=type(statement).__name__):
                with self.assertRaises(IntegrityError):
                    with self.session.begin_nested():
                        self.session.execute(statement)


if __name__ == '__main__':
    unittest.main()
