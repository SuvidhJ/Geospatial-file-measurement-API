"""Upload validation, safe storage, archive extraction and dataset discovery.

Everything here runs on untrusted input, so each check fails closed with a clear message.
"""

import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree.ElementTree import ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import parse as parse_xml_safely

from app.errors import DatasetError, FileTooLargeError, InvalidFileError, UnsupportedFileTypeError
from app.models import FileFormat

CHUNK_SIZE = 1024 * 1024
FORMAT_BY_SUFFIX = {".zip": FileFormat.SHAPEFILE, ".kml": FileFormat.KML}
SHAPEFILE_REQUIRED_COMPANIONS = (".shx", ".dbf")


def detect_format(filename: str) -> FileFormat:
    suffix = Path(filename).suffix.lower()
    try:
        return FORMAT_BY_SUFFIX[suffix]
    except KeyError:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{suffix or filename}'. "
            "Upload a .zip containing a Shapefile or a .kml file.",
            details={"supported_extensions": sorted(FORMAT_BY_SUFFIX)},
        ) from None


def save_upload(source: BinaryIO, destination: Path, max_bytes: int) -> int:
    """Copy the upload to disk in chunks, enforcing the size limit while copying."""
    written = 0
    with destination.open("wb") as out:
        while chunk := source.read(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                raise FileTooLargeError(
                    f"Upload exceeds the maximum size of {max_bytes} bytes.",
                    details={"max_upload_bytes": max_bytes},
                )
            out.write(chunk)
    if written == 0:
        raise InvalidFileError("The uploaded file is empty.")
    return written


def validate_content(path: Path, file_format: FileFormat) -> None:
    """Check the bytes match the extension; the extension alone proves nothing."""
    if file_format is FileFormat.SHAPEFILE:
        if not zipfile.is_zipfile(path):
            raise InvalidFileError("The .zip file is not a valid zip archive.")
    else:
        _validate_kml(path)


def _validate_kml(path: Path) -> None:
    # defusedxml rejects entity declarations and external references, which blocks XXE and
    # "billion laughs" payloads before GDAL ever parses the file.
    try:
        root = parse_xml_safely(path).getroot()
    except DefusedXmlException:
        raise InvalidFileError("The KML contains forbidden XML entities or DTDs.") from None
    except ParseError as exc:
        raise InvalidFileError(f"The .kml file is not valid XML: {exc}.") from None
    if _local_name(root.tag) != "kml":
        raise InvalidFileError(f"Expected a <kml> root element, found <{_local_name(root.tag)}>.")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def safe_extract(archive: Path, target: Path, *, max_members: int, max_total_bytes: int) -> None:
    """Extract an archive while blocking path traversal and decompression bombs.

    The uncompressed size is counted while streaming, not trusted from the zip headers,
    because headers can lie.
    """
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir() and not _is_ignored(m.filename)]
            if len(members) > max_members:
                raise InvalidFileError(
                    f"The archive contains {len(members)} files; the limit is {max_members}."
                )
            total_bytes = 0
            for member in members:
                destination = (root / member.filename).resolve()
                if not destination.is_relative_to(root):
                    raise InvalidFileError(f"Unsafe path in archive: '{member.filename}'.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, destination.open("wb") as out:
                    while chunk := src.read(CHUNK_SIZE):
                        total_bytes += len(chunk)
                        if total_bytes > max_total_bytes:
                            raise InvalidFileError(
                                "The archive is too large when uncompressed "
                                f"(limit {max_total_bytes} bytes)."
                            )
                        out.write(chunk)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        # RuntimeError: encrypted members; NotImplementedError: unsupported compression.
        raise InvalidFileError(f"The archive could not be extracted: {exc}.") from None


def _is_ignored(name: str) -> bool:
    """Skip macOS resource forks and hidden files that zip tools add.

    "." and ".." are not hidden files: they must reach the path-traversal check and be
    rejected loudly instead of being silently skipped.
    """
    return any(
        part == "__MACOSX" or (part.startswith(".") and part not in {".", ".."})
        for part in PurePosixPath(name).parts
    )


def locate_shapefile(root: Path) -> Path:
    """Find the single .shp anywhere in the extracted tree and check its companions exist."""
    files = sorted(p for p in root.rglob("*") if p.is_file())
    shapefiles = [p for p in files if p.suffix.lower() == ".shp"]
    if not shapefiles:
        found = ", ".join(_relative(p, root) for p in files) or "none"
        raise DatasetError(f"No .shp file found in the archive. Files found: {found}.")
    if len(shapefiles) > 1:
        found = ", ".join(_relative(p, root) for p in shapefiles)
        raise DatasetError(
            f"Expected exactly one .shp file, found {len(shapefiles)}: {found}. "
            "Upload one Shapefile per archive."
        )

    shp = shapefiles[0]
    siblings = {p.name.lower() for p in shp.parent.iterdir()}
    missing = [
        ext for ext in SHAPEFILE_REQUIRED_COMPANIONS if f"{shp.stem.lower()}{ext}" not in siblings
    ]
    if missing:
        raise DatasetError(
            f"Shapefile '{_relative(shp, root)}' is missing required file(s): {', '.join(missing)}."
        )
    return shp


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
