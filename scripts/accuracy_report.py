"""Compare this service's area measurement with common shortcuts, at sites around the world.

Each site gets a polygon whose true (geodesic) area is known, built by walking geodesics on
the WGS84 ellipsoid. It is then measured by:

- this service's strategy (`measure()`: per-feature UTM, LAEA fallback),
- planar area in Web Mercator (EPSG:3857), a common mistake with web-map data,
- one fixed projected CRS for everything (UTM 43N, Bengaluru's zone),
- "degrees x 111.32 km", treating lon/lat degrees as fixed-size squares.

Every number in the README's accuracy table comes from running this script:

    python -m scripts.accuracy_report
"""

from pyproj import CRS
from shapely.geometry import Polygon, box

from app.services.crs import WGS84, reproject
from app.services.measure import geodesic_area_perimeter, measure
from tests.factories import geodesic_square

METRES_PER_DEGREE_AT_EQUATOR = 111_320
FIXED_CRS = CRS.from_epsg(32643)
WEB_MERCATOR = CRS.from_epsg(3857)

SITES: list[tuple[str, Polygon]] = [
    ("Equator, on a central meridian (3°E)", geodesic_square(3.0, 0.0, 1000)),
    ("Equator, 2.9° from the central meridian", geodesic_square(5.9, 0.0, 1000)),
    ("Bengaluru (77.59°E, 12.97°N)", geodesic_square(77.5946, 12.9716, 1000)),
    ("Oslo (10.75°E, 59.91°N)", geodesic_square(10.75, 59.91, 1000)),
    ("Ushuaia (68.30°W, 54.80°S)", geodesic_square(-68.30, -54.80, 1000)),
    ("Svalbard, 85°N (beyond UTM)", geodesic_square(15.0, 85.0, 1000)),
    ("Wide feature, 8.5° x 1° near India", box(72.5, 12.0, 81.0, 13.0)),
]


def pct_error(value: float, truth: float) -> str:
    return f"{(value - truth) / truth * 100:+.3f}%"


def main() -> None:
    print(
        "| Site | Measured in | This service | Web Mercator | Fixed UTM 43N | Degrees x 111.32 km |"
    )
    print("|---|---|---|---|---|---|")
    for name, polygon in SITES:
        truth, _ = geodesic_area_perimeter(polygon)
        ours = measure(polygon, polygon, WGS84, warning_threshold_pct=0.5)
        assert ours.area_m2 is not None
        mercator = reproject(polygon, WGS84, WEB_MERCATOR).area
        fixed = reproject(polygon, WGS84, FIXED_CRS).area
        degrees = polygon.area * METRES_PER_DEGREE_AT_EQUATOR**2
        crs = ours.measurement_crs if ours.method == "projected-utm" else "local LAEA"
        print(
            f"| {name} | {crs} | {pct_error(ours.area_m2, truth)} | "
            f"{pct_error(mercator, truth)} | {pct_error(fixed, truth)} | "
            f"{pct_error(degrees, truth)} |"
        )


if __name__ == "__main__":
    main()
