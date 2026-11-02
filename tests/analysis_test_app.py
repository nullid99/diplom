"""Реальний HTTP/WS транспорт тільки для ізольованого browser-тесту."""
import os
import uuid

from sqlalchemy.orm import Session

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.database import build_engine
from backend.app.analysis_service import checksum
from backend.app.models import ModelVersion
import backend.app.database as database
import backend.app.main as main
import backend.app.analysis_api as analysis_api

name=os.environ.get('FIREVISION_ANALYSIS_TEST_DATABASE','')
if not name.startswith('firevision_analysis_test_'):
    raise RuntimeError('Only isolated analysis test database is allowed')
settings=get_settings()
if not settings.storage_root.is_relative_to((PROJECT_ROOT/'.tmp').resolve()):
    raise RuntimeError('Test storage must be under project .tmp')
engine=build_engine(settings.database_url().set(database=name))
database.get_engine=lambda:engine
main.get_engine=lambda:engine
analysis_api.get_engine=lambda:engine
app=main.app


@app.post('/test/model')
def seed_test_model():
    identifier=uuid.uuid4()
    path=settings.storage_root/f'browser-test-only-{identifier}.fixture'
    path.write_bytes(b'NOT YOLO: isolated browser test metadata, no inference')
    with Session(engine) as session:
        session.add(ModelVersion(id=identifier,name='ТІЛЬКИ ТЕСТ, не справжня модель',architecture='YOLO11n',weights_path=path.name,weights_sha256=checksum(path),class_mapping={'0':'smoke','1':'fire'},training_metadata={'test_fixture':True}))
        session.commit()
    return {'id':str(identifier)}
