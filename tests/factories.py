"""Builders for test inputs. Every fixture file is generated, so tests document their data."""

import zipfile
from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd
from pyproj import Geod
from shapely.geometry import Polygon

GEOD = Geod(ellps="WGS84")


def write_shapefile(gdf: gpd.GeoDataFrame, directory: Path, name: str = "data") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.shp"
    gdf.to_file(path, engine="pyogrio")
    return path


def zip_files(zip_path: Path, entries: Iterable[tuple[str, Path | bytes]]) -> Path:
    """Write a zip from (archive name, file path or raw bytes) pairs."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in entries:
            if isinstance(content, Path):
                zf.write(content, arcname)
            else:
                zf.writestr(arcname, content)
    return zip_path


def shapefile_zip(
    tmp_path: Path,
    gdf: gpd.GeoDataFrame,
    *,
    name: str = "data",
    folder: str = "",
    exclude: tuple[str, ...] = (),
) -> Path:
    """Write gdf as a Shapefile and zip its parts, optionally nested or with parts missing."""
    shp = write_shapefile(gdf, tmp_path / f"src_{name}", name)
    parts = [p for p in shp.parent.iterdir() if p.suffix.lower() not in exclude]
    prefix = f"{folder}/" if folder else ""
    return zip_files(tmp_path / f"{name}.zip", [(f"{prefix}{p.name}", p) for p in parts])


def geodesic_square(lon: float, lat: float, side_m: float) -> Polygon:
    """A square whose sides are exactly side_m metres on the WGS84 ellipsoid.

    Built by walking geodesics, so its true area does not depend on any projection; that
    is what makes it a fair ground truth for the projected measurement.
    """
    corners = [(lon, lat)]
    for azimuth in (90, 0, 270):
        x, y, _ = GEOD.fwd(*corners[-1], azimuth, side_m)
        corners.append((x, y))
    return Polygon(corners)


def kml_document(folders: dict[str, list[str]]) -> str:
    """Build a KML document from {folder name: [placemark XML, ...]}."""
    body = "".join(
        f"<Folder><name>{name}</name>{''.join(placemarks)}</Folder>"
        for name, placemarks in folders.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"{body}</Document></kml>"
    )


def placemark(name: str, geometry_xml: str, extended_data: dict[str, str] | None = None) -> str:
    data = "".join(
        f'<Data name="{key}"><value>{value}</value></Data>'
        for key, value in (extended_data or {}).items()
    )
    extended = f"<ExtendedData>{data}</ExtendedData>" if data else ""
    return f"<Placemark><name>{name}</name>{extended}{geometry_xml}</Placemark>"


def kml_coords(coords: Iterable[tuple[float, ...]]) -> str:
    return " ".join(",".join(str(c) for c in point) for point in coords)


def kml_polygon(coords: Iterable[tuple[float, ...]]) -> str:
    return (
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
        f"{kml_coords(coords)}"
        "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
    )


def kml_line(coords: Iterable[tuple[float, ...]]) -> str:
    return f"<LineString><coordinates>{kml_coords(coords)}</coordinates></LineString>"


def kml_point(lon: float, lat: float) -> str:
    return f"<Point><coordinates>{lon},{lat}</coordinates></Point>"
