"""API лише для ізольованої наскрізної перевірки."""
import os

import backend.app.database as database
import backend.app.main as main
from backend.app.config import get_settings
from backend.app.database import build_engine

name = os.environ.get('FIREVISION_VIDEO_TEST_DATABASE', '')
if not name.startswith('firevision_video_test_'):
    raise RuntimeError('Потрібна окрема тестова БД.')
engine = build_engine(get_settings().database_url().set(database=name))
database.get_engine = lambda: engine
main.get_engine = lambda: engine
app = main.app
