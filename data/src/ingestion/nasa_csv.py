import csv
from codecs import BOM_UTF8
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
from pathlib import Path


@dataclass(frozen=True)
class CsvTable:
    header: tuple[str, ...]
    rows: list[list[str]]
    encoding: str
    delimiter: str
    sha256: str


def inspect_nasa_csv(path: Path, encoding: str | None = None) -> CsvTable:
    content = path.read_bytes()
    if encoding is None:
        if content.startswith(BOM_UTF8):
            encoding = "utf-8-sig"
        else:
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                encoding = "cp1252"
            else:
                encoding = "utf-8"
    text = content.decode(encoding)

    # Choose the single delimiter that yields a rectangular, multi-column table.
    candidates = []
    for delimiter in (",", ";", "\t", "|"):
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            header = next(reader, [])
            if len(header) < 2:
                continue
            rows = list(reader)
        except csv.Error:
            continue
        if all(len(row) == len(header) for row in rows):
            candidates.append((tuple(header), rows, delimiter))
    if len(candidates) != 1:
        raise ValueError(f"{path}: expected one unambiguous rectangular CSV dialect")
    header, rows, delimiter = candidates[0]
    return CsvTable(header, rows, encoding, delimiter, sha256(content).hexdigest())


def validate_nasa_csv(
    path: Path, source: CsvTable, expected_header: tuple[str, ...], expected_rows: int
) -> None:
    if source.header != expected_header:
        raise ValueError(f"{path}: unexpected header: {source.header!r}")
    if len(source.rows) != expected_rows:
        raise ValueError(f"{path}: found {len(source.rows)} records; expected {expected_rows}")


def read_nasa_csv(
    path: Path, encoding: str, expected_header: tuple[str, ...], expected_rows: int
) -> tuple[list[list[str]], str]:
    """Return the original cell text and the hash of the bytes that were read."""
    source = inspect_nasa_csv(path, encoding)
    validate_nasa_csv(path, source, expected_header, expected_rows)
    return source.rows, source.sha256
