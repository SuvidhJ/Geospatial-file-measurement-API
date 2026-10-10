from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    is_sqlite = database_url.startswith("sqlite")
    # FastAPI runs sync routes in a threadpool, so a SQLite connection can cross threads.
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    # No migration tool for a single-schema service; Alembic is listed under future scope.
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    # SQLite ignores ON DELETE CASCADE unless foreign keys are enabled on each connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
