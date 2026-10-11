"""Generate the files in sample_data/.

Shapes are built by walking geodesics on the WGS84 ellipsoid, so their true size is known
by construction and the API's output can be checked by hand:

    python -m scripts.make_sample_data
"""

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, Polygon

from tests.factories import (
    GEOD,
    cell_centres,
    geodesic_square,
    kml_document,
    kml_line,
    kml_point,
    kml_polygon,
    placemark,
    write_dem,
    zip_files,
)

OUT = Path("sample_data")
CUBBON_PARK = (77.5920, 12.9763)
WHITEFIELD = (77.7500, 12.9698)
ELECTRONIC_CITY = (77.6700, 12.8450)


@dataclass(frozen=True)
class Cone:
    """A cone (or, with negative height, a pit) on flat ground; its volume is πR²h/3."""

    east_m: float  # offset from the yard centre
    radius_m: float
    height_m: float
    toe_radius_m: float  # radius of the surveyed toe polygon, beyond the cone's edge


# Stockpile yard: a 200 m x 200 m DEM at 0.5 m resolution in UTM 43N, on flat ground at 905 m.
UTM_43N = "EPSG:32643"
YARD_CELL, YARD_SIZE, YARD_GROUND = 0.5, 400, 905.0
STOCKPILE = Cone(east_m=-40, radius_m=40, height_m=12, toe_radius_m=45)
PIT = Cone(east_m=60, radius_m=15, height_m=-4, toe_radius_m=20)


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


def yard_centre() -> tuple[float, float]:
    to_utm = Transformer.from_crs(4326, UTM_43N, always_xy=True)
    x, y = to_utm.transform(*ELECTRONIC_CITY)
    return round(x), round(y)


def stockpile_dem(centre: tuple[float, float]) -> np.ndarray:
    left, top = centre[0] - 100, centre[1] + 100
    xs, ys = cell_centres(left, top, YARD_CELL, YARD_SIZE)
    elevations = np.full(xs.shape, YARD_GROUND)
    for cone in (STOCKPILE, PIT):
        distance = np.hypot(xs - (centre[0] + cone.east_m), ys - centre[1])
        elevations += cone.height_m * np.clip(1 - distance / cone.radius_m, 0, None)
    return elevations


def stockpile_kml(centre: tuple[float, float]) -> str:
    to_wgs84 = Transformer.from_crs(UTM_43N, 4326, always_xy=True)

    def toe(cone: Cone) -> str:
        circle = Point(centre[0] + cone.east_m, centre[1]).buffer(cone.toe_radius_m, quad_segs=32)
        return kml_polygon(to_wgs84.transform(x, y) for x, y in circle.exterior.coords)

    return kml_document(
        {
            "Stockpiles": [
                placemark(
                    "Aggregate stockpile",
                    toe(STOCKPILE),
                    {"expected_cut_m3": "20106 (cone, R 40 m, h 12 m)"},
                ),
                placemark(
                    "Excavation pit", toe(PIT), {"expected_fill_m3": "942 (cone, R 15 m, h 4 m)"}
                ),
            ]
        }
    )


def main() -> None:
    OUT.mkdir(exist_ok=True)
    write_shapefile_zip(parcels(), "bengaluru_parcels")
    write_shapefile_zip(parcels().to_crs(32643), "bengaluru_parcels_utm43n")
    (OUT / "bengaluru_survey.kml").write_text(survey_kml(), encoding="utf-8")
    zip_files(OUT / "bengaluru_survey.kmz", [("doc.kml", survey_kml().encode())])
    centre = yard_centre()
    (OUT / "stockpile_yard.kml").write_text(stockpile_kml(centre), encoding="utf-8")
    write_dem(
        OUT / "stockpile_yard_dem.tif",
        stockpile_dem(centre),
        left=centre[0] - 100,
        top=centre[1] + 100,
        cell_size=YARD_CELL,
        crs=UTM_43N,
    )
    print("Wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
