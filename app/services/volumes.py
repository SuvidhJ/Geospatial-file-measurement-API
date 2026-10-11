"""Stockpile volume and 3D surface area of polygon features from a DEM (GeoTIFF).

For each polygon, the DEM cells whose centres fall inside it are selected and compared with a
horizontal base plane whose elevation is sampled from the DEM along the polygon's boundary
(the stockpile toe):

- cut volume  = Σ max(z - base, 0) · cell area   (material above the base)
- fill volume = Σ max(base - z, 0) · cell area   (void below the base, e.g. a pit)
- surface area = Σ cell area · √(1 + (∂z/∂x)² + (∂z/∂y)²)
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyproj import CRS
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask
from rasterio.io import DatasetReader
from rasterio.transform import rowcol
from rasterio.windows import Window
from shapely.geometry.base import BaseGeometry

from app.errors import InvalidFileError
from app.services.crs import WGS84, crs_label, reproject

TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")  # TIFF and BigTIFF
FULL_COVERAGE_PCT = 99.9


class BaseMethod(StrEnum):
    BOUNDARY_MEAN = "boundary-mean"
    BOUNDARY_MIN = "boundary-min"


@dataclass(frozen=True)
class DemInfo:
    crs: str
    cell_size_m: tuple[float, float]
    width: int
    height: int


@dataclass
class FeatureVolume:
    index: int
    measured: bool
    reason: str | None = None
    base_elevation_m: float | None = None
    cut_volume_m3: float | None = None
    fill_volume_m3: float | None = None
    net_volume_m3: float | None = None
    surface_area_m2: float | None = None
    planimetric_area_m2: float | None = None
    dem_coverage_pct: float | None = None
    warnings: list[str] = field(default_factory=list)


def compute_volumes(
    dem_path: Path,
    polygons_wgs84: list[tuple[int, BaseGeometry]],
    base_method: BaseMethod,
    max_cells: int,
) -> tuple[DemInfo, list[FeatureVolume]]:
    _check_signature(dem_path)
    try:
        # Restricting GDAL to the GeoTIFF driver stops a crafted upload (e.g. a VRT) from
        # making GDAL read other files on the server.
        with rasterio.open(dem_path, driver="GTiff") as dem:
            dem_crs = _check_dem(dem)
            info = DemInfo(
                crs=crs_label(dem_crs) or dem_crs.name,
                cell_size_m=(float(dem.res[0]), float(dem.res[1])),
                width=dem.width,
                height=dem.height,
            )
            results = [
                _feature_volume(dem, dem_crs, index, polygon, base_method, max_cells)
                for index, polygon in polygons_wgs84
            ]
    except RasterioIOError as exc:
        raise InvalidFileError(f"The DEM could not be read: {exc}") from None
    return info, results


def _check_signature(path: Path) -> None:
    with path.open("rb") as file:
        if file.read(4) not in TIFF_SIGNATURES:
            raise InvalidFileError("The DEM must be a GeoTIFF (.tif) file.")


def _check_dem(dem: DatasetReader) -> CRS:
    if dem.crs is None:
        raise InvalidFileError("The DEM has no CRS; export it as a georeferenced GeoTIFF.")
    crs = CRS.from_wkt(dem.crs.to_wkt())
    if not crs.is_projected or crs.axis_info[0].unit_conversion_factor != 1.0:
        raise InvalidFileError(
            f"The DEM's CRS ({crs_label(crs)}) must be projected with metre units, e.g. UTM, "
            "so that cell sizes and elevations share one unit."
        )
    if not dem.transform.is_rectilinear:
        raise InvalidFileError("Rotated DEM grids are not supported.")
    return crs


def _feature_volume(
    dem: DatasetReader,
    dem_crs: CRS,
    index: int,
    polygon_wgs84: BaseGeometry,
    base_method: BaseMethod,
    max_cells: int,
) -> FeatureVolume:
    polygon = reproject(polygon_wgs84, WGS84, dem_crs)
    window = _window(dem, polygon)
    if window is None:
        return FeatureVolume(index, measured=False, reason="The polygon is outside the DEM.")
    if window.width * window.height > max_cells:
        return FeatureVolume(
            index,
            measured=False,
            reason=f"The polygon covers more than {max_cells} DEM cells.",
        )

    elevations = np.ma.masked_invalid(dem.read(1, window=window, masked=True).astype("float64"))
    transform = dem.window_transform(window)
    inside = geometry_mask([polygon], out_shape=elevations.shape, transform=transform, invert=True)
    if not inside.any():
        return FeatureVolume(
            index, measured=False, reason="The polygon is smaller than one DEM cell."
        )

    base = _base_elevation(polygon, elevations, transform, base_method)
    if base is None:
        return FeatureVolume(
            index, measured=False, reason="The DEM has no data along the polygon boundary."
        )

    cell_width, cell_height = dem.res
    cell_area = cell_width * cell_height
    valid = inside & ~np.ma.getmaskarray(elevations)
    heights = elevations.filled(np.nan)[valid] - base
    cut = float(np.clip(heights, 0, None).sum() * cell_area)
    fill = float(np.clip(-heights, 0, None).sum() * cell_area)

    slope_y, slope_x = np.gradient(elevations.filled(np.nan), cell_height, cell_width)
    slope_factor = np.sqrt(1 + slope_x**2 + slope_y**2)[valid]
    # Cells next to nodata have no gradient; count them as flat rather than dropping them.
    surface = float(np.where(np.isnan(slope_factor), 1.0, slope_factor).sum() * cell_area)

    coverage = float(valid.sum() / inside.sum() * 100)
    warnings = []
    if coverage < FULL_COVERAGE_PCT:
        warnings.append(
            f"The DEM has data for only {coverage:.1f}% of the polygon; "
            "volumes and surface area cover that part only."
        )
    return FeatureVolume(
        index,
        measured=True,
        base_elevation_m=base,
        cut_volume_m3=cut,
        fill_volume_m3=fill,
        net_volume_m3=cut - fill,
        surface_area_m2=surface,
        planimetric_area_m2=float(valid.sum() * cell_area),
        dem_coverage_pct=coverage,
        warnings=warnings,
    )


def _window(dem: DatasetReader, polygon: BaseGeometry) -> Window | None:
    """The DEM window covering the polygon, padded by one cell, or None if they don't overlap."""
    min_x, min_y, max_x, max_y = polygon.bounds
    row_top, col_left = dem.index(min_x, max_y)
    row_bottom, col_right = dem.index(max_x, min_y)
    row_start, row_stop = max(row_top - 1, 0), min(row_bottom + 2, dem.height)
    col_start, col_stop = max(col_left - 1, 0), min(col_right + 2, dem.width)
    if row_start >= row_stop or col_start >= col_stop:
        return None
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def _base_elevation(
    polygon: BaseGeometry,
    elevations: np.ma.MaskedArray,
    transform: rasterio.Affine,
    base_method: BaseMethod,
) -> float | None:
    """Sample the DEM along the polygon's outer boundary, once per cell width."""
    spacing = abs(transform.a)
    points = [
        ring.interpolate(distance)
        for ring in (part.exterior for part in shapely.get_parts(polygon))
        for distance in np.arange(0, ring.length, spacing)
    ]
    rows, cols = (
        np.asarray(index)
        for index in rowcol(transform, [p.x for p in points], [p.y for p in points])
    )
    on_grid = (
        (rows >= 0) & (rows < elevations.shape[0]) & (cols >= 0) & (cols < elevations.shape[1])
    )
    samples = elevations[rows[on_grid], cols[on_grid]].compressed()
    if samples.size == 0:
        return None
    if base_method is BaseMethod.BOUNDARY_MIN:
        return float(samples.min())
    return float(samples.mean())
