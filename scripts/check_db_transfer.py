"""Перевірка custom backup/restore в окремій новій тимчасовій БД."""
import argparse
import sys
import uuid

from psycopg import sql
from sqlalchemy import inspect, text

from backend.app.config import PROJECT_ROOT, get_settings
from backend.app.database import build_engine
from scripts.db import backup, connect, run_pg_tool


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, required=True)
    args = parser.parse_args()
    token = uuid.uuid4().hex
    name = 'firevision_restore_check_' + token
    archive = PROJECT_ROOT / '.tmp' / (token + '.dump')
    archive.parent.mkdir(exist_ok=True)
    created = False
    restored_engine = None
    source_engine = None
    failed = False
    try:
        settings = get_settings()
        url = settings.database_url()
        source_engine = build_engine(url)
        with source_engine.connect() as connection:
            expected_tables = set(inspect(connection).get_table_names())
            expected_revision = connection.scalar(text('SELECT version_num FROM alembic_version'))
            counts = {table: connection.scalar(text('SELECT count(*) FROM ' + table)) for table in ('video_sources', 'model_versions', 'analysis_runs', 'events')}
        with connect('postgres') as connection:
            # CREATE без IF NOT EXISTS: ніколи не використовуємо вже наявну БД.
            connection.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(name)))
            created = True
        backup(archive, args.pg_bin)
        run_pg_tool('pg_restore', ['--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', str(archive)], args.pg_bin, name)
        restored_engine = build_engine(url.set(database=name))
        with restored_engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == expected_tables
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == expected_revision
            assert connection.scalar(text('SHOW server_encoding')) == 'UTF8'
            for table, count in counts.items():
                assert connection.scalar(text('SELECT count(*) FROM ' + table)) == count
            assert len(inspect(connection).get_foreign_keys('analysis_runs')) == 2
            assert len(inspect(connection).get_foreign_keys('events')) == 1
            assert connection.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname IN ('lock_analysis_run_settings', 'touch_event_updated_at')")) == 2
        print('Custom backup/restore перевірено: схема, ревізія, UTF-8, зовнішні ключі, тригери й кількості записів збігаються.')
    except Exception:
        print('Перевірку перенесення не завершено. Перевірте доступ CREATEDB, конфігурацію та утиліти PostgreSQL; деталі приховано.', file=sys.stderr)
        failed = True
    finally:
        if restored_engine:
            restored_engine.dispose()
        if source_engine:
            source_engine.dispose()
        if created:
            try:
                with connect('postgres') as connection:
                    connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                print('Власну тимчасову БД видалено.')
            except Exception:
                print('Не вдалося прибрати власну тимчасову БД: ' + name, file=sys.stderr)
                failed = True
        if archive.exists():
            archive.unlink()
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
