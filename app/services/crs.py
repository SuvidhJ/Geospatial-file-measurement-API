"""CRS identification and selection of the CRS each feature is measured in."""

import math
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely import transform
from shapely.geometry.base import BaseGeometry

WGS84 = CRS.from_epsg(4326)

# UTM is only defined between 80°S and 84°N; beyond that UPS or another projection is needed.
UTM_MIN_LATITUDE = -80.0
UTM_MAX_LATITUDE = 84.0
# UTM scale error grows with distance from the zone's central meridian:
#   k ≈ 0.9996 · (1 + (Δλ·cos φ)² / 2)
# At 4° from the meridian the area error reaches ≈0.4% at the equator; beyond that, features
# are measured in an equal-area projection instead of accepting a growing error.
MAX_DEGREES_FROM_CENTRAL_MERIDIAN = 4.0


class MeasurementMethod(StrEnum):
    NATIVE = "native"
    UTM = "projected-utm"
    LAEA_FALLBACK = "projected-laea-fallback"


@dataclass(frozen=True)
class MeasurementCRS:
    crs: CRS
    label: str
    method: MeasurementMethod
    to_metres: float = 1.0
    note: str | None = None


@lru_cache(maxsize=128)
def crs_label(crs: CRS | None) -> str | None:
    """A readable identifier: 'EPSG:xxxx' when one can be matched, else the CRS name."""
    if crs is None:
        return None
    # ESRI-flavoured .prj files often only match their EPSG code at reduced confidence.
    epsg = crs.to_epsg() or crs.to_epsg(min_confidence=20)
    return f"EPSG:{epsg}" if epsg else crs.name


@lru_cache(maxsize=128)
def get_transformer(source: CRS, target: CRS) -> Transformer:
    # always_xy: EPSG:4326 is officially (lat, lon), but shapely and GeoJSON use (x=lon, y=lat).
    return Transformer.from_crs(source, target, always_xy=True)


def reproject(geometry: BaseGeometry, source: CRS, target: CRS) -> BaseGeometry:
    if source == target:
        return geometry
    return transform(geometry, get_transformer(source, target).transform, interleaved=False)


def to_wgs84(geometry: BaseGeometry, source: CRS) -> BaseGeometry:
    return reproject(geometry, source, WGS84)


def choose_measurement_crs(source: CRS, geometry_wgs84: BaseGeometry) -> MeasurementCRS:
    """Pick the CRS a single feature is measured in.

    - A suitable projected source CRS is used as-is: it is what the surveyor chose.
    - Otherwise use the UTM zone of the feature's centroid: an EPSG-coded, widely
      recognised projection whose area error stays under ~0.2% inside its own zone.
    - Fall back to a Lambert Azimuthal Equal-Area projection centred on the feature when
      it is outside UTM's latitude range or too far from the zone's central meridian.
    """
    if source.is_projected and not _is_mercator(source):
        return MeasurementCRS(
            crs=source,
            label=crs_label(source) or source.name,
            method=MeasurementMethod.NATIVE,
            to_metres=source.axis_info[0].unit_conversion_factor,
        )

    note = None
    if source.is_projected:
        note = (
            f"Source CRS {crs_label(source)} is a Mercator projection, which inflates "
            "areas away from the equator; the feature was reprojected to measure it."
        )

    centroid = geometry_wgs84.centroid
    min_lon, min_lat, max_lon, max_lat = geometry_wgs84.bounds
    if min_lat < UTM_MIN_LATITUDE or max_lat > UTM_MAX_LATITUDE:
        return _laea(centroid.x, centroid.y, "Feature extends beyond UTM's 80°S-84°N limits.")

    zone = utm_zone(centroid.x)
    central_meridian = zone * 6 - 183
    if max(abs(min_lon - central_meridian), abs(max_lon - central_meridian)) > (
        MAX_DEGREES_FROM_CENTRAL_MERIDIAN
    ):
        return _laea(
            centroid.x,
            centroid.y,
            f"Feature reaches more than {MAX_DEGREES_FROM_CENTRAL_MERIDIAN:g}° from the "
            f"central meridian of UTM zone {zone}, where UTM scale error becomes significant.",
        )

    epsg = (32600 if centroid.y >= 0 else 32700) + zone
    return MeasurementCRS(
        crs=_crs_from_epsg(epsg), label=f"EPSG:{epsg}", method=MeasurementMethod.UTM, note=note
    )


@lru_cache(maxsize=128)
def _crs_from_epsg(code: int) -> CRS:
    return CRS.from_epsg(code)


def utm_zone(longitude: float) -> int:
    """UTM zones are 6° wide, numbered 1-60 eastwards from 180°W."""
    return min(math.floor((longitude + 180) / 6) + 1, 60)


def _laea(lon: float, lat: float, reason: str) -> MeasurementCRS:
    # Equal-area at any extent, so polygon areas stay correct however large the feature is.
    proj = f"+proj=laea +lat_0={lat:.6f} +lon_0={lon:.6f} +datum=WGS84 +units=m +no_defs"
    return MeasurementCRS(
        crs=CRS.from_proj4(proj),
        label=proj,
        method=MeasurementMethod.LAEA_FALLBACK,
        note=f"Measured in a local Lambert Azimuthal Equal-Area projection: {reason}",
    )


def _is_mercator(crs: CRS) -> bool:
    """True for (Pseudo-)Mercator, e.g. EPSG:3857; Transverse/Oblique Mercator are fine."""
    operation = crs.coordinate_operation
    method = operation.method_name.lower() if operation else ""
    return method.startswith("mercator") or "pseudo mercator" in method
