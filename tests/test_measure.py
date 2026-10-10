"""Accuracy tests against independent ground truth.

Ground-truth shapes are built by walking geodesics on the WGS84 ellipsoid, not in the
projection under test; a square drawn in UTM and measured back in UTM would prove nothing.
"""

import math

import pytest
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.services.crs import WGS84, MeasurementMethod, reproject, to_wgs84
from app.services.measure import GEOD, Measurement, MeasurementStatus, measure
from tests.factories import geodesic_square

BENGALURU = (77.5946, 12.9716)
WARN_PCT = 0.5


def measure_in(geometry: Polygon | LineString, crs: CRS) -> Measurement:
    return measure(geometry, to_wgs84(geometry, crs), crs, WARN_PCT)


def test_one_km_square_near_bengaluru() -> None:
    square = geodesic_square(*BENGALURU, side_m=1000)

    result = measure_in(square, WGS84)

    assert result.status is MeasurementStatus.MEASURED
    assert result.method is MeasurementMethod.UTM
    assert result.measurement_crs == "EPSG:32643"
    assert result.geodesic_area_m2 == pytest.approx(1_000_000, rel=1e-4)
    # Bengaluru is ~2.6° from zone 43's central meridian, so UTM overstates area by ~0.1%.
    assert result.area_m2 == pytest.approx(1_000_000, rel=2.5e-3)
    assert result.perimeter_m == pytest.approx(4000, rel=2.5e-3)
    assert result.warnings == []


def test_one_km_square_near_a_central_meridian_is_within_a_tenth_of_a_percent() -> None:
    square = geodesic_square(75.0, 12.97, side_m=1000)  # 75°E is zone 43's central meridian

    result = measure_in(square, WGS84)

    assert result.area_m2 == pytest.approx(1_000_000, rel=1e-3)


def test_area_is_never_computed_in_degrees() -> None:
    square = geodesic_square(*BENGALURU, side_m=1000)

    result = measure_in(square, WGS84)

    # In square degrees this polygon is ~8e-5; any degree-based maths would be off by 10^10.
    assert square.area < 1e-3
    assert result.area_m2 > 990_000
    assert result.measurement_crs != "EPSG:4326"


def test_line_of_known_geodesic_length() -> None:
    lon2, lat2, _ = GEOD.fwd(*BENGALURU, 45, 5000)
    line = LineString([BENGALURU, (lon2, lat2)])

    result = measure_in(line, WGS84)

    assert result.geodesic_length_m == pytest.approx(5000, rel=1e-6)
    assert result.length_m == pytest.approx(5000, rel=2.5e-3)
    assert result.area_m2 is None


def test_one_degree_of_longitude_at_the_equator() -> None:
    result = measure_in(LineString([(0, 0), (1, 0)]), WGS84)

    assert result.geodesic_length_m == pytest.approx(111_319.49, abs=0.01)
    assert result.length_m == pytest.approx(111_320, rel=1e-3)


def test_polygon_hole_is_subtracted_whatever_its_winding_order() -> None:
    outer = geodesic_square(*BENGALURU, side_m=200)
    hole_start = GEOD.fwd(*GEOD.fwd(*BENGALURU, 90, 75)[:2], 0, 75)[:2]
    hole = geodesic_square(*hole_start, side_m=50)
    # Same winding as the exterior: a naive geodesic sum would add the hole's area.
    polygon = Polygon(outer.exterior.coords, [hole.exterior.coords])

    result = measure_in(polygon, WGS84)

    assert result.geodesic_area_m2 == pytest.approx(40_000 - 2_500, rel=1e-4)
    assert result.area_m2 == pytest.approx(37_500, rel=2.5e-3)


def test_native_projected_metres_are_measured_without_reprojection() -> None:
    utm = CRS.from_epsg(32643)
    square = reproject(geodesic_square(*BENGALURU, side_m=1000), WGS84, utm)

    result = measure_in(square, utm)

    assert result.method is MeasurementMethod.NATIVE
    assert result.measurement_crs == "EPSG:32643"
    assert result.area_m2 == pytest.approx(square.area)


@pytest.mark.parametrize(
    ("crs", "lon", "lat", "metres_per_unit"),
    [
        # NAD83 / California zone 3, in US survey feet (1200/3937 m).
        (CRS.from_epsg(2227), -122.27, 37.80, 1200 / 3937),
        # UTM 43N in international feet (0.3048 m).
        (CRS.from_proj4("+proj=utm +zone=43 +datum=WGS84 +units=ft"), *BENGALURU, 0.3048),
    ],
)
def test_projected_feet_are_converted_to_metres(
    crs: CRS, lon: float, lat: float, metres_per_unit: float
) -> None:
    square_ft = reproject(geodesic_square(lon, lat, side_m=1000), WGS84, crs)

    result = measure_in(square_ft, crs)

    assert crs.axis_info[0].unit_conversion_factor == pytest.approx(metres_per_unit)
    assert result.method is MeasurementMethod.NATIVE
    assert result.area_m2 == pytest.approx(1_000_000, rel=2.5e-3)
    assert result.perimeter_m == pytest.approx(4000, rel=2.5e-3)


def test_web_mercator_input_is_not_measured_natively() -> None:
    mercator = CRS.from_epsg(3857)
    square = reproject(geodesic_square(*BENGALURU, side_m=1000), WGS84, mercator)
    # Measured directly in EPSG:3857 the area is inflated by roughly 1/cos²(lat), plus a little
    # more because pseudo-Mercator applies spherical formulas to ellipsoidal latitudes.
    naive_ratio = square.area / 1_000_000
    assert naive_ratio > 1 / math.cos(math.radians(BENGALURU[1])) ** 2
    assert naive_ratio == pytest.approx(1.0595, abs=1e-3)

    result = measure_in(square, mercator)

    assert result.method is MeasurementMethod.UTM
    assert result.area_m2 == pytest.approx(1_000_000, rel=2.5e-3)
    assert any("Mercator" in w for w in result.warnings)


def test_polar_feature_uses_equal_area_fallback() -> None:
    square = geodesic_square(20.0, 85.0, side_m=1000)

    result = measure_in(square, WGS84)

    assert result.method is MeasurementMethod.LAEA_FALLBACK
    assert result.area_m2 == pytest.approx(1_000_000, rel=1e-3)


def test_large_difference_from_geodesic_raises_a_warning() -> None:
    square = geodesic_square(*BENGALURU, side_m=1000)

    result = measure(square, square, WGS84, warning_threshold_pct=0.01)

    assert any("differ by" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("geometry", "status", "reason"),
    [
        (Point(*BENGALURU), MeasurementStatus.NOT_APPLICABLE, "Points have no area"),
        (Polygon(), MeasurementStatus.SKIPPED, "empty"),
        (None, MeasurementStatus.SKIPPED, "empty"),
        (
            GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])]),
            MeasurementStatus.UNSUPPORTED,
            "not supported for GeometryCollection",
        ),
    ],
)
def test_unmeasurable_geometries_are_handled_gracefully(
    geometry: object, status: MeasurementStatus, reason: str
) -> None:
    result = measure(geometry, geometry, WGS84, WARN_PCT)

    assert result.status is status
    assert reason in result.reason
    assert result.area_m2 is None
    assert result.length_m is None


def test_unknown_crs_is_skipped_not_guessed() -> None:
    square = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])

    result = measure(square, None, None, WARN_PCT)

    assert result.status is MeasurementStatus.SKIPPED
    assert "Unknown CRS" in result.reason
