import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import NotFoundError
from app.models import UploadedFile


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_file_or_404(file_id: str, db: Annotated[Session, Depends(get_db)]) -> UploadedFile:
    # Ids are opaque to clients: a malformed id is just an id that does not exist.
    try:
        record = db.get(UploadedFile, uuid.UUID(file_id))
    except ValueError:
        record = None
    if record is None:
        raise NotFoundError(f"File '{file_id}' was not found.")
    return record
