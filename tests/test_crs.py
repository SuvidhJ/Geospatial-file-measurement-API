import pytest
from pyproj import CRS
from shapely.geometry import Point, box

from app.services.crs import (
    WGS84,
    MeasurementMethod,
    choose_measurement_crs,
    reproject,
    utm_zone,
)


@pytest.mark.parametrize(
    ("longitude", "zone"), [(-180, 1), (3, 31), (77.59, 43), (78.0, 44), (179.99, 60), (180, 60)]
)
def test_utm_zone(longitude: float, zone: int) -> None:
    assert utm_zone(longitude) == zone


def test_axis_order_is_lon_lat() -> None:
    # Bengaluru in UTM 43N is roughly E 777 km, N 1434 km. Swapped axes would land far away.
    utm = reproject(Point(77.5946, 12.9716), WGS84, CRS.from_epsg(32643))

    assert 770_000 < utm.x < 785_000
    assert 1_425_000 < utm.y < 1_440_000


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [(77.59, 12.97, "EPSG:32643"), (151.2, -33.9, "EPSG:32756"), (-0.13, 51.5, "EPSG:32630")],
)
def test_geographic_source_uses_utm_zone_of_centroid(lon: float, lat: float, expected: str) -> None:
    feature = box(lon, lat, lon + 0.01, lat + 0.01)

    choice = choose_measurement_crs(WGS84, feature)

    assert choice.method is MeasurementMethod.UTM
    assert choice.label == expected
    assert choice.crs.is_projected


def test_projected_source_is_used_natively() -> None:
    choice = choose_measurement_crs(CRS.from_epsg(32643), box(77.5, 12.9, 77.6, 13.0))

    assert choice.method is MeasurementMethod.NATIVE
    assert choice.label == "EPSG:32643"
    assert choice.to_metres == 1.0


def test_web_mercator_source_is_reprojected_to_utm() -> None:
    choice = choose_measurement_crs(CRS.from_epsg(3857), box(77.5, 12.9, 77.6, 13.0))

    assert choice.method is MeasurementMethod.UTM
    assert choice.label == "EPSG:32643"
    assert "Mercator" in choice.note


def test_polar_feature_falls_back_to_laea() -> None:
    choice = choose_measurement_crs(WGS84, box(10, 85, 11, 85.5))

    assert choice.method is MeasurementMethod.LAEA_FALLBACK
    assert choice.label.startswith("+proj=laea")
    assert "80°S-84°N" in choice.note


def test_feature_far_from_central_meridian_falls_back_to_laea() -> None:
    # Zone 43's central meridian is 75°E; this feature reaches 81°E (6° away).
    choice = choose_measurement_crs(WGS84, box(72.5, 12, 81, 13))

    assert choice.method is MeasurementMethod.LAEA_FALLBACK
    assert "central meridian" in choice.note
