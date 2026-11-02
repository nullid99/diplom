"""Керування лише БД проєкту; секрети й сирі винятки не виводяться."""
import argparse
import subprocess
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import inspect, text

from backend.app.config import PROJECT_ROOT, DatabaseConfigurationError, get_settings
from backend.app.database import build_engine


def migration_config(connection=None) -> Config:
    config = Config(str(PROJECT_ROOT / 'alembic.ini'))
    if connection is not None:
        config.attributes['connection'] = connection
    return config


def connect(database: str):
    settings = get_settings()
    settings.database_url()  # Обов’язково перевірити всі поля й наявність пароля.
    return psycopg.connect(
        host=settings.db_host, port=int(settings.db_port), dbname=database,
        user=settings.db_user, password=settings.db_password,
        connect_timeout=3, autocommit=True,
    )


def create_database():
    settings = get_settings()
    settings.database_url()
    with connect('postgres') as connection:
        existing = connection.execute(
            'SELECT pg_encoding_to_char(encoding), datallowconn FROM pg_database WHERE datname = %s',
            (settings.db_name,),
        ).fetchone()
        if existing is None:
            connection.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(settings.db_name)))
            print('Створено firevision_db з UTF-8.')
        elif existing != ('UTF8', True):
            raise RuntimeError('База існує, але її стан потребує ручної перевірки.')
        else:
            print('firevision_db вже існує: UTF-8, підключення дозволені.')
    engine = build_engine(settings.database_url())
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            print('Кількість наявних таблиць public:', len(tables))
            if 'alembic_version' in tables:
                versions = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
                print('Ревізії Alembic:', ', '.join(versions) or 'немає')
            expected = {'video_sources', 'model_versions', 'analysis_runs', 'events', 'alembic_version', 'app_settings'}
            if set(tables) - expected or (tables and 'alembic_version' not in tables):
                raise RuntimeError('Невідома схема: автоматичне продовження зупинено.')
    finally:
        engine.dispose()


def pg_tool(name: str, pg_bin: Path | None) -> str:
    import shutil
    candidate = pg_bin / (name + '.exe') if pg_bin else None
    executable = str(candidate) if candidate and candidate.is_file() else shutil.which(name)
    if not executable:
        raise RuntimeError('Укажіть -PgBin із каталогом утиліт PostgreSQL.')
    return executable


def run_pg_tool(name: str, arguments: list[str], pg_bin: Path | None, database: str):
    import os
    settings = get_settings()
    settings.database_url()
    environment = dict(os.environ)
    # Пароль передається лише дочірньому процесу, не в аргументах командного рядка.
    environment['PGPASSWORD'] = settings.db_password
    environment['PGCONNECT_TIMEOUT'] = '3'
    result = subprocess.run(
        [pg_tool(name, pg_bin), '--host', settings.db_host, '--port', settings.db_port,
         '--username', settings.db_user, '--no-password', '--dbname', database, *arguments],
        env=environment, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError('Утиліта PostgreSQL завершилася з помилкою; секретні деталі приховано.')


def backup(destination: Path, pg_bin: Path | None):
    destination = destination.resolve()
    if not destination.parent.is_dir():
        raise RuntimeError('Спочатку створіть каталог резервних копій.')
    # Ексклюзивне створення не дозволяє перезаписати чинну копію.
    with destination.open('xb'):
        pass
    try:
        run_pg_tool('pg_dump', ['--format=custom', '--file', str(destination)], pg_bin, 'firevision_db')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    print('Резервну копію custom створено.')


def restore(source: Path, pg_bin: Path | None):
    if not source.is_file():
        raise RuntimeError('Файл резервної копії не знайдено.')
    # Відновлення лише в уже створену порожню БД firevision_db, без --clean.
    with connect('firevision_db') as connection:
        count = connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f')").fetchone()[0]
        routines = connection.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname = 'public'").fetchone()[0]
        if count or routines:
            raise RuntimeError('Відновлення дозволене лише в порожню БД.')
    run_pg_tool('pg_restore', ['--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', str(source.resolve())], pg_bin, 'firevision_db')
    print('Копію відновлено в порожню firevision_db без власників і ACL.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'upgrade', 'current', 'check', 'sql', 'backup', 'restore'])
    parser.add_argument('--file', type=Path)
    parser.add_argument('--pg-bin', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'create':
            create_database()
        elif args.action == 'upgrade':
            command.upgrade(migration_config(), 'head')
            print('Міграції застосовано до head.')
        elif args.action == 'current':
            command.current(migration_config())
        elif args.action == 'check':
            command.check(migration_config())
        elif args.action == 'sql':
            command.upgrade(migration_config(), 'head', sql=True)
        elif args.action in ('backup', 'restore'):
            if args.file is None:
                raise RuntimeError('Потрібен параметр -File.')
            (backup if args.action == 'backup' else restore)(args.file, args.pg_bin)
    except DatabaseConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('Операцію БД не виконано. Перевірте локальну конфігурацію, доступ, стан схеми та параметри. Деталі помилки приховано.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
