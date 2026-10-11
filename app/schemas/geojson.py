"""Export of a file's features and measurements as an RFC 7946 GeoJSON FeatureCollection."""

from typing import Any

from app.models import Feature, UploadedFile
from app.schemas.measurements import FeatureMeasurement

GEOJSON_MEDIA_TYPE = "application/geo+json"


def feature_collection(file: UploadedFile, features: list[Feature]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        # "name" is a foreign member (allowed by RFC 7946); QGIS uses it as the layer name.
        "name": file.filename,
        "features": [_geojson_feature(feature) for feature in features],
    }


def _geojson_feature(feature: Feature) -> dict[str, Any]:
    item = FeatureMeasurement.from_feature(feature, include_geometry=True)
    measurement = item.measurement
    geodesic = measurement.geodesic
    return {
        "type": "Feature",
        "id": item.index,
        # GeoJSON coordinates must be WGS84; a geometry whose CRS is unknown cannot be placed
        # on a map, so it is exported without one rather than at a wrong location.
        "geometry": item.geometry if item.geometry_crs == "EPSG:4326" else None,
        "properties": {
            "index": item.index,
            "source_fid": item.source_fid,
            "geometry_type": item.geometry_type,
            "repaired": item.repaired,
            "status": measurement.status,
            "reason": measurement.reason,
            "area_m2": measurement.area_m2,
            "area_ha": measurement.area_ha,
            "perimeter_m": measurement.perimeter_m,
            "length_m": measurement.length_m,
            "length_km": measurement.length_km,
            "measurement_crs": measurement.measurement_crs,
            "method": measurement.method,
            "geodesic_area_m2": geodesic.area_m2 if geodesic else None,
            "geodesic_length_m": geodesic.length_m if geodesic else None,
            "difference_pct": measurement.difference_pct,
            "warnings": measurement.warnings,
            "attributes": item.properties,
        },
    }
