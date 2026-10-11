import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_file_or_404, get_settings
from app.config import Settings
from app.errors import FileNotReadyError, ProcessingFailedError, QueueUnavailableError
from app.models import FileStatus, UploadedFile
from app.schemas.errors import ErrorResponse
from app.schemas.files import FileList, FileRead
from app.schemas.geojson import GEOJSON_MEDIA_TYPE, feature_collection
from app.schemas.measurements import FeatureMeasurement, GeometryType, MeasurementPage
from app.schemas.volumes import VolumeReport, volume_report
from app.services import ingest, jobs, processing, results
from app.services.volumes import BaseMethod, compute_volumes

router = APIRouter(prefix="/api/files", tags=["files"])

DbSession = Annotated[Session, Depends(get_db)]
FileRecord = Annotated[UploadedFile, Depends(get_file_or_404)]
Limit = Annotated[int, Query(ge=1, le=500, description="Page size.")]
Offset = Annotated[int, Query(ge=0, description="Number of items to skip.")]


def _errors(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in status_codes}


@router.post(
    "/",
    status_code=201,
    summary="Upload and process a geospatial file",
    description=(
        "Accepts a `.zip` containing exactly one Shapefile (`.shp` with `.shx` and `.dbf`; "
        "`.prj` strongly recommended), a `.kml` file, or a `.kmz` (zipped KML).\n\n"
        "By default the file is processed before responding (`201`). With `wait=false` "
        "the upload is accepted with `202` and status `PENDING`, processed in the "
        "background, and polled with `GET /api/files/{id}/`.\n\n"
        "Bad input is rejected with 400/413/415 and not stored. A file that is accepted "
        "but cannot be processed is stored as FAILED and returned as a 422 error whose "
        "`details.file_id` can be used with the GET endpoints."
    ),
    responses={
        202: {"description": "Accepted for background processing (wait=false)."},
        **_errors(400, 413, 415, 422, 503),
    },
)
def upload_file(
    file: Annotated[
        UploadFile, File(description="A .zip with one Shapefile, a .kml or a .kmz file.")
    ],
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    wait: Annotated[
        bool, Query(description="Process before responding (true) or in the background (false).")
    ] = True,
) -> FileRead:
    record = processing.accept_upload(db, settings, file.filename or "", file.file)
    if not wait:
        try:
            jobs.dispatch_processing(
                record.id, settings, request.app.state.session_factory, background_tasks
            )
        except QueueUnavailableError:
            processing.mark_failed(db, record, "The processing queue was unavailable.")
            raise
        response.status_code = 202
        return FileRead.model_validate(record)

    record = processing.process_file(db, record.id, settings)
    if record.status == FileStatus.FAILED:
        raise ProcessingFailedError(
            record.error_detail or "The file could not be processed.",
            details={"file_id": str(record.id)},
        )
    return FileRead.model_validate(record)


@router.get("/", summary="List uploaded files, newest first")
def list_files(db: DbSession, limit: Limit = 50, offset: Offset = 0) -> FileList:
    total, files = results.list_files(db, limit=limit, offset=offset)
    return FileList(
        total=total,
        limit=limit,
        offset=offset,
        items=[FileRead.model_validate(f) for f in files],
    )


@router.get("/{file_id}/", summary="Get information about a file", responses=_errors(404))
def get_file(record: FileRecord) -> FileRead:
    return FileRead.model_validate(record)


@router.get(
    "/{file_id}/measurements/",
    summary="Get per-feature measurements",
    description=(
        "Returns each feature with its properties, geometry (GeoJSON, EPSG:4326) and "
        "measurement: area for polygons, length for lines. The summary covers every "
        "feature matching `geometry_type`, not just the current page."
    ),
    responses=_errors(404, 409),
)
def get_measurements(
    record: FileRecord,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
    geometry_type: Annotated[
        GeometryType | None, Query(description="Only features of this source geometry type.")
    ] = None,
    include_geometry: Annotated[
        bool, Query(description="Include GeoJSON geometries in the response.")
    ] = True,
) -> MeasurementPage:
    _require_completed(record)
    summary = results.summarize(db, record.id, geometry_type=geometry_type)
    features = results.list_features(
        db, record.id, geometry_type=geometry_type, limit=limit, offset=offset
    )
    return MeasurementPage(
        file_id=record.id,
        filename=record.filename,
        status=FileStatus(record.status),
        crs=record.crs,
        total=summary.feature_count,
        limit=limit,
        offset=offset,
        summary=summary,
        items=[
            FeatureMeasurement.from_feature(f, include_geometry=include_geometry) for f in features
        ],
    )


@router.get(
    "/{file_id}/geojson/",
    summary="Export features and measurements as GeoJSON",
    description=(
        "Returns every feature (optionally filtered by `geometry_type`) as an RFC 7946 "
        "FeatureCollection in EPSG:4326, with the measurement as flat properties and the "
        "source attributes under `attributes`. Opens directly in QGIS or geojson.io."
    ),
    response_class=JSONResponse,
    responses={200: {"content": {GEOJSON_MEDIA_TYPE: {}}}, **_errors(404, 409)},
)
def export_geojson(
    record: FileRecord,
    db: DbSession,
    geometry_type: Annotated[
        GeometryType | None, Query(description="Only features of this source geometry type.")
    ] = None,
) -> JSONResponse:
    _require_completed(record)
    features = results.list_features(
        db, record.id, geometry_type=geometry_type, limit=None, offset=0
    )
    return JSONResponse(feature_collection(record, features), media_type=GEOJSON_MEDIA_TYPE)


@router.post(
    "/{file_id}/volumes/",
    summary="Compute stockpile volumes and 3D surface area from a DEM",
    description=(
        "Upload a digital elevation model (GeoTIFF in a projected CRS with metre units, e.g. "
        "a drone survey DSM in UTM) and get, for every measured polygon in the file: cut, "
        "fill and net volume relative to a horizontal base plane, the 3D surface area and "
        "how much of the polygon the DEM covers.\n\n"
        "The base plane's elevation is sampled from the DEM along the polygon boundary "
        "(the stockpile toe): its mean (`boundary-mean`, default) or its lowest point "
        "(`boundary-min`). Nothing is stored; the DEM is discarded after the calculation."
    ),
    responses=_errors(400, 404, 409, 413),
)
def compute_file_volumes(
    record: FileRecord,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    dem: Annotated[UploadFile, File(description="Elevation model as a GeoTIFF.")],
    base: Annotated[
        BaseMethod, Query(description="How the base plane elevation is chosen.")
    ] = BaseMethod.BOUNDARY_MEAN,
) -> VolumeReport:
    _require_completed(record)
    polygons = results.measured_polygons(db, record.id)
    with tempfile.TemporaryDirectory(dir=settings.data_dir) as workdir:
        dem_path = Path(workdir) / "dem.tif"
        ingest.save_upload(dem.file, dem_path, settings.max_upload_bytes)
        dem_info, volumes = compute_volumes(
            dem_path, polygons, base, settings.max_dem_cells_per_feature
        )
    return volume_report(record.id, base, dem_info, volumes)


@router.delete(
    "/{file_id}/", status_code=204, summary="Delete a file and its data", responses=_errors(404)
)
def delete_file(record: FileRecord, db: DbSession) -> Response:
    processing.delete_file(db, record)
    return Response(status_code=204)


def _require_completed(record: UploadedFile) -> None:
    if record.status != FileStatus.COMPLETED:
        raise FileNotReadyError(
            f"File has no measurements because its status is {record.status}.",
            details={"file_id": str(record.id), "status": record.status},
        )
