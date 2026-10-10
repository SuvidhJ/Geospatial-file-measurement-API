from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from shapely.geometry import MultiPolygon, Point, Polygon

from app.config import Settings
from app.main import create_app
from tests.factories import (
    geodesic_square,
    kml_document,
    kml_line,
    kml_point,
    kml_polygon,
    placemark,
    shapefile_zip,
    write_shapefile,
    zip_files,
)

BENGALURU = (77.5946, 12.9716)


def upload(client: TestClient, name: str, content: bytes) -> Response:
    return client.post("/api/files/", files={"file": (name, content, "application/octet-stream")})


def measurements(client: TestClient, file_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/files/{file_id}/measurements/", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def assert_error(response: Response, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


@pytest.fixture
def survey_kml() -> bytes:
    square = list(geodesic_square(*BENGALURU, side_m=1000).exterior.coords)
    return kml_document(
        {
            "Parcels": [placemark("Plot A", kml_polygon(square), {"owner": "BBMP"})],
            "Roads": [
                placemark("Ring road", kml_line([(77.60, 12.97, 900), (77.62, 12.97, 905)])),
                placemark(
                    "Mixed",
                    "<MultiGeometry>"
                    f"{kml_point(77.6, 12.9)}{kml_line([(77.6, 12.9), (77.61, 12.9)])}"
                    "</MultiGeometry>",
                ),
            ],
            "Control": [
                placemark("GCP-1", kml_point(*BENGALURU)),
                placemark("No geometry", ""),
            ],
        }
    ).encode()


@pytest.fixture
def uploaded_kml(client: TestClient, survey_kml: bytes) -> dict[str, Any]:
    response = upload(client, "survey.kml", survey_kml)
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_kml_returns_file_record(uploaded_kml: dict[str, Any]) -> None:
    assert uploaded_kml["filename"] == "survey.kml"
    assert uploaded_kml["format"] == "kml"
    assert uploaded_kml["status"] == "COMPLETED"
    assert uploaded_kml["feature_count"] == 5
    assert uploaded_kml["crs"] == "EPSG:4326"
    assert uploaded_kml["crs_assumed"] is False
    assert uploaded_kml["geometry_type_counts"] == {
        "Polygon": 1,
        "LineString": 1,
        "GeometryCollection": 1,
        "Point": 1,
        "None": 1,
    }
    assert uploaded_kml["error_detail"] is None


def test_get_file_matches_upload_response(client: TestClient, uploaded_kml: dict[str, Any]) -> None:
    response = client.get(f"/api/files/{uploaded_kml['id']}/")

    assert response.status_code == 200
    assert response.json() == uploaded_kml


def test_measurements_cover_every_geometry_case(
    client: TestClient, uploaded_kml: dict[str, Any]
) -> None:
    body = measurements(client, uploaded_kml["id"])
    by_name = {item["properties"]["Name"]: item for item in body["items"]}

    plot = by_name["Plot A"]
    assert plot["geometry_type"] == "Polygon"
    assert plot["geometry"]["type"] == "Polygon"
    assert plot["geometry_crs"] == "EPSG:4326"
    assert plot["source_crs"] == "EPSG:4326"
    assert plot["properties"] == {"Name": "Plot A", "owner": "BBMP", "kml_layer": "Parcels"}
    assert plot["measurement"]["status"] == "measured"
    assert plot["measurement"]["method"] == "projected-utm"
    assert plot["measurement"]["measurement_crs"] == "EPSG:32643"
    assert plot["measurement"]["area_m2"] == pytest.approx(1_000_000, rel=2.5e-3)
    assert plot["measurement"]["area_ha"] == pytest.approx(100, rel=2.5e-3)
    assert plot["measurement"]["geodesic"]["area_m2"] == pytest.approx(1_000_000, rel=1e-4)

    road = by_name["Ring road"]["measurement"]
    assert road["status"] == "measured"
    assert road["length_km"] == pytest.approx(road["length_m"] / 1000)
    assert road["area_m2"] is None
    assert any("Z values were dropped" in w for w in road["warnings"])

    assert by_name["GCP-1"]["measurement"]["status"] == "not_applicable"
    assert by_name["Mixed"]["measurement"]["status"] == "unsupported"
    assert by_name["No geometry"]["measurement"]["status"] == "skipped"
    assert by_name["No geometry"]["geometry"] is None


def test_measurement_summary(client: TestClient, uploaded_kml: dict[str, Any]) -> None:
    summary = measurements(client, uploaded_kml["id"])["summary"]

    assert summary["feature_count"] == 5
    assert summary["measured"] == 2
    assert summary["not_applicable"] == 1
    assert summary["skipped"] == 1
    assert summary["unsupported"] == 1
    assert summary["total_area_m2"] == pytest.approx(1_000_000, rel=2.5e-3)
    assert summary["total_length_m"] > 2000


def test_measurements_pagination(client: TestClient, uploaded_kml: dict[str, Any]) -> None:
    page = measurements(client, uploaded_kml["id"], limit=2, offset=1)

    assert page["total"] == 5
    assert (page["limit"], page["offset"]) == (2, 1)
    assert [item["index"] for item in page["items"]] == [1, 2]
    assert page["summary"]["feature_count"] == 5


def test_measurements_geometry_type_filter(
    client: TestClient, uploaded_kml: dict[str, Any]
) -> None:
    page = measurements(client, uploaded_kml["id"], geometry_type="Polygon")

    assert page["total"] == 1
    assert [item["geometry_type"] for item in page["items"]] == ["Polygon"]
    assert page["summary"]["total_length_m"] == 0


def test_measurements_without_geometry(client: TestClient, uploaded_kml: dict[str, Any]) -> None:
    page = measurements(client, uploaded_kml["id"], include_geometry="false")

    assert all(item["geometry"] is None for item in page["items"])


def test_invalid_query_parameter_uses_error_envelope(
    client: TestClient, uploaded_kml: dict[str, Any]
) -> None:
    response = client.get(
        f"/api/files/{uploaded_kml['id']}/measurements/", params={"geometry_type": "Circle"}
    )

    assert_error(response, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("file_id", ["3f2b8c1e-5d0a-4a7e-9b8e-2c4d6f8a1b3c", "not-a-uuid"])
@pytest.mark.parametrize("suffix", ["", "measurements/"])
def test_unknown_file_returns_404(client: TestClient, file_id: str, suffix: str) -> None:
    response = client.get(f"/api/files/{file_id}/{suffix}")

    assert_error(response, 404, "NOT_FOUND")


def test_upload_shapefile_zip_in_nested_folder(client: TestClient, tmp_path: Path) -> None:
    square = geodesic_square(*BENGALURU, side_m=100)
    gdf = gpd.GeoDataFrame({"plot": ["P-1"]}, geometry=[square], crs=4326)
    archive = shapefile_zip(tmp_path, gdf, name="parcels", folder="export/layers")

    response = upload(client, "parcels.zip", archive.read_bytes())

    assert response.status_code == 201, response.text
    file = response.json()
    assert (file["format"], file["crs"], file["feature_count"]) == ("shapefile", "EPSG:4326", 1)
    (item,) = measurements(client, file["id"])["items"]
    assert item["source_fid"] == 0
    assert item["properties"] == {"plot": "P-1"}
    assert item["measurement"]["area_m2"] == pytest.approx(10_000, rel=2.5e-3)


def test_upload_projected_shapefile_is_measured_natively(
    client: TestClient, tmp_path: Path
) -> None:
    square = gpd.GeoSeries([geodesic_square(*BENGALURU, side_m=100)], crs=4326).to_crs(32643)
    archive = shapefile_zip(tmp_path, gpd.GeoDataFrame(geometry=square))

    file = upload(client, "utm.zip", archive.read_bytes()).json()
    (item,) = measurements(client, file["id"])["items"]

    assert file["crs"] == "EPSG:32643"
    assert item["measurement"]["method"] == "native"
    assert item["geometry_crs"] == "EPSG:4326"
    lon, lat = item["geometry"]["coordinates"][0][0]
    assert (lon, lat) == pytest.approx(BENGALURU, abs=1e-6)


def test_multipart_and_repaired_geometries(client: TestClient, tmp_path: Path) -> None:
    a = geodesic_square(*BENGALURU, side_m=100)
    b = geodesic_square(BENGALURU[0] + 0.01, BENGALURU[1], side_m=100)
    bow_tie = Polygon([(77.60, 12.90), (77.61, 12.91), (77.61, 12.90), (77.60, 12.91)])
    gdf = gpd.GeoDataFrame(geometry=[MultiPolygon([a, b]), bow_tie], crs=4326)
    archive = shapefile_zip(tmp_path, gdf)

    file = upload(client, "mixed.zip", archive.read_bytes()).json()
    multi, repaired = measurements(client, file["id"])["items"]

    assert multi["measurement"]["area_m2"] == pytest.approx(20_000, rel=2.5e-3)
    assert repaired["repaired"] is True
    assert repaired["measured_geometry_type"] == "MultiPolygon"
    assert repaired["measurement"]["status"] == "measured"
    assert repaired["measurement"]["area_m2"] > 0
    assert any("repaired" in w for w in repaired["measurement"]["warnings"])


def test_shapefile_without_prj_in_lonlat_range_is_assumed_wgs84(
    client: TestClient, tmp_path: Path
) -> None:
    gdf = gpd.GeoDataFrame(geometry=[geodesic_square(*BENGALURU, side_m=100)], crs=4326)
    archive = shapefile_zip(tmp_path, gdf, exclude=(".prj",))

    file = upload(client, "noprj.zip", archive.read_bytes()).json()

    assert file["crs"] == "EPSG:4326"
    assert file["crs_assumed"] is True
    assert "assumed" in file["warnings"][0]


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_shapefile_without_prj_and_projected_coordinates_is_not_guessed(
    client: TestClient, tmp_path: Path
) -> None:
    square = Polygon([(776_000, 1_435_000), (776_100, 1_435_000), (776_100, 1_435_100)])
    archive = shapefile_zip(tmp_path, gpd.GeoDataFrame(geometry=[square]), exclude=(".prj",))

    file = upload(client, "unknown.zip", archive.read_bytes()).json()
    (item,) = measurements(client, file["id"])["items"]

    assert file["status"] == "COMPLETED"
    assert file["crs"] is None
    assert item["measurement"]["status"] == "skipped"
    assert "Unknown CRS" in item["measurement"]["reason"]
    assert item["geometry_crs"] is None
    assert item["geometry"]["coordinates"][0][0] == [776_000, 1_435_000]


def test_unsupported_extension_returns_415(client: TestClient) -> None:
    assert_error(upload(client, "notes.txt", b"hello"), 415, "UNSUPPORTED_FILE_TYPE")


@pytest.mark.parametrize(
    ("name", "content"),
    [("fake.zip", b"not a zip"), ("broken.kml", b"<kml>"), ("empty.kml", b"")],
)
def test_invalid_content_returns_400_and_is_not_stored(
    client: TestClient, settings: Settings, name: str, content: bytes
) -> None:
    assert_error(upload(client, name, content), 400, "INVALID_FILE")

    assert client.get("/api/files/").json()["total"] == 0
    assert list(settings.upload_dir.iterdir()) == []


def test_zip_slip_upload_is_rejected(client: TestClient, tmp_path: Path) -> None:
    archive = zip_files(tmp_path / "evil.zip", [("../evil.shp", b"x")])

    error = assert_error(upload(client, "evil.zip", archive.read_bytes()), 400, "INVALID_FILE")

    assert "Unsafe path" in error["message"]


def test_oversized_upload_returns_413(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", max_upload_bytes=1024)
    with TestClient(create_app(settings)) as small_client:
        response = upload(small_client, "big.kml", b"x" * 100_000)

    assert_error(response, 413, "FILE_TOO_LARGE")


def test_missing_file_field_returns_validation_error(client: TestClient) -> None:
    assert_error(client.post("/api/files/"), 422, "VALIDATION_ERROR")


def test_unprocessable_archive_is_stored_as_failed(client: TestClient, tmp_path: Path) -> None:
    archive = zip_files(tmp_path / "docs.zip", [("readme.txt", b"no shapefile here")])

    error = assert_error(upload(client, "docs.zip", archive.read_bytes()), 422, "PROCESSING_FAILED")
    file_id = error["details"]["file_id"]

    record = client.get(f"/api/files/{file_id}/").json()
    assert record["status"] == "FAILED"
    assert "No .shp file found" in record["error_detail"]
    assert_error(client.get(f"/api/files/{file_id}/measurements/"), 409, "FILE_NOT_READY")


@pytest.mark.parametrize("missing", [".shx", ".dbf"])
def test_shapefile_missing_companion_fails(
    client: TestClient, tmp_path: Path, missing: str
) -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(*BENGALURU)], crs=4326)
    archive = shapefile_zip(tmp_path, gdf, exclude=(missing,))

    error = assert_error(upload(client, "x.zip", archive.read_bytes()), 422, "PROCESSING_FAILED")

    assert missing in error["message"]


def test_multiple_shapefiles_fail_with_list(client: TestClient, tmp_path: Path) -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(*BENGALURU)], crs=4326)
    parts = [
        part
        for name in ("roads", "parcels")
        for part in write_shapefile(gdf, tmp_path / "src", name).parent.iterdir()
    ]
    archive = zip_files(tmp_path / "both.zip", [(p.name, p) for p in set(parts)])

    error = assert_error(upload(client, "both.zip", archive.read_bytes()), 422, "PROCESSING_FAILED")

    assert "parcels.shp, roads.shp" in error["message"]


