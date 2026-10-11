from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    upgrade_database(database_url)
    is_sqlite = database_url.startswith("sqlite")
    # FastAPI runs sync routes in a threadpool, so a SQLite connection can cross threads.
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return sessionmaker(engine, expire_on_commit=False)


def upgrade_database(database_url: str) -> None:
    """Apply any pending Alembic migrations."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    # SQLite ignores ON DELETE CASCADE unless foreign keys are enabled on each connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
