"""Generate the files in sample_data/.

Shapes are built by walking geodesics on the WGS84 ellipsoid, so their true size is known
by construction and the API's output can be checked by hand:

    python -m scripts.make_sample_data
"""

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from tests.factories import (
    GEOD,
    geodesic_square,
    kml_document,
    kml_line,
    kml_point,
    kml_polygon,
    placemark,
    zip_files,
)

OUT = Path("sample_data")
CUBBON_PARK = (77.5920, 12.9763)
WHITEFIELD = (77.7500, 12.9698)
ELECTRONIC_CITY = (77.6700, 12.8450)


def offset(point: tuple[float, float], east_m: float, north_m: float) -> tuple[float, float]:
    lon, lat, _ = GEOD.fwd(*point, 90, east_m)
    lon, lat, _ = GEOD.fwd(lon, lat, 0, north_m)
    return lon, lat


def parcels() -> gpd.GeoDataFrame:
    courtyard_outer = geodesic_square(*WHITEFIELD, side_m=200)
    courtyard_hole = geodesic_square(*offset(WHITEFIELD, 75, 75), side_m=50)
    return gpd.GeoDataFrame(
        {
            "plot_id": ["P-001", "P-002", "P-003"],
            "use": ["park", "campus", "industrial"],
            "expected": ["1 ha", "3.75 ha (4 ha minus 0.25 ha hole)", "100 ha"],
        },
        geometry=[
            geodesic_square(*CUBBON_PARK, side_m=100),
            Polygon(courtyard_outer.exterior.coords, [courtyard_hole.exterior.coords]),
            geodesic_square(*ELECTRONIC_CITY, side_m=1000),
        ],
        crs=4326,
    )


def write_shapefile_zip(gdf: gpd.GeoDataFrame, name: str) -> None:
    folder = OUT / f"_{name}"
    folder.mkdir(parents=True, exist_ok=True)
    gdf.to_file(folder / f"{name}.shp", engine="pyogrio")
    zip_files(OUT / f"{name}.zip", [(f"{name}/{p.name}", p) for p in sorted(folder.iterdir())])
    for part in folder.iterdir():
        part.unlink()
    folder.rmdir()


def survey_kml() -> str:
    road_end = GEOD.fwd(*CUBBON_PARK, 90, 2000)[:2]
    return kml_document(
        {
            "Site boundary": [
                placemark(
                    "Survey block (1 km x 1 km)",
                    kml_polygon(geodesic_square(*ELECTRONIC_CITY, side_m=1000).exterior.coords),
                    {"expected": "100 ha"},
                )
            ],
            "Haul roads": [
                placemark(
                    "Haul road (2 km due east)",
                    kml_line([(*CUBBON_PARK, 920.0), (*road_end, 915.0)]),
                    {"expected": "2.000 km", "surface": "gravel"},
                )
            ],
            "Ground control points": [
                placemark(f"GCP-{i}", kml_point(*offset(CUBBON_PARK, 500 * i, 0)))
                for i in range(1, 4)
            ],
        }
    )


def main() -> None:
    OUT.mkdir(exist_ok=True)
    write_shapefile_zip(parcels(), "bengaluru_parcels")
    write_shapefile_zip(parcels().to_crs(32643), "bengaluru_parcels_utm43n")
    (OUT / "bengaluru_survey.kml").write_text(survey_kml(), encoding="utf-8")
    print("Wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
