"""Volume and surface-area tests against synthetic DEMs with closed-form answers."""

import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

from app.config import Settings
from app.main import create_app
from tests.factories import cell_centres, shapefile_zip, write_dem, zip_files

# A 200 m x 200 m DEM at 0.5 m resolution in UTM 43N, centred on (776000, 1435000).
LEFT, TOP, CELL, SIZE = 775_900.0, 1_435_100.0, 0.5, 400
CENTRE_X, CENTRE_Y = 776_000.0, 1_435_000.0
GROUND = 900.0
RADIUS, HEIGHT = 50.0, 10.0
CONE_VOLUME = math.pi * RADIUS**2 * HEIGHT / 3
# A 140 m square around the cone, so the polygon boundary lies on flat ground.
TOE = box(CENTRE_X - 70, CENTRE_Y - 70, CENTRE_X + 70, CENTRE_Y + 70)


def cone(sign: float = 1.0) -> np.ndarray:
    xs, ys = cell_centres(LEFT, TOP, CELL, SIZE)
    distance = np.hypot(xs - CENTRE_X, ys - CENTRE_Y)
    return GROUND + sign * HEIGHT * np.clip(1 - distance / RADIUS, 0, None)


def dem_file(tmp_path: Path, elevations: np.ndarray, crs: str | None = "EPSG:32643") -> Path:
    return write_dem(tmp_path / "dem.tif", elevations, left=LEFT, top=TOP, cell_size=CELL, crs=crs)


def upload_polygons(client: TestClient, tmp_path: Path, *geometries: BaseGeometry) -> str:
    archive = shapefile_zip(tmp_path, gpd.GeoDataFrame(geometry=list(geometries), crs=32643))
    response = client.post("/api/files/", files={"file": ("site.zip", archive.read_bytes())})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def post_dem(client: TestClient, file_id: str, dem: Path, **params: str) -> Response:
    return client.post(
        f"/api/files/{file_id}/volumes/",
        params=params,
        files={"dem": ("dem.tif", dem.read_bytes())},
    )


