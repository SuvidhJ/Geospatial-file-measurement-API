from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import upgrade_database
from app.models import Base


def test_migrations_create_the_schema_and_match_the_models(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"

    upgrade_database(url)
    upgrade_database(url)  # a second run is a no-op

    engine = create_engine(url)
    with engine.connect() as connection:
        drift = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        tables = set(inspect(connection).get_table_names())
    engine.dispose()
    assert drift == [], "models changed without a migration: run alembic revision --autogenerate"
    assert {"uploaded_files", "features", "alembic_version"} <= tables
