import datetime as dt
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from app.errors import DatasetError
from app.services import reader
from app.services.crs import crs_label
from tests.factories import (
    kml_document,
    kml_line,
    kml_point,
    kml_polygon,
    placemark,
    write_shapefile,
)

BENGALURU = (77.5946, 12.9716)


def test_shapefile_with_prj_keeps_crs_and_fids(tmp_path: Path) -> None:
    gdf = gpd.GeoDataFrame({"name": ["a", "b"]}, geometry=[Point(*BENGALURU)] * 2, crs=32643)
    shp = write_shapefile(gdf, tmp_path)

    dataset = reader.read_shapefile(shp)
    features = list(reader.iter_features(dataset))

    assert crs_label(dataset.crs) == "EPSG:32643"
    assert dataset.crs_assumed is False
    assert [f.source_fid for f in features] == [0, 1]
    assert features[1].properties == {"name": "b"}


def test_missing_prj_with_lonlat_coordinates_assumes_wgs84(tmp_path: Path) -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(*BENGALURU)], crs=4326)
    shp = write_shapefile(gdf, tmp_path)
    shp.with_suffix(".prj").unlink()

    dataset = reader.read_shapefile(shp)

    assert crs_label(dataset.crs) == "EPSG:4326"
    assert dataset.crs_assumed is True
    assert "EPSG:4326 was assumed" in dataset.warnings[0]


def test_missing_prj_with_projected_coordinates_leaves_crs_unknown(tmp_path: Path) -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(776_000, 1_435_000)], crs=32643)
    shp = write_shapefile(gdf, tmp_path)
    shp.with_suffix(".prj").unlink()

    dataset = reader.read_shapefile(shp)

    assert dataset.crs is None
    assert dataset.crs_assumed is False
    assert "CRS is unknown" in dataset.warnings[0]


def test_corrupt_shapefile_raises_dataset_error(tmp_path: Path) -> None:
    shp = write_shapefile(gpd.GeoDataFrame(geometry=[Point(0, 0)], crs=4326), tmp_path)
    shp.write_bytes(b"definitely not a shapefile")

    with pytest.raises(DatasetError, match="Could not read the Shapefile"):
        reader.read_shapefile(shp)


def test_feature_properties_are_json_safe() -> None:
    gdf = gpd.GeoDataFrame(
        {
            "surveyed": pd.to_datetime(["2024-03-01"]),
            "count": np.array([3], dtype="int32"),
            "height": [float("nan")],
        },
        geometry=[Point(*BENGALURU)],
        crs=4326,
    )
    dataset = reader.Dataset(frame=gdf, crs=CRS.from_epsg(4326), has_source_fids=False)

    (feature,) = reader.iter_features(dataset)

    assert feature.properties == {"surveyed": "2024-03-01T00:00:00", "count": 3, "height": None}


def test_kml_reads_every_folder_and_tags_layer(tmp_path: Path) -> None:
    path = tmp_path / "survey.kml"
    path.write_text(
        kml_document(
            {
                "Roads": [
                    placemark(
                        "MG Road",
                        kml_line([(77.60, 12.97, 900), (77.61, 12.97, 905)]),
                        {"lanes": "4"},
                    )
                ],
                "Parcels": [
                    placemark(
                        "Plot 1",
                        kml_polygon([(77.59, 12.97), (77.6, 12.97), (77.6, 12.98), (77.59, 12.97)]),
                    ),
                    placemark("Benchmark", kml_point(*BENGALURU)),
                ],
            }
        )
    )

    dataset = reader.read_kml(path)
    features = list(reader.iter_features(dataset))

    assert crs_label(dataset.crs) == "EPSG:4326"
    assert [f.properties["kml_layer"] for f in features] == ["Roads", "Parcels", "Parcels"]
    assert [f.geometry.geom_type for f in features] == ["LineString", "Polygon", "Point"]
    assert features[0].properties["Name"] == "MG Road"
    assert features[0].properties["lanes"] == "4"
    assert all(f.source_fid is None for f in features)
    assert not {"tessellate", "visibility", "timestamp"} & set(features[0].properties)


def test_kml_without_placemarks_has_no_features(tmp_path: Path) -> None:
    path = tmp_path / "empty.kml"
    path.write_text(kml_document({}))

    dataset = reader.read_kml(path)

    assert list(reader.iter_features(dataset)) == []


def test_prepare_geometry_drops_z_values() -> None:
    prepared = reader.prepare_geometry(LineString([(0, 0, 10), (1, 1, 20)]))

    assert not prepared.geometry.has_z
    assert "Z values were dropped" in prepared.warnings[0]


def test_prepare_geometry_repairs_bow_tie_into_multipolygon() -> None:
    bow_tie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    assert not bow_tie.is_valid

    prepared = reader.prepare_geometry(bow_tie)

    assert prepared.repaired is True
    assert isinstance(prepared.geometry, MultiPolygon)
    assert prepared.geometry.is_valid
    assert math.isclose(prepared.geometry.area, 0.5)
    assert "Self-intersection" in prepared.warnings[0]


def test_prepare_geometry_leaves_empty_and_null_alone() -> None:
    assert reader.prepare_geometry(None).geometry is None
    assert reader.prepare_geometry(Polygon()).geometry.is_empty


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (np.int64(7), 7),
        (np.float32(1.5), 1.5),
        (float("nan"), None),
        (pd.NA, None),
        (pd.NaT, None),
        (pd.Timestamp("2024-01-02T03:04:05"), "2024-01-02T03:04:05"),
        (dt.date(2024, 1, 2), "2024-01-02"),
        (np.bool_(True), True),
        ("text", "text"),
        (None, None),
    ],
)
def test_json_safe(value: object, expected: object) -> None:
    assert reader.json_safe(value) == expected


def test_crs_label_matches_esri_flavoured_wkt() -> None:
    esri_wkt = CRS.from_epsg(32643).to_wkt("WKT1_ESRI")

    assert crs_label(CRS.from_wkt(esri_wkt)) == "EPSG:32643"