def only_item(response: Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    return dict(item)


def test_cone_stockpile_volume_and_surface_area(client: TestClient, tmp_path: Path) -> None:
    file_id = upload_polygons(client, tmp_path, TOE)

    response = post_dem(client, file_id, dem_file(tmp_path, cone()))

    report = response.json()
    item = only_item(response)
    assert report["base_method"] == "boundary-mean"
    assert report["dem"] == {
        "crs": "EPSG:32643",
        "cell_size_m": [0.5, 0.5],
        "width": SIZE,
        "height": SIZE,
    }
    assert item["measured"] is True
    assert item["base_elevation_m"] == pytest.approx(GROUND)
    assert item["cut_volume_m3"] == pytest.approx(CONE_VOLUME, rel=5e-3)
    assert item["fill_volume_m3"] == pytest.approx(0, abs=1)
    assert item["planimetric_area_m2"] == pytest.approx(140 * 140, rel=1e-3)
    # Flat ground around the cone plus the cone's lateral surface, π·R·√(R² + h²).
    cone_footprint = math.pi * RADIUS**2
    lateral_surface = math.pi * RADIUS * math.hypot(RADIUS, HEIGHT)
    assert item["surface_area_m2"] == pytest.approx(
        140 * 140 - cone_footprint + lateral_surface, rel=5e-3
    )
    assert item["dem_coverage_pct"] == 100
    assert report["totals"]["net_volume_m3"] == item["net_volume_m3"]


def test_pit_is_reported_as_fill(client: TestClient, tmp_path: Path) -> None:
    file_id = upload_polygons(client, tmp_path, TOE)

    item = only_item(post_dem(client, file_id, dem_file(tmp_path, cone(sign=-1))))

    assert item["fill_volume_m3"] == pytest.approx(CONE_VOLUME, rel=5e-3)
    assert item["cut_volume_m3"] == pytest.approx(0, abs=1)
    assert item["net_volume_m3"] == pytest.approx(-CONE_VOLUME, rel=5e-3)


def test_base_method_on_sloping_ground(client: TestClient, tmp_path: Path) -> None:
    xs, _ = cell_centres(LEFT, TOP, CELL, SIZE)
    slope = GROUND + 0.05 * (xs - TOE.bounds[0])  # 5% grade rising eastwards
    file_id = upload_polygons(client, tmp_path, TOE)
    dem = dem_file(tmp_path, slope)

    mean_base = only_item(post_dem(client, file_id, dem))
    min_base = only_item(post_dem(client, file_id, dem, base="boundary-min"))

    # A plane through the mean boundary elevation balances cut and fill on a uniform slope.
    assert mean_base["net_volume_m3"] == pytest.approx(0, abs=50)
    # From the lowest boundary point the slope is a wedge averaging 0.05 x 70 m = 3.5 m high.
    assert min_base["cut_volume_m3"] == pytest.approx(140 * 140 * 3.5, rel=5e-3)


def test_missing_dem_data_is_reported_as_partial_coverage(
    client: TestClient, tmp_path: Path
) -> None:
    elevations = cone()
    elevations[: SIZE // 2, :] = -9999.0  # the northern half has no data
    file_id = upload_polygons(client, tmp_path, TOE)

    item = only_item(post_dem(client, file_id, dem_file(tmp_path, elevations)))

    assert item["measured"] is True
    assert item["dem_coverage_pct"] == pytest.approx(50, abs=1)
    assert item["cut_volume_m3"] == pytest.approx(CONE_VOLUME / 2, rel=1e-2)
    assert "only 50.0%" in item["warnings"][0]


def test_polygon_outside_the_dem_is_skipped(client: TestClient, tmp_path: Path) -> None:
    far_away = box(CENTRE_X + 5_000, CENTRE_Y, CENTRE_X + 5_100, CENTRE_Y + 100)
    file_id = upload_polygons(client, tmp_path, TOE, far_away)

    report = post_dem(client, file_id, dem_file(tmp_path, cone())).json()

    assert [item["measured"] for item in report["items"]] == [True, False]
    assert report["items"][1]["reason"] == "The polygon is outside the DEM."
    assert report["totals"]["cut_volume_m3"] == report["items"][0]["cut_volume_m3"]


def test_points_have_no_volume(client: TestClient, tmp_path: Path) -> None:
    file_id = upload_polygons(client, tmp_path, Point(CENTRE_X, CENTRE_Y))

    report = post_dem(client, file_id, dem_file(tmp_path, cone())).json()

    assert report["items"] == []
    assert report["totals"]["net_volume_m3"] == 0


def test_polygon_over_the_cell_limit_is_skipped(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", max_dem_cells_per_feature=1000)
    with TestClient(create_app(settings)) as client:
        file_id = upload_polygons(client, tmp_path, TOE)
        item = only_item(post_dem(client, file_id, dem_file(tmp_path, cone())))

    assert item["measured"] is False
    assert "more than 1000 DEM cells" in item["reason"]


@pytest.mark.parametrize(
    ("crs", "message"),
    [("EPSG:4326", "must be projected with metre units"), (None, "has no CRS")],
)
def test_dem_without_a_metric_crs_is_rejected(
    client: TestClient, tmp_path: Path, crs: str | None, message: str
) -> None:
    file_id = upload_polygons(client, tmp_path, TOE)

    response = post_dem(client, file_id, dem_file(tmp_path, cone(), crs=crs))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"
    assert message in response.json()["error"]["message"]


def test_non_tiff_dem_is_rejected_before_gdal_opens_it(client: TestClient, tmp_path: Path) -> None:
    file_id = upload_polygons(client, tmp_path, TOE)
    vrt = tmp_path / "dem.vrt"
    vrt.write_text('<VRTDataset rasterXSize="1" rasterYSize="1"></VRTDataset>')

    response = post_dem(client, file_id, vrt)

    assert response.status_code == 400
    assert "must be a GeoTIFF" in response.json()["error"]["message"]


def test_volumes_for_a_failed_file_return_409(client: TestClient, tmp_path: Path) -> None:
    archive = zip_files(tmp_path / "docs.zip", [("readme.txt", b"no shapefile here")])
    response = client.post("/api/files/", files={"file": ("docs.zip", archive.read_bytes())})
    file_id = response.json()["error"]["details"]["file_id"]

    assert post_dem(client, file_id, dem_file(tmp_path, cone())).status_code == 409
