from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from backend.app.config import get_settings


def build_engine(url) -> Engine:
    return create_engine(
        url, pool_pre_ping=True, hide_parameters=True,
        connect_args={'connect_timeout': 3, 'options': '-c statement_timeout=5000'},
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # Лінива ініціалізація: відсутня БД не перешкоджає запуску самого API.
    return build_engine(get_settings().database_url())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        # Commit виконує явно сценарій запису, а не залежність чи читання.
