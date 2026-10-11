"""Read-side queries for stored files and their measurements."""

import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models import Feature, UploadedFile
from app.schemas.measurements import (
    METRES_PER_KILOMETRE,
    SQUARE_METRES_PER_HECTARE,
    GeometryType,
    MeasurementSummary,
)
from app.services.measure import MeasurementStatus


def list_files(db: Session, *, limit: int, offset: int) -> tuple[int, list[UploadedFile]]:
    total = db.scalar(select(func.count()).select_from(UploadedFile)) or 0
    files = db.scalars(
        select(UploadedFile).order_by(UploadedFile.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return total, list(files)


def list_features(
    db: Session,
    file_id: uuid.UUID,
    *,
    geometry_type: GeometryType | None,
    limit: int,
    offset: int,
) -> list[Feature]:
    stmt = (
        select(Feature)
        .where(*_feature_filter(file_id, geometry_type))
        .order_by(Feature.index)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def summarize(
    db: Session, file_id: uuid.UUID, *, geometry_type: GeometryType | None
) -> MeasurementSummary:
    stmt = (
        select(
            Feature.measurement_status,
            func.count(),
            func.sum(Feature.area_m2),
            func.sum(Feature.length_m),
        )
        .where(*_feature_filter(file_id, geometry_type))
        .group_by(Feature.measurement_status)
    )
    counts = dict.fromkeys(MeasurementStatus, 0)
    total_area = total_length = 0.0
    for status, count, area, length in db.execute(stmt):
        counts[MeasurementStatus(status)] = count
        total_area += area or 0.0
        total_length += length or 0.0

    return MeasurementSummary(
        feature_count=sum(counts.values()),
        measured=counts[MeasurementStatus.MEASURED],
        not_applicable=counts[MeasurementStatus.NOT_APPLICABLE],
        skipped=counts[MeasurementStatus.SKIPPED],
        unsupported=counts[MeasurementStatus.UNSUPPORTED],
        total_area_m2=round(total_area, 2),
        total_area_ha=round(total_area / SQUARE_METRES_PER_HECTARE, 4),
        total_length_m=round(total_length, 3),
        total_length_km=round(total_length / METRES_PER_KILOMETRE, 6),
    )


def _feature_filter(
    file_id: uuid.UUID, geometry_type: GeometryType | None
) -> list[ColumnElement[bool]]:
    conditions = [Feature.file_id == file_id]
    if geometry_type is not None:
        conditions.append(Feature.geometry_type == geometry_type.value)
    return conditions
