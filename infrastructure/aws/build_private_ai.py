"""Build a Linux x86_64 Lambda package for the private AI service."""

import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from build import AWS_DIR, ROOT, write_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=AWS_DIR / ".build" / "private-ai.zip")
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="private-ai-", dir=output.parent) as temp:
        vendor = Path(temp)
        subprocess.run([
            sys.executable, "-m", "pip", "install",
            "--platform", "manylinux2014_x86_64",
            "--platform", "manylinux_2_28_x86_64",
            "--platform", "manylinux_2_34_x86_64",
            "--implementation", "cp", "--python-version", "3.12",
            "--only-binary=:all:", "--no-compile", "--target", str(vendor),
            "-r", str(AWS_DIR / "private-ai-requirements.txt"),
        ], check=True)
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for file in sorted(vendor.rglob("*")):
                name = file.relative_to(vendor)
                if file.is_file() and "__pycache__" not in name.parts and name.parts[0] != "bin":
                    write_file(archive, name.as_posix(), file)
            package = ROOT / "ai" / "src"
            for file in sorted(package.rglob("*.py")):
                write_file(archive, file.relative_to(package).as_posix(), file)
            write_file(archive, "private_ai_handler.py", AWS_DIR / "private_ai_handler.py")
            size = sum(item.file_size for item in archive.infolist())
            if size > 250 * 1024 * 1024:
                raise ValueError(f"Lambda package exceeds 250 MiB ({size:,} B)")
    print(f"{output}: {output.stat().st_size:,} B")


if __name__ == "__main__":
    main()
