"""Alembic environment.

The database URL comes from the Alembic config when the app runs migrations on startup
(`app.db.upgrade_database`), and from GEOAPI_* settings when the alembic CLI is used.
"""

from alembic import context
from sqlalchemy import create_engine

from app.config import Settings
from app.models import Base

config = context.config
database_url = config.get_main_option("sqlalchemy.url") or Settings().resolved_database_url


def run_migrations() -> None:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            # SQLite cannot ALTER most column properties; batch mode rebuilds the table.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
