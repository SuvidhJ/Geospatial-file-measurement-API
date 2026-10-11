"""Read Shapefile/KML into a GeoDataFrame and normalise each feature."""

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyogrio.errors import DataLayerError, DataSourceError
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.errors import DatasetError
from app.services.crs import WGS84
from app.services.measure import POLYGONAL_TYPES

KML_LAYER_PROPERTY = "kml_layer"
# LIBKML exposes these rendering hints as columns with sentinel defaults (e.g. -1);
# they describe how Google Earth draws a placemark, not the feature itself.
KML_RENDERING_FIELDS = ["tessellate", "extrude", "visibility", "drawOrder", "icon", "altitudeMode"]


@dataclass
class Dataset:
    frame: gpd.GeoDataFrame
    crs: CRS | None
    has_source_fids: bool
    crs_assumed: bool = False
    warnings: list[str] = field(default_factory=list)
    # True when a null attribute means "this feature has no such field" rather than an
    # empty value, as for KML layers stacked into one frame.
    drop_null_properties: bool = False


@dataclass
class SourceFeature:
    index: int
    source_fid: int | None
    geometry: BaseGeometry | None
    properties: dict[str, Any]


@dataclass
class PreparedGeometry:
    geometry: BaseGeometry | None
    repaired: bool = False
    warnings: list[str] = field(default_factory=list)


def read_shapefile(path: Path) -> Dataset:
    try:
        frame = pyogrio.read_dataframe(path, fid_as_index=True)
    except (DataSourceError, DataLayerError) as exc:
        raise DatasetError(f"Could not read the Shapefile: {exc}") from None

    if frame.crs is not None:
        return Dataset(frame=frame, crs=CRS.from_user_input(frame.crs), has_source_fids=True)
    return _resolve_missing_crs(frame)


def _resolve_missing_crs(frame: gpd.GeoDataFrame) -> Dataset:
    """No .prj: assume WGS84 only when every coordinate is a plausible lon/lat; never guess."""
    if _within_lonlat_bounds(frame):
        return Dataset(
            frame=frame.set_crs(WGS84),
            crs=WGS84,
            has_source_fids=True,
            crs_assumed=True,
            warnings=[
                "The Shapefile has no .prj file. All coordinates are within longitude/latitude "
                "bounds, so EPSG:4326 was assumed."
            ],
        )
    return Dataset(
        frame=frame,
        crs=None,
        has_source_fids=True,
        warnings=[
            "The Shapefile has no .prj file and its coordinates are not longitude/latitude, "
            "so the CRS is unknown and features cannot be measured."
        ],
    )


def _within_lonlat_bounds(frame: gpd.GeoDataFrame) -> bool:
    min_x, min_y, max_x, max_y = frame.total_bounds
    if np.isnan([min_x, min_y, max_x, max_y]).any():
        return False
    return min_x >= -180 and max_x <= 180 and min_y >= -90 and max_y <= 90


def read_kml(path: Path) -> Dataset:
    """Read every KML folder/document layer and stack them, tagging each feature's layer."""
    try:
        layer_names = [name for name, _ in pyogrio.list_layers(path)]
        frames = [_read_kml_layer(path, name) for name in layer_names]
    except (DataSourceError, DataLayerError) as exc:
        raise DatasetError(f"Could not read the KML file: {exc}") from None

    if not frames:
        empty = gpd.GeoDataFrame(geometry=[], crs=WGS84)
        return Dataset(frame=empty, crs=WGS84, has_source_fids=False)
    # KML coordinates are always WGS84 lon/lat by specification (OGC KML 2.2).
    # Stacking layers unions their columns, so each placemark picks up nulls for fields
    # that only exist in other folders; drop_null_properties removes those again.
    combined = pd.concat(frames, ignore_index=True)
    return Dataset(
        frame=gpd.GeoDataFrame(combined, geometry="geometry", crs=WGS84),
        crs=WGS84,
        has_source_fids=False,
        drop_null_properties=True,
    )


def _read_kml_layer(path: Path, layer: str) -> gpd.GeoDataFrame:
    frame = pyogrio.read_dataframe(path, layer=layer)
    frame = frame.drop(columns=[c for c in KML_RENDERING_FIELDS if c in frame.columns])
    empty_columns = [c for c in frame.columns if c != frame.geometry.name and frame[c].isna().all()]
    frame = frame.drop(columns=empty_columns)
    frame[KML_LAYER_PROPERTY] = layer
    return frame


def iter_features(dataset: Dataset) -> Iterator[SourceFeature]:
    frame = dataset.frame
    attributes = frame.drop(columns=frame.geometry.name).to_dict("records")
    for index, (fid, geometry, attributes_row) in enumerate(
        zip(frame.index, frame.geometry, attributes, strict=True)
    ):
        properties = {str(key): json_safe(value) for key, value in attributes_row.items()}
        if dataset.drop_null_properties:
            properties = {key: value for key, value in properties.items() if value is not None}
        yield SourceFeature(
            index=index,
            source_fid=int(fid) if dataset.has_source_fids else None,
            geometry=geometry,
            properties=properties,
        )


def prepare_geometry(geometry: BaseGeometry | None) -> PreparedGeometry:
    """Make a geometry safe to measure: 2D and valid."""
    if geometry is None or geometry.is_empty:
        return PreparedGeometry(geometry=geometry)

    warnings = []
    if shapely.has_z(geometry):
        geometry = shapely.force_2d(geometry)
        warnings.append("Z values were dropped; measurements are planimetric (2D).")

    if geometry.is_valid:
        return PreparedGeometry(geometry=geometry, warnings=warnings)

    reason = shapely.is_valid_reason(geometry)
    if geometry.geom_type in POLYGONAL_TYPES:
        # "structure" keeps the result polygonal: the default "linework" method can return a
        # GeometryCollection (polygons plus stray lines), which would lose the area.
        repaired = shapely.make_valid(geometry, method="structure", keep_collapsed=False)
    else:
        repaired = shapely.make_valid(geometry)
    warnings.append(f"Invalid geometry was repaired ({reason}).")
    return PreparedGeometry(geometry=repaired, repaired=True, warnings=warnings)


def json_safe(value: Any) -> Any:
    """Convert a pandas/numpy cell into a value the JSON encoder accepts."""
    if isinstance(value, np.datetime64):
        value = pd.Timestamp(value)
    elif isinstance(value, np.generic):
        value = value.item()

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)
