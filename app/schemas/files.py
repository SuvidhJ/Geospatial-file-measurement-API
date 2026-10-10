from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import FileFormat, FileStatus


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    format: FileFormat
    status: FileStatus
    feature_count: int
    crs: str | None = Field(description="Source CRS of the file, e.g. 'EPSG:4326'.")
    crs_assumed: bool = Field(
        description="True when the Shapefile had no .prj and EPSG:4326 was assumed."
    )
    geometry_type_counts: dict[str, int] = Field(
        description="Number of features per source geometry type."
    )
    warnings: list[str]
    error_detail: str | None = Field(description="Why processing failed, when status is FAILED.")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite drops timezone info; timestamps are always written in UTC.
        return value if value.tzinfo else value.replace(tzinfo=UTC)


class FileList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FileRead]
