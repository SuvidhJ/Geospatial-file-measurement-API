# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-11

### Added

- Upload of zipped Shapefiles, KML and KMZ files with per-feature extraction of index, source
  FID, geometry type, GeoJSON geometry, CRS and JSON-safe properties.
- Area, perimeter and length measured in a projected CRS chosen per feature (UTM zone of the
  centroid, Lambert Azimuthal Equal-Area beyond UTM's limits), with a geodesic cross-check
  on the WGS84 ellipsoid for every value.
- Stockpile cut, fill and net volume and 3D surface area of polygons from a GeoTIFF DEM.
- Synchronous or queued processing; the queue runs on Redis with RQ workers, with an
  in-process fallback when Redis is not configured.
- GeoJSON export, paginated and filterable measurements with a summary, list and delete
  endpoints, and a health check that reports the queue backend.
- A map viewer built on the public API.
- Defences against zip slip, zip bombs, XXE, oversized uploads and GDAL file indirection.
- Alembic migrations applied on startup, request ids and structured request logging.
- Docker image, Compose stack and CI running ruff, mypy, pytest with a coverage gate and a
  full-stack smoke test.
