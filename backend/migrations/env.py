from alembic import context

from backend.app.config import get_settings
from backend.app.database import build_engine
from backend.app.models import Base

target_metadata = Base.metadata


def run_migrations_offline():
    # URL із секретами не записується в INI / ConfigParser; % не інтерполюється.
    context.configure(
        dialect_name='postgresql', target_metadata=target_metadata,
        literal_binds=True, dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    supplied = context.config.attributes.get('connection')
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = build_engine(get_settings().database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
