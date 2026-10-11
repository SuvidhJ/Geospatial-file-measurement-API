from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import FileFormat, FileStatus


class FileRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "a5fe2f73-eebe-4f51-a15a-204cd7d9d2ee",
                    "filename": "bengaluru_survey.kml",
                    "format": "kml",
                    "status": "COMPLETED",
                    "feature_count": 5,
                    "crs": "EPSG:4326",
                    "crs_assumed": False,
                    "geometry_type_counts": {"Polygon": 1, "LineString": 1, "Point": 3},
                    "warnings": [],
                    "error_detail": None,
                    "size_bytes": 1289,
                    "sha256": "420b751a56ee0f094509bb5c6482f6c9db5a341f9cc5e54019b93b2b91b1acbc",
                    "processing_time_ms": 18,
                    "created_at": "2026-10-11T15:52:19.819787Z",
                }
            ]
        },
    )

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
    size_bytes: int = Field(description="Size of the uploaded file.")
    sha256: str = Field(
        description="SHA-256 of the uploaded file, for integrity and de-duplication."
    )
    processing_time_ms: int | None = Field(
        description="Time spent reading and measuring the file; null until processed."
    )
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
