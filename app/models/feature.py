import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.file import UploadedFile


class Feature(Base):
    """One feature of an uploaded file, with its measurement.

    Measurement values are real columns (not a JSON blob) so filtering and the summary
    totals can be done in SQL.
    """

    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("file_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int]
    source_fid: Mapped[int | None]
    geometry_type: Mapped[str | None] = mapped_column(String(32), index=True)
    measured_geometry_type: Mapped[str | None] = mapped_column(String(32))
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    geometry_crs: Mapped[str | None] = mapped_column(Text)
    source_crs: Mapped[str | None] = mapped_column(Text)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    repaired: Mapped[bool] = mapped_column(default=False)

    measurement_status: Mapped[str] = mapped_column(String(16))
    measurement_reason: Mapped[str | None] = mapped_column(Text)
    measurement_crs: Mapped[str | None] = mapped_column(Text)
    measurement_method: Mapped[str | None] = mapped_column(String(32))
    area_m2: Mapped[float | None]
    perimeter_m: Mapped[float | None]
    length_m: Mapped[float | None]
    geodesic_area_m2: Mapped[float | None]
    geodesic_perimeter_m: Mapped[float | None]
    geodesic_length_m: Mapped[float | None]
    difference_pct: Mapped[float | None]
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    file: Mapped["UploadedFile"] = relationship(back_populates="features")
