import hashlib
import io
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from app.errors import DatasetError, FileTooLargeError, InvalidFileError, UnsupportedFileTypeError
from app.models import FileFormat
from app.services import ingest
from tests.factories import kml_document, kml_point, placemark, shapefile_zip, zip_files

POINTS = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(77.59, 12.97)], crs=4326)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("survey.zip", FileFormat.SHAPEFILE), ("SURVEY.KML", FileFormat.KML)],
)
def test_detect_format_accepts_zip_and_kml(filename: str, expected: FileFormat) -> None:
    assert ingest.detect_format(filename) is expected


@pytest.mark.parametrize("filename", ["survey.geojson", "survey.kmz", "survey"])
def test_detect_format_rejects_other_types(filename: str) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        ingest.detect_format(filename)


def test_save_upload_rejects_empty_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidFileError, match="empty"):
        ingest.save_upload(io.BytesIO(b""), tmp_path / "upload", max_bytes=100)


def test_save_upload_enforces_size_limit_while_streaming(tmp_path: Path) -> None:
    with pytest.raises(FileTooLargeError):
        ingest.save_upload(io.BytesIO(b"x" * 101), tmp_path / "upload", max_bytes=100)


def test_save_upload_writes_bytes_and_hashes_them(tmp_path: Path) -> None:
    stored = ingest.save_upload(io.BytesIO(b"abc"), tmp_path / "upload", max_bytes=100)

    assert stored.size_bytes == 3
    assert stored.sha256 == hashlib.sha256(b"abc").hexdigest()
    assert (tmp_path / "upload").read_bytes() == b"abc"


def test_non_zip_renamed_to_zip_is_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "fake.zip"
    fake.write_text("this is not a zip")

    with pytest.raises(InvalidFileError, match="not a valid zip"):
        ingest.validate_content(fake, FileFormat.SHAPEFILE)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not xml at all <", "not valid XML"),
        ("<gpx></gpx>", "Expected a <kml> root"),
    ],
)
def test_invalid_kml_is_rejected(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "bad.kml"
    path.write_text(content)

    with pytest.raises(InvalidFileError, match=message):
        ingest.validate_content(path, FileFormat.KML)


def test_kml_with_xxe_payload_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "xxe.kml"
    path.write_text(
        '<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>&xxe;</name>'
        "</Document></kml>"
    )

    with pytest.raises(InvalidFileError, match="forbidden XML entities"):
        ingest.validate_content(path, FileFormat.KML)


def test_valid_kml_passes_validation(tmp_path: Path) -> None:
    path = tmp_path / "ok.kml"
    path.write_text(kml_document({"Points": [placemark("p", kml_point(77.59, 12.97))]}))

    ingest.validate_content(path, FileFormat.KML)


def test_zip_slip_is_blocked(tmp_path: Path) -> None:
    archive = zip_files(tmp_path / "evil.zip", [("../../evil.txt", b"pwned")])
    target = tmp_path / "out" / "extracted"

    with pytest.raises(InvalidFileError, match="Unsafe path"):
        ingest.safe_extract(archive, target, max_members=10, max_total_bytes=10_000)
    assert not (tmp_path / "evil.txt").exists()


def test_zip_bomb_is_stopped_by_streamed_size_cap(tmp_path: Path) -> None:
    # 2 MB of zeros compresses to a few KB: small upload, large extraction.
    archive = zip_files(tmp_path / "bomb.zip", [("zeros.bin", b"\0" * 2_000_000)])
    assert archive.stat().st_size < 50_000

    with pytest.raises(InvalidFileError, match="too large when uncompressed"):
        ingest.safe_extract(
            archive, tmp_path / "extracted", max_members=10, max_total_bytes=1_000_000
        )


def test_archive_member_count_is_capped(tmp_path: Path) -> None:
    archive = zip_files(tmp_path / "many.zip", [(f"f{i}.txt", b"x") for i in range(5)])

    with pytest.raises(InvalidFileError, match="contains 5 files"):
        ingest.safe_extract(archive, tmp_path / "extracted", max_members=4, max_total_bytes=1000)


def test_macos_metadata_and_hidden_files_are_ignored(tmp_path: Path) -> None:
    archive = zip_files(
        tmp_path / "mac.zip",
        [("data.txt", b"x"), ("__MACOSX/._data.txt", b"x"), (".DS_Store", b"x")],
    )
    target = tmp_path / "extracted"

    ingest.safe_extract(archive, target, max_members=1, max_total_bytes=1000)

    assert sorted(p.name for p in target.rglob("*")) == ["data.txt"]


def test_locate_shapefile_in_nested_folder(tmp_path: Path) -> None:
    archive = shapefile_zip(tmp_path, POINTS, folder="survey/2024/layers")
    target = tmp_path / "extracted"
    ingest.safe_extract(archive, target, max_members=10, max_total_bytes=1_000_000)

    shp = ingest.locate_shapefile(target)

    assert shp.relative_to(target).as_posix() == "survey/2024/layers/data.shp"


def test_locate_shapefile_without_shp_lists_found_files(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("hi")

    with pytest.raises(DatasetError, match=r"No \.shp file found.*readme\.txt"):
        ingest.locate_shapefile(tmp_path)


def test_locate_shapefile_rejects_multiple_shp(tmp_path: Path) -> None:
    for name in ("roads", "parcels"):
        (tmp_path / f"{name}.shp").write_bytes(b"")

    with pytest.raises(DatasetError, match=r"found 2: parcels\.shp, roads\.shp"):
        ingest.locate_shapefile(tmp_path)


@pytest.mark.parametrize("missing", [".shx", ".dbf"])
def test_locate_shapefile_requires_companions(tmp_path: Path, missing: str) -> None:
    archive = shapefile_zip(tmp_path, POINTS, exclude=(missing,))
    target = tmp_path / "extracted"
    ingest.safe_extract(archive, target, max_members=10, max_total_bytes=1_000_000)

    with pytest.raises(DatasetError, match=rf"missing required file\(s\): \{missing}"):
        ingest.locate_shapefile(target)
