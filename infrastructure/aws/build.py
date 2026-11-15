"""Genera el ZIP de Lambda a partir del snapshot y las dependencias de la demo."""

import argparse
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

AWS_DIR = Path(__file__).resolve().parent
DEMO_DIR = AWS_DIR.parent / "demo"
ROOT = AWS_DIR.parent.parent


def build(output: Path, etl_python: str) -> None:
    subprocess.run([etl_python, "-m", "infrastructure.demo.export_data"], cwd=ROOT, check=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="lambda-dependencies-", dir=output.parent) as build_dir:
        dependencies = Path(build_dir)
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "--platform", "manylinux2014_x86_64",
                "--platform", "manylinux_2_28_x86_64",
                "--platform", "manylinux_2_34_x86_64",
                "--implementation", "cp",
                "--python-version", "3.12",
                "--only-binary=:all:",
                "--no-compile",
                "--target", str(dependencies),
                "-r", str(DEMO_DIR / "requirements.txt"),
            ],
            check=True,
        )

        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for file in sorted(dependencies.rglob("*")):
                relative = file.relative_to(dependencies)
                if file.is_file() and "__pycache__" not in relative.parts and relative.parts[0] != "bin":
                    write_file(archive, relative.as_posix(), file)
            for name in ("app.py", "snapshot.json"):
                write_file(archive, name, DEMO_DIR / name)
    print(f"{output}: {output.stat().st_size:,} B")


def write_file(archive: ZipFile, name: str, file: Path) -> None:
    # A fixed timestamp avoids changing the package hash for identical inputs.
    archive.writestr(ZipInfo(name), file.read_bytes(), compress_type=ZIP_DEFLATED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=AWS_DIR / ".build" / "lambda.zip")
    parser.add_argument("--etl-python", default=sys.executable)
    arguments = parser.parse_args()
    build(arguments.output.resolve(), arguments.etl_python)
