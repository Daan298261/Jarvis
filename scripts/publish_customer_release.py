"""Copy customer deliverables into the gitignored repo ``release/`` folder.

Used by the Android companion build (``scripts/build_android.py``) and the
Linux CI workflow (``.github/workflows/android-companion.yml``). The Windows
installer and Tauri NSIS scripts publish through
``installer/windows/stage-release-folder.ps1`` into the same folder.

The customer set is the installer executable, issued license, companion APK,
and license manager. Source archives are refused. The portal ``npm run build``
output stays in ``frontend/dist``; it is an installer input, not a package we
drop here.

``-DriveReleasesPath`` is a parameter of ``installer/windows/build-installer.ps1``
only. This publisher writes ``<repo>/release/`` and does not copy elsewhere.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO / "release"

_ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".7z")


def is_customer_deliverable(name: str) -> bool:
    """True for the shippable installer, license, APK, or license manager."""
    lower = name.lower()
    if lower.endswith(_ARCHIVE_SUFFIXES):
        return False
    if lower.endswith(".jarvis-license"):
        return True
    if lower == "jarvissetup.exe" or lower.endswith("-setup.exe"):
        return True
    if lower in {"jarvislicensemanager.exe", "jarvislicensemanager.cmd"}:
        return True
    if name.startswith("JarvisSetup-") and lower.endswith(".bin"):
        return True
    if lower.endswith(".apk"):
        return True
    return False


def publish_file(source: Path, *, name: str | None = None, release_dir: Path | None = None) -> Path:
    """Copy one customer deliverable into ``release/`` and return the new path.

    ``source`` stays in place. ``name`` renames the copy (CI's ``app-release.apk``
    becomes ``JarvisCompanion.apk``). The destination name must itself be a
    customer deliverable, so a zip renamed to look like an apk is still checked
    against the source name as well.
    """
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Customer deliverable not found: {src}")
    dest_name = name or src.name
    if not is_customer_deliverable(src.name) or not is_customer_deliverable(dest_name):
        raise ValueError(f"Refusing to publish non-customer artifact: {src.name}")
    dest_dir = Path(release_dir) if release_dir is not None else RELEASE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    shutil.copyfile(src, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Customer deliverable to copy into <repo>/release/ (repeatable)",
    )
    parser.add_argument(
        "--as",
        dest="rename",
        default="",
        help="Destination file name when exactly one --source is given",
    )
    args = parser.parse_args(argv)
    sources = [Path(item) for item in args.source]
    if args.rename and len(sources) != 1:
        parser.error("--as requires exactly one --source")
    for src in sources:
        dest = publish_file(src, name=args.rename or None)
        print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
