# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, not in a public issue. Include steps to reproduce and, if possible, a
sample file. Reports are acknowledged within a few days.

## Supported versions

Only the latest release on `main` receives fixes.

## Threat model

Every uploaded file is treated as hostile. The service defends against:

| Threat | Defence | Where |
|---|---|---|
| Oversized uploads | `Content-Length` checked before the body is read; bytes counted while streaming | `app/main.py`, `app/services/ingest.py` |
| Zip slip (path traversal) | Every extracted path must resolve inside the extraction directory | `ingest.safe_extract` |
| Zip bombs | Member-count cap and an uncompressed-size cap counted while streaming, not trusted from headers | `ingest.safe_extract` |
| XXE and entity expansion in KML/KMZ | Parsed with `defusedxml` before GDAL reads the file | `ingest._validate_kml` |
| Files that make GDAL read other files (e.g. VRT) | DEMs must start with a TIFF signature and are opened with the GeoTIFF driver only | `app/services/volumes.py` |
| Raster memory exhaustion | Per-feature DEM cell limit | `GEOAPI_MAX_DEM_CELLS_PER_FEATURE` |
| Path injection via filenames | Uploads are stored under server-generated ids; client filenames never reach the filesystem | `processing.accept_upload` |
| Script injection in the viewer | File-derived text is only inserted with `textContent`; CDN assets are pinned with Subresource Integrity | `app/static/viewer/index.html` |
| Log forging | Client request ids are echoed only if they match `[A-Za-z0-9._-]{1,64}` | `app/main.py` |
| Leaking internals | Unexpected errors return a generic 500 envelope; details go to the server log | `app/main.py` |

The container runs as a non-root user.

## Out of scope

The service has no authentication. Deploy it behind an authenticating gateway, or add API
keys, before exposing it to untrusted networks.
