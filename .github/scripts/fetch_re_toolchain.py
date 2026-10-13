"""Fetch the pinned RFC-0207 static toolchain (JDK 21, apktool, jadx) for CI's real-tool tests.

Every artifact is checked against backend/app/reverse_engineering/engine-lock.json before use,
including artifacts restored from the Actions cache, so a poisoned cache or a changed upstream
release fails the job instead of running unverified tools. Writes ANZU_TEST_* to $GITHUB_ENV.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

LOCK = Path(__file__).resolve().parents[2] / "backend" / "app" / "reverse_engineering" / "engine-lock.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(root: Path, name: str, spec: dict) -> Path:
    dest = root / "downloads" / Path(spec["url"].split("?")[0]).name.replace("%2B", "+")
    if not dest.is_file() or sha256(dest) != spec["sha256"]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_suffix(dest.suffix + ".partial")
        print(f"Downloading {name} {spec['version']} from {spec['url']}", flush=True)
        with urllib.request.urlopen(spec["url"], timeout=300) as r, partial.open("wb") as f:
            shutil.copyfileobj(r, f)
        partial.replace(dest)
    actual = sha256(dest)
    if actual != spec["sha256"]:
        dest.unlink()
        raise SystemExit(f"{name}: SHA-256 {actual} does not match engine-lock.json {spec['sha256']}")
    print(f"{name} {spec['version']}: SHA-256 verified ({actual})", flush=True)
    return dest


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    jdk_tgz = fetch(root, "jdk", lock["jdk"])
    apktool = fetch(root, "apktool", lock["apktool"])
    jadx_zip = fetch(root, "jadx", lock["jadx"])

    jdk_dir = root / "jdk"
    shutil.rmtree(jdk_dir, ignore_errors=True)
    with tarfile.open(jdk_tgz) as t:
        t.extractall(jdk_dir, filter="data")
    java = next(jdk_dir.glob("*/bin/java"))
    jadx_dir = root / "jadx"
    shutil.rmtree(jadx_dir, ignore_errors=True)
    with zipfile.ZipFile(jadx_zip) as z:
        z.extractall(jadx_dir)
    jadx = jadx_dir / "bin" / "jadx"
    for exe in (java, jadx):
        exe.chmod(0o755)
    readelf = shutil.which("readelf")
    if not readelf:
        raise SystemExit("readelf (binutils) is not on PATH")
    env = {"ANZU_TEST_JAVA": str(java), "ANZU_TEST_APKTOOL_JAR": str(apktool),
           "ANZU_TEST_JADX": str(jadx), "ANZU_TEST_READELF": readelf,
           "JAVA_HOME": str(java.parents[1])}
    with open(os.environ.get("GITHUB_ENV", os.devnull), "a", encoding="utf-8") as f:
        for key, value in env.items():
            f.write(f"{key}={value}\n")
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
