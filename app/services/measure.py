"""Per-feature measurement: a projected value (primary, per the spec) plus a geodesic check."""

from dataclasses import dataclass, field
from enum import StrEnum

import shapely
from pyproj import CRS, Geod
from shapely.geometry.base import BaseGeometry

from app.services.crs import WGS84, MeasurementMethod, choose_measurement_crs, reproject

GEOD = Geod(ellps="WGS84")
POLYGONAL_TYPES = {"Polygon", "MultiPolygon"}
LINEAR_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}


class MeasurementStatus(StrEnum):
    MEASURED = "measured"
    NOT_APPLICABLE = "not_applicable"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"


@dataclass
class Measurement:
    status: MeasurementStatus
    reason: str | None = None
    measurement_crs: str | None = None
    method: MeasurementMethod | None = None
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    geodesic_area_m2: float | None = None
    geodesic_perimeter_m: float | None = None
    geodesic_length_m: float | None = None
    difference_pct: float | None = None
    warnings: list[str] = field(default_factory=list)


def measure(
    geometry: BaseGeometry | None,
    geometry_wgs84: BaseGeometry | None,
    source_crs: CRS | None,
    warning_threshold_pct: float,
) -> Measurement:
    """Measure one feature.

    `geometry` is in `source_crs`; `geometry_wgs84` is the same geometry in lon/lat, used
    to choose the measurement CRS and for the geodesic cross-check.
    """
    if geometry is None or geometry.is_empty:
        return Measurement(MeasurementStatus.SKIPPED, reason="The geometry is empty.")

    geometry_type = geometry.geom_type
    if geometry_type in POINT_TYPES:
        return Measurement(
            MeasurementStatus.NOT_APPLICABLE, reason="Points have no area or length."
        )
    if geometry_type not in POLYGONAL_TYPES | LINEAR_TYPES:
        return Measurement(
            MeasurementStatus.UNSUPPORTED,
            reason=f"Measurement is not supported for {geometry_type} geometries.",
        )
    if source_crs is None or geometry_wgs84 is None:
        return Measurement(
            MeasurementStatus.SKIPPED,
            reason="Unknown CRS: the geometry cannot be transformed to a projected CRS.",
        )

    target = choose_measurement_crs(source_crs, geometry_wgs84)
    if target.method is MeasurementMethod.NATIVE:
        projected = geometry
    else:
        projected = reproject(geometry_wgs84, WGS84, target.crs)

    result = Measurement(
        MeasurementStatus.MEASURED,
        measurement_crs=target.label,
        method=target.method,
        warnings=[target.note] if target.note else [],
    )
    if geometry_type in POLYGONAL_TYPES:
        result.area_m2 = projected.area * target.to_metres**2
        result.perimeter_m = projected.length * target.to_metres
        result.geodesic_area_m2, result.geodesic_perimeter_m = geodesic_area_perimeter(
            geometry_wgs84
        )
        value, reference = result.area_m2, result.geodesic_area_m2
    else:
        result.length_m = projected.length * target.to_metres
        result.geodesic_length_m = GEOD.geometry_length(geometry_wgs84)
        value, reference = result.length_m, result.geodesic_length_m

    result.difference_pct = percent_difference(value, reference)
    if result.difference_pct is not None and abs(result.difference_pct) > warning_threshold_pct:
        result.warnings.append(
            f"Projected and geodesic values differ by {result.difference_pct:.3f}% "
            f"(threshold {warning_threshold_pct}%)."
        )
    return result


def geodesic_area_perimeter(geometry_wgs84: BaseGeometry) -> tuple[float, float]:
    # pyproj adds each ring's area with a sign set by its winding order. Orienting the
    # exterior counter-clockwise and holes clockwise makes holes subtract, whatever winding
    # the source file used; abs() then removes the remaining sign convention.
    oriented = shapely.orient_polygons(geometry_wgs84)
    area, _ = GEOD.geometry_area_perimeter(oriented)
    # pyproj's polygon perimeter covers only exterior rings; the projected perimeter (shapely
    # .length) includes holes, so sum every ring to compare like with like.
    perimeter = sum(GEOD.geometry_length(ring) for ring in shapely.get_rings(oriented))
    return abs(area), perimeter


def percent_difference(value: float, reference: float) -> float | None:
    if reference == 0:
        return None
    return (value - reference) / reference * 100
