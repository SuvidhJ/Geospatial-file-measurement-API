"""Pipeline orchestration and file status transitions.

`accept_upload` does request-level work (validate, store, extract) and rejects bad input
before anything is persisted. `process_file` does content-level work and is the one
function a background worker would call instead of the request handler.
"""

import logging
import shutil
import uuid
from collections import Counter
from pathlib import Path
from typing import BinaryIO

from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import DatasetError
from app.models import Feature, FileFormat, FileStatus, UploadedFile
from app.services import ingest, reader
from app.services.crs import crs_label, to_wgs84
from app.services.measure import measure

logger = logging.getLogger(__name__)

STORED_UPLOAD_NAME = {FileFormat.SHAPEFILE: "upload.zip", FileFormat.KML: "upload.kml"}
EXTRACTED_DIR = "extracted"
NULL_GEOMETRY = "None"


def accept_upload(db: Session, settings: Settings, filename: str, stream: BinaryIO) -> UploadedFile:
    file_format = ingest.detect_format(filename)
    file_id = uuid.uuid4()
    # Files are stored under a server-generated id; the client's filename never touches disk.
    workdir = settings.upload_dir / str(file_id)
    workdir.mkdir(parents=True)
    try:
        stored = workdir / STORED_UPLOAD_NAME[file_format]
        ingest.save_upload(stream, stored, settings.max_upload_bytes)
        ingest.validate_content(stored, file_format)
        if file_format is FileFormat.SHAPEFILE:
            ingest.safe_extract(
                stored,
                workdir / EXTRACTED_DIR,
                max_members=settings.max_archive_members,
                max_total_bytes=settings.max_uncompressed_bytes,
            )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise

    record = UploadedFile(
        id=file_id,
        filename=Path(filename).name[:255],
        format=file_format,
        status=FileStatus.PENDING,
        storage_path=str(workdir),
    )
    db.add(record)
    db.commit()
    return record


def process_file(db: Session, file_id: uuid.UUID, settings: Settings) -> UploadedFile:
    record = db.get_one(UploadedFile, file_id)
    record.status = FileStatus.PROCESSING
    db.commit()

    try:
        dataset = _read_dataset(record)
        source_crs = crs_label(dataset.crs)
        features = [
            _build_feature(feature, dataset, source_crs, settings.geodesic_warning_pct)
            for feature in reader.iter_features(dataset)
        ]
    except DatasetError as exc:
        return _mark_failed(db, record, str(exc))
    except Exception:
        logger.exception("Unexpected error while processing file %s", file_id)
        _mark_failed(db, record, "An unexpected error occurred while processing the file.")
        raise

    record.features = features
    record.feature_count = len(features)
    record.geometry_type_counts = dict(
        Counter(feature.geometry_type or NULL_GEOMETRY for feature in features)
    )
    record.crs = source_crs
    record.crs_assumed = dataset.crs_assumed
    record.warnings = dataset.warnings + ([] if features else ["The file contains no features."])
    record.status = FileStatus.COMPLETED
    db.commit()
    return record


def _read_dataset(record: UploadedFile) -> reader.Dataset:
    workdir = Path(record.storage_path)
    if record.format == FileFormat.KML:
        return reader.read_kml(workdir / STORED_UPLOAD_NAME[FileFormat.KML])
    return reader.read_shapefile(ingest.locate_shapefile(workdir / EXTRACTED_DIR))


def _build_feature(
    source: reader.SourceFeature,
    dataset: reader.Dataset,
    source_crs: str | None,
    warning_threshold_pct: float,
) -> Feature:
    prepared = reader.prepare_geometry(source.geometry)
    geometry = prepared.geometry
    geometry_wgs84 = (
        to_wgs84(geometry, dataset.crs)
        if geometry is not None and dataset.crs is not None
        else None
    )
    result = measure(geometry, geometry_wgs84, dataset.crs, warning_threshold_pct)
    # Output geometry is GeoJSON in WGS84 (RFC 7946). With an unknown CRS it cannot be
    # transformed, so the source coordinates are returned and geometry_crs is null.
    output_geometry = geometry_wgs84 if geometry_wgs84 is not None else geometry

    return Feature(
        index=source.index,
        source_fid=source.source_fid,
        geometry_type=source.geometry.geom_type if source.geometry is not None else None,
        measured_geometry_type=geometry.geom_type if geometry is not None else None,
        geometry=mapping(output_geometry) if output_geometry is not None else None,
        geometry_crs="EPSG:4326" if geometry_wgs84 is not None else None,
        source_crs=source_crs,
        properties=source.properties,
        repaired=prepared.repaired,
        measurement_status=result.status,
        measurement_reason=result.reason,
        measurement_crs=result.measurement_crs,
        measurement_method=result.method,
        area_m2=result.area_m2,
        perimeter_m=result.perimeter_m,
        length_m=result.length_m,
        geodesic_area_m2=result.geodesic_area_m2,
        geodesic_perimeter_m=result.geodesic_perimeter_m,
        geodesic_length_m=result.geodesic_length_m,
        difference_pct=result.difference_pct,
        warnings=prepared.warnings + result.warnings,
    )


def _mark_failed(db: Session, record: UploadedFile, detail: str) -> UploadedFile:
    db.rollback()
    record.status = FileStatus.FAILED
    record.error_detail = detail
    db.commit()
    return record


def delete_file(db: Session, record: UploadedFile) -> None:
    storage = Path(record.storage_path)
    db.delete(record)
    db.commit()
    # Remove files only after the row is gone: an orphaned folder is harmless, a row
    # pointing at deleted files is not.
    shutil.rmtree(storage, ignore_errors=True)