def test_list_files_newest_first(client: TestClient, survey_kml: bytes) -> None:
    first = upload(client, "first.kml", survey_kml).json()
    second = upload(client, "second.kml", survey_kml).json()

    listing = client.get("/api/files/", params={"limit": 1}).json()

    assert listing["total"] == 2
    assert [f["id"] for f in listing["items"]] == [second["id"]]
    assert first["id"] != second["id"]


def test_delete_file_removes_record_and_storage(
    client: TestClient, settings: Settings, uploaded_kml: dict[str, Any]
) -> None:
    file_id = uploaded_kml["id"]
    assert (settings.upload_dir / file_id).exists()

    response = client.delete(f"/api/files/{file_id}/")

    assert response.status_code == 204
    assert not (settings.upload_dir / file_id).exists()
    assert_error(client.get(f"/api/files/{file_id}/"), 404, "NOT_FOUND")
    assert_error(client.delete(f"/api/files/{file_id}/"), 404, "NOT_FOUND")


def test_empty_kml_completes_with_warning(client: TestClient) -> None:
    response = upload(client, "empty.kml", kml_document({}).encode())

    assert response.status_code == 201
    assert response.json()["feature_count"] == 0
    assert response.json()["warnings"] == ["The file contains no features."]


def test_unexpected_error_returns_500_and_marks_file_failed(
    settings: Settings, survey_kml: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_path: Path) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.services.reader.read_kml", explode)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = upload(client, "survey.kml", survey_kml)
        (record,) = client.get("/api/files/").json()["items"]

    assert_error(response, 500, "INTERNAL_ERROR")
    assert "boom" not in response.text
    assert record["status"] == "FAILED"
    assert record["error_detail"] == "An unexpected error occurred while processing the file."
