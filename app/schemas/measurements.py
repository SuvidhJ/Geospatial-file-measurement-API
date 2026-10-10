from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import Feature, FileStatus
from app.services.crs import MeasurementMethod
from app.services.measure import MeasurementStatus

SQUARE_METRES_PER_HECTARE = 10_000
METRES_PER_KILOMETRE = 1_000


class GeometryType(StrEnum):
    POINT = "Point"
    MULTI_POINT = "MultiPoint"
    LINE_STRING = "LineString"
    MULTI_LINE_STRING = "MultiLineString"
    POLYGON = "Polygon"
    MULTI_POLYGON = "MultiPolygon"
    GEOMETRY_COLLECTION = "GeometryCollection"


class GeodesicValues(BaseModel):
    """The same measurement on the WGS84 ellipsoid, used to validate the projected value."""

    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None


class MeasurementRead(BaseModel):
    status: MeasurementStatus
    reason: str | None = Field(description="Why the feature was not measured, if it wasn't.")
    area_m2: float | None
    area_ha: float | None
    perimeter_m: float | None
    length_m: float | None
    length_km: float | None
    measurement_crs: str | None = Field(description="The projected CRS the value was computed in.")
    method: MeasurementMethod | None
    geodesic: GeodesicValues | None
    difference_pct: float | None = Field(
        description="(projected - geodesic) / geodesic * 100 for the primary value."
    )
    warnings: list[str]


class FeatureMeasurement(BaseModel):
    index: int = Field(description="0-based position of the feature in the file.")
    source_fid: int | None = Field(description="Feature ID from the source file, if it has one.")
    geometry_type: str | None = Field(description="Geometry type as read from the file.")
    measured_geometry_type: str | None = Field(
        description="Geometry type after repair (a repaired Polygon may become a MultiPolygon)."
    )
    repaired: bool
    source_crs: str | None
    geometry_crs: str | None = Field(
        description="CRS of `geometry`: EPSG:4326, or null when the source CRS is unknown."
    )
    properties: dict[str, Any]
    geometry: dict[str, Any] | None = Field(
        description="GeoJSON geometry; null when include_geometry=false."
    )
    measurement: MeasurementRead

    @classmethod
    def from_feature(cls, feature: Feature, *, include_geometry: bool) -> Self:
        is_polygonal = feature.geodesic_area_m2 is not None
        is_linear = feature.geodesic_length_m is not None
        geodesic = None
        if is_polygonal or is_linear:
            geodesic = GeodesicValues(
                area_m2=_round(feature.geodesic_area_m2, 2),
                perimeter_m=_round(feature.geodesic_perimeter_m, 3),
                length_m=_round(feature.geodesic_length_m, 3),
            )
        return cls(
            index=feature.index,
            source_fid=feature.source_fid,
            geometry_type=feature.geometry_type,
            measured_geometry_type=feature.measured_geometry_type,
            repaired=feature.repaired,
            source_crs=feature.source_crs,
            geometry_crs=feature.geometry_crs,
            properties=feature.properties,
            geometry=feature.geometry if include_geometry else None,
            measurement=MeasurementRead(
                status=MeasurementStatus(feature.measurement_status),
                reason=feature.measurement_reason,
                area_m2=_round(feature.area_m2, 2),
                area_ha=_round(_scale(feature.area_m2, 1 / SQUARE_METRES_PER_HECTARE), 4),
                perimeter_m=_round(feature.perimeter_m, 3),
                length_m=_round(feature.length_m, 3),
                length_km=_round(_scale(feature.length_m, 1 / METRES_PER_KILOMETRE), 6),
                measurement_crs=feature.measurement_crs,
                method=feature.measurement_method,
                geodesic=geodesic,
                difference_pct=_round(feature.difference_pct, 4),
                warnings=feature.warnings,
            ),
        )


class MeasurementSummary(BaseModel):
    """Totals over every feature matching the filter, not just the current page.

    Totals are sums of feature values: overlapping polygons are counted once each.
    """

    feature_count: int
    measured: int
    not_applicable: int
    skipped: int
    unsupported: int
    total_area_m2: float
    total_area_ha: float
    total_length_m: float
    total_length_km: float


class MeasurementPage(BaseModel):
    file_id: UUID
    filename: str
    status: FileStatus
    crs: str | None
    total: int
    limit: int
    offset: int
    summary: MeasurementSummary
    items: list[FeatureMeasurement]


def _scale(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _round(value: float | None, digits: int) -> float | None:
    # Rounded for readability; even this precision exceeds what survey inputs can support.
    return None if value is None else round(value, digits)
