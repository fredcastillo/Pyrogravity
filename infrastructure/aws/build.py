"""Genera el ZIP de Lambda a partir del snapshot y las dependencias de la demo."""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

AWS_DIR = Path(__file__).resolve().parent
DEMO_DIR = AWS_DIR.parent / "demo"
ROOT = AWS_DIR.parent.parent


def build(output: Path, etl_python: str, release_id: str | None = None) -> None:
    if release_id is not None and not re.fullmatch(r"[0-9a-f]{40}", release_id):
        raise ValueError("El identificador de publicación debe ser un SHA de Git completo.")
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
                "-r", str(AWS_DIR / "lambda-requirements.txt"),
            ],
            check=True,
        )

        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for file in sorted(dependencies.rglob("*")):
                relative = file.relative_to(dependencies)
                if file.is_file() and "__pycache__" not in relative.parts and relative.parts[0] != "bin":
                    write_file(archive, relative.as_posix(), file)
            for name in ("app.py", "snapshot.json", "analyses.json"):
                write_file(archive, f"infrastructure/demo/{name}", DEMO_DIR / name)
            write_file(archive, "infrastructure/aws/lambda_entry.py", AWS_DIR / "lambda_entry.py")
            # The alias keeps the same handler across releases and rollback to older ZIPs.
            archive.writestr(ZipInfo("app/__init__.py"), b"from infrastructure.aws.lambda_entry import handler\n")
            for pattern in ("app/**/*.py", "ai/contracts/v1_1/*.json", "data/src/**/*.py", "data/raw/*.csv"):
                for file in sorted(ROOT.glob(pattern)):
                    write_file(archive, file.relative_to(ROOT).as_posix(), file)
            ai_package = ROOT / "ai" / "src"
            for file in sorted(ai_package.glob("pyrogravity_ai/schemas/*.py")):
                write_file(archive, file.relative_to(ai_package).as_posix(), file)
            write_file(archive, "data/source_manifest.csv", ROOT / "data" / "source_manifest.csv")
            if release_id:
                archive.writestr(ZipInfo("infrastructure/demo/release.txt"), release_id)
            uncompressed = sum(item.file_size for item in archive.infolist())
            if uncompressed > 250 * 1024 * 1024:
                raise ValueError(f"El paquete excede el límite de Lambda ({uncompressed:,} B sin comprimir).")
    print(f"{output}: {output.stat().st_size:,} B")


def write_file(archive: ZipFile, name: str, file: Path) -> None:
    # A fixed timestamp avoids changing the package hash for identical inputs.
    archive.writestr(ZipInfo(name), file.read_bytes(), compress_type=ZIP_DEFLATED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=AWS_DIR / ".build" / "lambda.zip")
    parser.add_argument("--etl-python", default=sys.executable)
    parser.add_argument("--release-id")
    arguments = parser.parse_args()
    build(arguments.output.resolve(), arguments.etl_python, arguments.release_id)
