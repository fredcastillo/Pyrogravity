import csv
from hashlib import sha256
from io import StringIO
from pathlib import Path


def read_nasa_csv(
    path: Path, encoding: str, expected_header: tuple[str, ...], expected_rows: int
) -> tuple[list[list[str]], str]:
    """Return the original cell text and the hash of the bytes that were read."""
    content = path.read_bytes()
    reader = csv.reader(StringIO(content.decode(encoding), newline=""), strict=True)
    rows = []
    try:
        header = next(reader, None)
        if header != list(expected_header):
            raise ValueError(f"{path}: unexpected header: {header!r}")

        for record in reader:
            if len(record) != len(expected_header):
                raise ValueError(
                    f"{path}: CSV line {reader.line_num} has {len(record)} fields; "
                    f"expected {len(expected_header)}"
                )
            rows.append(record)
    except csv.Error as error:
        raise ValueError(f"{path}: invalid CSV at line {reader.line_num}") from error

    if len(rows) != expected_rows:
        raise ValueError(f"{path}: found {len(rows)} records; expected {expected_rows}")

    return rows, sha256(content).hexdigest()
