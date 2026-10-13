"""RFC-0207 RE Phase 1: execution-free APK reverse-engineering sidecar.

Slice 1: static toolchain readiness (JDK, jadx, apktool), safe intake of standalone
APKs, XAPK/APKS containers and split-APK directories, apktool + jadx orchestration
inside the ANZU-REA WSL distribution with heap caps and timeouts, and manifest,
permission and component extraction.
Slice 2: native .so inventory (ABIs, ELF header, SONAME/NEEDED, RELRO, stack canary,
GNU_STACK, JNI exports, readelf fallback, packer and code-segment entropy hints).
Slice 3: string and network endpoint extraction and cryptographic key-material hints
(``apk_strings``), including network security config evaluation.
Slice 4: device (ADB) and FFS investigation origins for ``prepare_apk`` — ``adb shell pm
path`` + ``adb pull`` into ``apk/staged/``, and FFS ``index/files.ndjson`` reference with
SHA-256 verification. Both origins fail closed: missing ADB, an uninstalled package, a failed
or oversized pull, a missing/corrupt/oversized FFS index, a hash mismatch, or a linked path inside
the dump abort the prepare with an error, and device or dump data is never invented.
Slice 5: smali fallback -- when jadx fails catastrophically (failed / timeout / OOM / no
useful Java) or is skipped with the flag set, re-run apktool without `--no-src` (and with
`--no-res`) for every DEX-bearing part into `apk/smali/<part>/` so bytecode remains inspectable; evidence, custody, catalog
and REST expose the fallback state and counts.
Every step is written to the RFC-0201 investigation store as citable evidence plus a
chain-of-custody record. No target code is executed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import android, provision, store
from .ffs_ingest import make_chain_of_custody_entry
from .privacy import private_directory
from ..tools.safety import resolve_allowed_path

JAVA_HOME = "/opt/anzu/jdk"
JDK = "/opt/anzu/jdk/bin/java"
JADX = "/opt/anzu/jadx/bin/jadx"
APKTOOL_JAR = "/opt/anzu/apktool/apktool.jar"
READELF = "/usr/bin/readelf"  # binutils, installed by provision.install()
JVM_HEAP = ["-Xmx4g", "-XX:+UseG1GC"]
APKTOOL_TIMEOUT = 300
JADX_TIMEOUT = 600
KILL_GRACE = 10
MAX_BYTES = store.MAX_BYTES
MAX_FILES = store.MAX_FILES
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
CONTAINER_SUFFIXES = {".xapk", ".apks"}
APK_SUFFIXES = {".apk"} | CONTAINER_SUFFIXES
OPERATOR = "anzu_apk_sidecar"
_ANDROID = "{http://schemas.android.com/apk/res/android}"
_DECOMPILE_SLOTS = threading.BoundedSemaphore(2)
_CLAIM_LOCK = threading.Lock()
_CANCEL: dict[str, threading.Event] = {}
_RUNNING: dict[str, list[Path]] = {}
_OWNED: set[str] = set()
_CLAIMS: dict[str, str] = {}
log = logging.getLogger(__name__)


class DecompileCancelled(Exception):
    """The investigation was cancelled while a decompile tool was running."""

HIGH_RISK_PERMISSIONS = {
    "storage": {"READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE", "MANAGE_EXTERNAL_STORAGE"},
    "location": {"ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "ACCESS_BACKGROUND_LOCATION"},
    "media_hardware": {"CAMERA", "RECORD_AUDIO", "BODY_SENSORS"},
    "identity_telephony": {"READ_CONTACTS", "READ_PHONE_STATE", "CALL_PHONE", "READ_SMS", "SEND_SMS"},
    "system": {"SYSTEM_ALERT_WINDOW", "REQUEST_INSTALL_PACKAGES", "WRITE_SETTINGS"},
}
COMPONENT_TAGS = {"activity": "activity", "activity-alias": "activity", "service": "service",
                  "receiver": "receiver", "provider": "provider"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock() -> dict:
    return json.loads(provision.LOCK_PATH.read_text(encoding="utf-8"))


def toolchain() -> dict:
    lock = _lock()
    return {"platform": f"WSL2 {provision.DISTRO}", "jdk": lock["jdk"]["version"],
            "jadx": lock["jadx"]["version"], "apktool": lock["apktool"]["version"]}


def _wsl(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run one argv inside the dedicated distro; argv is never interpolated into shell code."""
    return subprocess.run(["wsl.exe", "-d", provision.DISTRO, "-u", "root", "--exec", *args],
                          capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _linux_path(path: Path) -> str:
    result = _wsl(["wslpath", "-a", "-u", path.resolve().as_posix()], 30)
    if result.returncode:
        raise RuntimeError("wslpath could not map " + str(path))
    return result.stdout.decode("utf-8", errors="replace").strip()


# --- Readiness -------------------------------------------------------------------------

def _missing_static_components() -> list[str]:
    missing = []
    for name, path in [("JDK", JDK), ("jadx", JADX), ("apktool", APKTOOL_JAR), ("readelf (binutils)", READELF)]:
        try:
            present = _wsl(["test", "-f", path], 30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            present = False
        if not present:
            missing.append(name)
    if "apktool" not in missing:
        try:
            out = _wsl(["sha256sum", APKTOOL_JAR], 60).stdout.decode("utf-8", errors="replace")
            actual = out.split()[0] if out.split() else ""
        except (OSError, subprocess.TimeoutExpired):
            actual = ""
        if actual != _lock()["apktool"]["sha256"]:
            missing.append("apktool (pinned SHA-256 mismatch)")
    return missing


def readiness_live() -> dict:
    """Live check: run each pinned tool and compare the version it reports with engine-lock.json."""
    static = readiness_static()
    if static["status"] != "ready":
        return static
    versions = static["versions"]
    probes = [("JDK", [JDK, "-version"], ".".join(versions["jdk"].split("+")[0].split(".")[:3])),
              ("jadx", ["env", f"JAVA_HOME={JAVA_HOME}", f"PATH={JAVA_HOME}/bin:/usr/bin:/bin", JADX, "--version"], versions["jadx"]),
              ("apktool", [JDK, "-jar", APKTOOL_JAR, "--version"], versions["apktool"])]
    broken = []
    for name, argv, expected in probes:
        try:
            result = _wsl(argv, 120)
            text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            ok = result.returncode == 0 and expected in text
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok:
            broken.append(name)
    if broken:
        return {"status": "needs_repair", "stage": "Static APK toolchain does not run",
                "error": f"Not runnable or wrong version: {', '.join(broken)}; run setup to repair", "versions": versions}
    return {"status": "ready", "stage": "Static APK toolchain verified by execution", "versions": versions}


def readiness_static() -> dict:
    """Static APK readiness only; emulator, AVD and adb state never affect it."""
    try:
        versions = toolchain()
        missing = _missing_static_components()
        if missing:
            return {"status": "needs_repair", "stage": "Static APK toolchain missing",
                    "error": f"Missing: {', '.join(missing)}; run setup to install", "versions": versions}
        return {"status": "ready", "stage": "Static APK toolchain ready", "versions": versions}
    except Exception as exc:
        return {"status": "needs_repair", "stage": "Static APK toolchain missing", "error": str(exc)}


# --- Intake ----------------------------------------------------------------------------

def _check_entry(name: str) -> PurePosixPath:
    rel = PurePosixPath(name.replace("\\", "/"))
    if (not name or rel.is_absolute() or ":" in name or ".." in rel.parts
            or name.startswith(("/", "\\"))):
        raise ValueError(f"Unsafe archive entry: {name}")
    return rel


def inspect_archive(path: Path) -> list[zipfile.ZipInfo]:
    """Validate a ZIP container without extracting it; fail closed on any unsafe entry."""
    with path.open("rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise ValueError("Target is not a valid APK/ZIP container")
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_FILES:
                raise ValueError("Archive exceeds expanded size/file limit")
            total = 0
            for info in infos:
                _check_entry(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError(f"Unsafe archive entry: {info.filename}")
                total += info.file_size
                if total > MAX_BYTES:
                    raise ValueError("Archive exceeds expanded size/file limit")
            if z.testzip() is not None:
                raise ValueError("Target is not a valid APK/ZIP container")
            return infos
    except (zipfile.BadZipFile, EOFError) as exc:
        raise ValueError("Target is not a valid APK/ZIP container") from exc


def _hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def _apk_part(path: Path, name: str, role: str) -> dict:
    infos = inspect_archive(path)
    names = [i.filename for i in infos]
    if "AndroidManifest.xml" not in names:
        raise ValueError(f"{name} is not an APK: AndroidManifest.xml is missing")
    digest, size = _hash_file(path)
    libs = sorted(n for n in names if re.fullmatch(r"lib/[^/]+/[^/]+\.so", n))
    return {"name": name, "role": role, "path": str(path), "sha256": digest, "bytes": size,
            "entries": len(infos), "expanded_bytes": sum(i.file_size for i in infos),
            "dex": sorted(n for n in names if re.fullmatch(r"classes\d*\.dex", n)),
            "abis": sorted({n.split("/")[1] for n in libs}), "native_libs": libs}


def _extract_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path, budget: dict) -> Path:
    rel = _check_entry(info.filename)
    target = (dest / Path(*rel.parts)).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise ValueError(f"Unsafe archive entry: {info.filename}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst = target.open("xb")
    except FileExistsError as exc:
        raise ValueError(f"Duplicate archive entry: {info.filename}") from exc
    with z.open(info) as src, dst:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            budget["bytes"] += len(chunk)
            if budget["bytes"] > MAX_BYTES:
                raise ValueError("Archive exceeds expanded size/file limit")
            dst.write(chunk)
    return target


def _pick_base(names: list[str], declared: str | None) -> str:
    if declared:
        if declared not in names:
            raise ValueError(f"Container manifest names base {declared!r}, which is not in the archive")
        return declared
    bases = [n for n in names if PurePosixPath(n).name.lower() == "base.apk"]
    if len(bases) == 1:
        return bases[0]
    if len(names) == 1:
        return names[0]
    raise ValueError("Split APK set has no unambiguous base.apk")


def _intake_container(snapshot: Path, staged: Path) -> dict:
    infos = inspect_archive(snapshot)
    apk_infos = [i for i in infos if not i.is_dir() and i.filename.lower().endswith(".apk")]
    if not apk_infos:
        raise ValueError("Container holds no APK files")
    declared_package = None
    declared_base = None
    splits = {}
    meta = next((i for i in infos if i.filename == "manifest.json"), None)
    with zipfile.ZipFile(snapshot) as z:
        if meta is not None:
            if meta.file_size > 1024 * 1024:
                raise ValueError("Container manifest.json is too large")
            try:
                doc = json.loads(z.read(meta).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Container manifest.json is not valid JSON") from exc
            if isinstance(doc, dict):
                declared_package = doc.get("package_name") if isinstance(doc.get("package_name"), str) else None
                for item in doc.get("split_apks") or []:
                    if isinstance(item, dict) and isinstance(item.get("file"), str):
                        splits[item["file"]] = str(item.get("id", ""))
                declared_base = next((f for f, i in splits.items() if i == "base"), None)
        base_name = _pick_base([i.filename for i in apk_infos], declared_base)
        budget = {"bytes": 0}
        parts = []
        for info in apk_infos:
            path = _extract_member(z, info, staged, budget)
            parts.append(_apk_part(path, info.filename, "base" if info.filename == base_name else "split"))
    obb = [{"path": i.filename, "bytes": i.file_size} for i in infos
           if not i.is_dir() and i.filename.startswith("Android/obb/")]
    return {"parts": parts, "obb": obb, "declared_package": declared_package,
            "split_ids": splits, "association": "manifest.json" if declared_base else "base.apk filename"}


def _intake_directory(snapshot: Path) -> dict:
    files = sorted(p for p in snapshot.rglob("*") if p.is_file() and p.suffix.lower() == ".apk")
    if not files:
        raise ValueError("Split APK set directory contains no .apk files")
    names = [p.relative_to(snapshot).as_posix() for p in files]
    base_name = _pick_base(names, None)
    parts = [_apk_part(p, n, "base" if n == base_name else "split") for p, n in zip(files, names)]
    return {"parts": parts, "obb": [], "declared_package": None, "split_ids": {},
            "association": "base.apk filename"}


def _intake(row: dict) -> dict:
    snapshot = Path(row["snapshot"])
    staged = store.directory(row["id"]) / "apk" / "staged"
    staged.mkdir(parents=True, mode=0o700)
    if snapshot.is_dir():
        fmt, info = "split_set", _intake_directory(snapshot)
    elif snapshot.suffix.lower() in CONTAINER_SUFFIXES:
        fmt, info = "xapk", _intake_container(snapshot, staged)
    else:
        fmt = "apk"
        info = {"parts": [_apk_part(snapshot, snapshot.name, "base")], "obb": [], "declared_package": None,
                "split_ids": {}, "association": "standalone"}
    parts = info["parts"]
    if sum(p["entries"] for p in parts) > MAX_FILES or sum(p["expanded_bytes"] for p in parts) > MAX_BYTES:
        raise ValueError("Archive exceeds expanded size/file limit")
    return {"format": fmt, "base": next(p for p in parts if p["role"] == "base"), **info}


def _custody(row: dict, **times: str) -> None:
    p = store.directory(row["id"]) / "custody.json"
    current = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    apk = row.get("apk") or {}
    container = apk.get("container") or {}
    current.update({"investigation_id": row["id"], "task_id": row.get("task_id"),
                    "source_uri": row.get("source_uri") or row["target"],
                    "source_kind": row.get("source_kind") or "local_path",
                    "source_sha256": container.get("sha256") or row.get("sha256"),
                    "source_bytes": container.get("bytes"), "toolchain": toolchain(),
                    "analyst": "ANZU", "verified_digest": row.get("sha256")})
    if row.get("ffs_investigation_id"):
        current["ffs_investigation_id"] = row["ffs_investigation_id"]
    if row.get("device_serial"):
        current["device_serial"] = row["device_serial"]
    if row.get("package_name"):
        current["package_name"] = row["package_name"]
    current.update(times)
    current["events"] = row["chain_of_custody"]
    store.atomic_json(p, current)


def _coc(row: dict, event: str, details: str, metadata: dict | None = None) -> None:
    chain = row.setdefault("chain_of_custody", [])
    chain.append(make_chain_of_custody_entry(event, row["target"], details, operator=OPERATOR,
                                             metadata=metadata, entry_index=len(chain) + 1))


def _record(row: dict, operation: str, arguments: dict, result: dict, success: bool = True) -> str:
    evidence_id = f"E{len(row['evidence']) + 1:05d}"
    entry = {"id": evidence_id, "operation": operation, "arguments": arguments,
             "target_sha256": row.get("sha256"), "success": success, "result": result}
    p = store.directory(row["id"]) / "evidence"
    p.mkdir(mode=0o700, exist_ok=True)
    store.atomic_json(p / f"{evidence_id}.json", entry)
    row["evidence"].append({"id": evidence_id, "operation": operation, "success": success})
    return evidence_id


MAX_DEVICE_APK_BYTES = 4 * 1024 * 1024 * 1024  # per pulled part; APKs are ZIP32-bounded
MAX_FFS_INDEX_BYTES = 4 * 1024 * 1024 * 1024
MAX_FFS_INDEX_LINE = 64 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_ADB_RUN = None  # tests may replace; production uses _default_adb_run


def _adb_bin() -> Path:
    """Resolve the pinned platform-tools adb; never invent a device bridge."""
    pinned = android.root() / "sdk" / "platform-tools" / ("adb.exe" if os_name_is_windows() else "adb")
    if pinned.is_file():
        return pinned
    which = shutil.which("adb.exe") or shutil.which("adb")
    if which:
        return Path(which)
    raise FileNotFoundError(
        "ADB is unavailable (platform-tools adb not installed); cannot pull from a device. "
        "Run Android REA setup or install platform-tools."
    )


def os_name_is_windows() -> bool:
    import os
    return os.name == "nt"


def _default_adb_run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, capture_output=True, timeout=timeout, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _adb(args: list[str], *, serial: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    bin_path = _adb_bin()
    argv = [str(bin_path)]
    if serial:
        argv.extend(["-s", serial])
    argv.extend(args)
    runner = _ADB_RUN or _default_adb_run
    return runner(argv, timeout)


def _parse_pm_path(output: str) -> list[str]:
    """Parse `adb shell pm path` lines (`package:/data/app/.../base.apk`)."""
    paths: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("package:"):
            remote = line[len("package:"):].strip()
        elif line.startswith("/"):
            remote = line
        else:
            continue
        if not remote or ".." in remote.split("/") or remote.startswith("//"):
            raise ValueError(f"Unsafe device APK path from pm path: {remote!r}")
        paths.append(remote)
    return paths


def _remote_size(remote: str, serial: str | None) -> int:
    """Ask the device for a part's size before pulling it (`stat -c %s`); fail closed on any doubt."""
    import shlex
    try:
        res = _adb(["shell", "stat", "-c", "%s", shlex.quote(remote)], serial=serial, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"ADB stat failed for {remote}: {exc}") from exc
    text = (res.stdout or "").strip()
    if res.returncode != 0 or not text.isdigit():
        err = (res.stderr or res.stdout or "").strip() or f"exit {res.returncode}"
        raise ValueError(f"Could not read the size of device APK {remote} ({err[:200]}); nothing was pulled.")
    return int(text)


def _pull_device_apks(package_name: str, staged: Path, *, serial: str | None) -> tuple[list[Path], list[str]]:
    """Pull base+split APKs for an installed package into staged/. Returns (local paths, unknowns)."""
    unknowns: list[str] = []
    if not _PACKAGE_RE.fullmatch(package_name):
        raise ValueError(f"Invalid Android package name: {package_name!r}")
    try:
        listed = _adb(["shell", "pm", "path", package_name], serial=serial, timeout=60)
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"ADB pm path failed: {exc}") from exc
    if listed.returncode != 0:
        err = (listed.stderr or listed.stdout or "").strip() or f"exit {listed.returncode}"
        raise ValueError(f"ADB pm path failed for {package_name!r}: {err}")
    remotes = _parse_pm_path(listed.stdout or "")
    if not remotes:
        raise ValueError(
            f"Package {package_name!r} is not installed on the device "
            f"(or ADB returned no package: paths); no APK data invented."
        )
    staged.mkdir(parents=True, mode=0o700, exist_ok=True)
    locals_: list[Path] = []
    total = 0
    for remote in remotes:
        name = PurePosixPath(remote).name
        if not name.lower().endswith(".apk"):
            unknowns.append(f"Skipping non-APK device path from pm path: {remote}")
            continue
        dest = staged / name
        if dest.exists():
            raise ValueError(f"Duplicate APK name from device pull: {name}")
        size = _remote_size(remote, serial)
        if size > MAX_DEVICE_APK_BYTES:
            raise ValueError(f"Device APK {remote} is {size} bytes, over the {MAX_DEVICE_APK_BYTES}-byte "
                             "per-file cap; nothing was pulled.")
        if total + size > MAX_BYTES:
            raise ValueError(f"Device APK parts for {package_name!r} exceed the {MAX_BYTES}-byte total cap "
                             f"at {remote}; the pull was refused.")
        total += size
        try:
            pulled = _adb(["pull", remote, str(dest)], serial=serial, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"ADB pull failed for {remote}: {exc}") from exc
        if pulled.returncode != 0 or not dest.is_file():
            err = (pulled.stderr or pulled.stdout or "").strip() or f"exit {pulled.returncode}"
            raise ValueError(f"ADB pull failed for {remote}: {err}")
        actual = dest.stat().st_size
        if actual != size:
            raise ValueError(f"ADB pull of {remote} produced {actual} bytes but the device reported {size}; "
                             "the part changed or the pull was incomplete.")
        locals_.append(dest)
    if not locals_:
        raise ValueError(f"No APK files were pulled for package {package_name!r}")
    return locals_, unknowns


def _norm_ffs_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _scan_ffs_ndjson(index_path: Path, needle: str) -> tuple[list[dict], list[dict]]:
    """Stream index/files.ndjson once and return (exact path matches, unique-basename .apk matches).

    Only matching entries are kept in memory. The file is capped at MAX_FFS_INDEX_BYTES and each
    line at MAX_FFS_INDEX_LINE; exceeding either, or any corrupt line, fails closed.
    """
    if not index_path.is_file():
        raise ValueError(
            f"FFS investigation has no index at {index_path.as_posix()}; "
            "expected index/files.ndjson (RFC-0208)."
        )
    size = index_path.stat().st_size
    if size > MAX_FFS_INDEX_BYTES:
        raise ValueError(f"FFS index is {size} bytes, over the {MAX_FFS_INDEX_BYTES}-byte cap; refused.")
    name = PurePosixPath(needle).name
    exact: list[dict] = []
    by_name: list[dict] = []
    read = 0
    with index_path.open("rb") as fh:
        lineno = 0
        while True:
            raw = fh.readline(MAX_FFS_INDEX_LINE + 1)
            if not raw:
                break
            lineno += 1
            read += len(raw)
            if read > MAX_FFS_INDEX_BYTES:
                raise ValueError(f"FFS index grew past the {MAX_FFS_INDEX_BYTES}-byte cap while reading; refused.")
            if len(raw) > MAX_FFS_INDEX_LINE:
                raise ValueError(f"FFS NDJSON line {lineno} exceeds the {MAX_FFS_INDEX_LINE}-byte line cap; refused.")
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Corrupt FFS NDJSON at line {lineno}: {exc}") from exc
            if not isinstance(obj, dict) or not isinstance(obj.get("path"), str):
                raise ValueError(f"FFS NDJSON line {lineno} is not a file entry with path")
            path = _norm_ffs_path(obj["path"])
            if path == needle:
                exact.append(obj)
            elif PurePosixPath(path).name == name and path.lower().endswith(".apk"):
                by_name.append(obj)
    return exact, by_name


def _reject_links_under(root: Path, rel: str) -> Path:
    """Walk rel component by component from root without resolving; refuse any symlink or reparse point."""
    current = root
    for part in PurePosixPath(rel).parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError as exc:
            raise ValueError(f"FFS entry {rel!r} does not exist under the dump root") from exc
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError(f"Linked/reparse path component {current.relative_to(root).as_posix()!r} "
                                  "inside the FFS dump is not admitted")
    return current


def _resolve_under(root: Path, rel: str) -> Path:
    """Resolve rel under root fail-closed (no escape, no symlink traversal for the final file)."""
    cleaned = rel.replace("\\", "/").lstrip("/")
    pure = PurePosixPath(cleaned)
    if pure.is_absolute() or ".." in pure.parts or ":" in cleaned:
        raise ValueError(f"Unsafe FFS entry path: {rel!r}")
    root_res = root.resolve()
    candidate = (root_res / Path(*pure.parts)).resolve()
    if not candidate.is_relative_to(root_res):
        raise ValueError(f"FFS entry escapes dump root: {rel!r}")
    return candidate


def _ffs_lookup(ffs_investigation_id: str, apk_relpath: str) -> tuple[dict, dict, Path]:
    """Load FFS investigation (kind==ffs), find NDJSON entry, return (ffs_row, entry, absolute source)."""
    try:
        ffs = store.load(ffs_investigation_id)
    except FileNotFoundError as exc:
        raise ValueError(f"Unknown FFS investigation: {ffs_investigation_id}") from exc
    if ffs.get("kind") != "ffs":
        raise ValueError(
            f"Investigation {ffs_investigation_id} has kind={ffs.get('kind')!r}; "
            "APK FFS origin requires kind == 'ffs'."
        )
    dump = Path(ffs["target"]).expanduser()
    if not dump.exists():
        raise ValueError(
            f"FFS dump path {dump} is unavailable; cannot extract APK without inventing bytes."
        )
    needle = _norm_ffs_path(apk_relpath)
    matches, base_matches = _scan_ffs_ndjson(store.directory(ffs_investigation_id) / "index" / "files.ndjson",
                                             needle)
    if not matches:
        # Also accept basename-only match when unique.
        if len(base_matches) == 1 and "/" not in needle.rstrip("/"):
            matches = base_matches
        else:
            raise ValueError(f"No FFS index entry for APK path {apk_relpath!r}")
    if len(matches) != 1:
        raise ValueError(f"Ambiguous FFS index entries for {apk_relpath!r}")
    entry = matches[0]
    expected = entry.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"FFS index entry for {apk_relpath!r} lacks a SHA-256 digest")
    _resolve_under(dump, entry["path"])  # rejects absolute, '..' and escaping paths
    # Walk from the dump root without resolving: a resolved path has already followed any link.
    source = _reject_links_under(dump, _norm_ffs_path(entry["path"]))
    if not stat.S_ISREG(os.lstat(source).st_mode):
        raise ValueError(
            f"FFS entry {entry['path']!r} is not a regular file under the dump root; "
            "archive-only dumps need the APK extracted to the dump tree first."
        )
    return ffs, entry, source


def _blank_apk_row(target_uri: str, question: str, task_id: str | None) -> dict:
    if not question.strip():
        raise ValueError("A specific investigation question is required")
    ident = uuid.uuid4().hex
    workspace = store.directory(ident)
    workspace.mkdir(mode=0o700, exist_ok=True)
    private_directory(workspace)
    return {
        "id": ident, "task_id": task_id, "target": target_uri, "question": question,
        "status": "prepared", "kind": "mobile", "evidence": [], "findings": [],
        "unknowns": [], "chain_of_custody": [], "created_at": _now(),
    }


def _finalize_intake(row: dict, intake: dict, container: dict, *, unknowns: list[str] | None = None) -> dict:
    row.update(kind="mobile", sha256=container["sha256"], apk={
        **intake, "container": container,
        "staged": str(store.directory(row["id"]) / "apk" / "staged"),
    })
    if unknowns:
        row["unknowns"] = list(dict.fromkeys([*row.get("unknowns", []), *unknowns]))
    _coc(row, "source_admitted", f"APK target admitted for static analysis ({intake['format']}).",
         {"sha256": container["sha256"], "bytes": container["bytes"],
          "source_kind": row.get("source_kind"), "source_uri": row.get("source_uri") or row["target"]})
    _coc(row, "apk_unpacked", f"{len(intake['parts'])} APK part(s) validated and hashed.",
         {"parts": [{"name": p["name"], "sha256": p["sha256"]} for p in intake["parts"]]})
    _record(row, "apk_unpack", {"target": row["target"], "source_kind": row.get("source_kind")}, {
        "provider": "ANZU APK sidecar", "format": intake["format"], "container": container,
        "declared_package": intake["declared_package"], "association": intake["association"],
        "parts": [{k: v for k, v in p.items() if k != "path"} for p in intake["parts"]],
        "obb": intake["obb"],
        "source_kind": row.get("source_kind"),
        "ffs_investigation_id": row.get("ffs_investigation_id"),
        "device_serial": row.get("device_serial"),
        "package_name": row.get("package_name"),
        "limitations": ["Static intake only; no target code was executed.",
                        "OBB files are indexed by name and size, not extracted.",
                        "Device/FFS origins never invent missing APK bytes."]})
    _custody(row, ingested_at=_now())
    return store.save(row)


def prepare_apk_from_device(
    package_name: str,
    question: str,
    allowed: list[str],
    task_id: str | None,
    *,
    device_serial: str | None = None,
) -> dict:
    """Pull installed base+split APKs via ADB into apk/staged/ and admit them."""
    del allowed  # device paths are not owner filesystem roots; ADB is the gate
    if not package_name or not package_name.strip():
        raise ValueError("device origin requires package_name")
    package_name = package_name.strip()
    serial = device_serial.strip() if isinstance(device_serial, str) and device_serial.strip() else None
    uri = f"device://{serial or 'default'}/{package_name}"
    row = _blank_apk_row(uri, question, task_id)
    row["source_kind"] = "device_pull"
    row["source_uri"] = uri
    row["package_name"] = package_name
    if serial:
        row["device_serial"] = serial
    try:
        staged = store.directory(row["id"]) / "apk" / "staged"
        locals_, unknowns = _pull_device_apks(package_name, staged, serial=serial)
        # Snapshot is the staged directory of pulled parts (fingerprint for custody).
        digest, manifest = store.fingerprint(staged)
        row["snapshot"] = str(staged)
        row["sha256"] = digest
        row["manifest"] = manifest
        info = _intake_directory(staged)
        if sum(p["entries"] for p in info["parts"]) > MAX_FILES or sum(p["expanded_bytes"] for p in info["parts"]) > MAX_BYTES:
            raise ValueError("Archive exceeds expanded size/file limit")
        multi = len(info["parts"]) > 1
        intake = {
            "format": "split_set" if multi else "apk",
            "base": next(p for p in info["parts"] if p["role"] == "base"),
            **info,
            "association": "adb pm path (base+splits)" if multi else "adb pm path (single)",
        }
        container = {"sha256": digest, "bytes": sum(p["bytes"] for p in intake["parts"])}
        return _finalize_intake(row, intake, container, unknowns=unknowns)
    except BaseException:
        shutil.rmtree(store.directory(row["id"]), ignore_errors=True)
        raise


def prepare_apk_from_ffs(
    ffs_investigation_id: str,
    apk_path: str,
    question: str,
    allowed: list[str],
    task_id: str | None,
) -> dict:
    """Copy one APK referenced by an FFS investigation index/files.ndjson entry and verify SHA-256."""
    if not ffs_investigation_id or not re.fullmatch(r"[a-f0-9]{32}", ffs_investigation_id):
        raise ValueError("ffs origin requires a 32-hex ffs_investigation_id")
    if not apk_path or not str(apk_path).strip():
        raise ValueError("ffs origin requires target (APK path inside the FFS index)")
    ffs, entry, source = _ffs_lookup(ffs_investigation_id, str(apk_path).strip())
    # Ensure dump root is under allowed directories when the owner configured roots.
    resolve_allowed_path(str(Path(ffs["target"]).expanduser()), allowed)
    expected = entry["sha256"].lower()
    uri = f"ffs://{ffs_investigation_id}/{entry['path']}"
    row = _blank_apk_row(uri, question, task_id)
    row["source_kind"] = "ffs_reference"
    row["source_uri"] = uri
    row["ffs_investigation_id"] = ffs_investigation_id
    row["ffs_entry_path"] = entry["path"]
    try:
        dest_dir = store.directory(row["id"]) / "target"
        dest_dir.mkdir(mode=0o700, exist_ok=True)
        dest = dest_dir / PurePosixPath(entry["path"]).name
        if not dest.name.lower().endswith(".apk"):
            raise ValueError(f"FFS entry is not an APK: {entry['path']!r}")
        # Stream copy without loading the dump into RAM; never modify the source.
        size = 0
        h = hashlib.sha256()
        with source.open("rb") as src, dest.open("xb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Archive exceeds expanded size/file limit")
                h.update(chunk)
                dst.write(chunk)
        actual = h.hexdigest()
        if actual != expected:
            raise ValueError(
                f"FFS APK SHA-256 mismatch for {entry['path']!r}: "
                f"index={expected} copied={actual}"
            )
        declared_bytes = entry.get("bytes") if isinstance(entry.get("bytes"), int) else entry.get("size")
        if isinstance(declared_bytes, int) and declared_bytes != size:
            raise ValueError(
                f"FFS APK size mismatch for {entry['path']!r}: index={declared_bytes} copied={size}"
            )
        row["snapshot"] = str(dest)
        row["sha256"] = actual
        row["manifest"] = [{"path": dest.name, "sha256": actual, "bytes": size}]
        # Stage a copy under apk/staged for parity with split pulls, then intake.
        staged = store.directory(row["id"]) / "apk" / "staged"
        staged.mkdir(parents=True, mode=0o700, exist_ok=True)
        staged_apk = staged / dest.name
        shutil.copyfile(dest, staged_apk)
        part = _apk_part(staged_apk, dest.name, "base")
        if part["entries"] > MAX_FILES or part["expanded_bytes"] > MAX_BYTES:
            raise ValueError("Archive exceeds expanded size/file limit")
        intake = {
            "format": "apk",
            "parts": [part],
            "obb": [],
            "declared_package": None,
            "split_ids": {},
            "association": "ffs index/files.ndjson",
            "base": part,
        }
        container = {"sha256": actual, "bytes": size}
        return _finalize_intake(row, intake, container)
    except BaseException:
        shutil.rmtree(store.directory(row["id"]), ignore_errors=True)
        raise


def prepare_apk(
    target: str | None,
    question: str,
    allowed: list[str],
    task_id: str | None,
    *,
    source_type: str = "file",
    device_serial: str | None = None,
    package_name: str | None = None,
    ffs_investigation_id: str | None = None,
) -> dict:
    """Admit an APK from a local path, connected device (ADB), or FFS investigation reference."""
    source_type = (source_type or "file").strip().lower()
    if source_type == "device":
        return prepare_apk_from_device(
            package_name or "", question, allowed, task_id, device_serial=device_serial,
        )
    if source_type == "ffs":
        return prepare_apk_from_ffs(
            ffs_investigation_id or "", target or "", question, allowed, task_id,
        )
    if source_type != "file":
        raise ValueError("source_type must be 'file', 'device', or 'ffs'")
    if not target or not str(target).strip():
        raise ValueError("file origin requires target path")
    raw = Path(target).expanduser()
    if not raw.is_dir() and raw.suffix.lower() not in APK_SUFFIXES:
        raise ValueError("APK target must be a .apk, .xapk or .apks file, or a split-APK directory")
    row = store.prepare(target, question, allowed, task_id)
    row["source_kind"] = "local_path"
    row["source_uri"] = row["target"]
    try:
        intake = _intake(row)
        snapshot = Path(row["snapshot"])
        container = ({"sha256": row["sha256"], "bytes": sum(p["bytes"] for p in intake["parts"])}
                     if snapshot.is_dir() else dict(zip(("sha256", "bytes"), _hash_file(snapshot))))
        return _finalize_intake(row, intake, container)
    except BaseException:
        shutil.rmtree(store.directory(row["id"]), ignore_errors=True)
        raise


# --- Decompile orchestration -----------------------------------------------------------

def cancel(ident: str) -> None:
    """Stop a running decompile: SIGTERM the tool's process tree in WSL, SIGKILL after 10 s."""
    import time
    event = _CANCEL.get(ident)
    if event is None:
        return
    event.set()
    for signal in ("-TERM", "-KILL"):
        for pidfile in list(_RUNNING.get(ident, [])):
            try:
                pid = pidfile.read_text(encoding="ascii").strip()
            except OSError as exc:
                log.warning("Cancel %s: pid file %s unreadable (%s); that tool may keep running", ident, pidfile, exc)
                continue
            if not pid.isdigit() or int(pid) < 2:
                log.warning("Cancel %s: pid file %s holds %r, not a PID; not signalling", ident, pidfile, pid)
                continue
            try:
                # coreutils timeout leads its own process group; signal the whole group by PID.
                result = _wsl(["kill", signal, "--", f"-{pid}"], 30)
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.warning("Cancel %s: kill %s -%s failed: %s", ident, signal, pid, exc)
                continue
            if result.returncode:
                log.warning("Cancel %s: kill %s -%s exited %s: %s", ident, signal, pid, result.returncode,
                            result.stderr.decode("utf-8", errors="replace")[-300:])
        deadline = time.monotonic() + KILL_GRACE
        while _RUNNING.get(ident) and time.monotonic() < deadline:
            time.sleep(0.2)
        if not _RUNNING.get(ident):
            return


def _run_tool(ident: str, name: str, argv: list[str], seconds: int, out: Path) -> dict:
    """Run one tool under coreutils timeout: SIGTERM at the deadline, SIGKILL after 10 s.

    The fixed sh prologue writes its PID (which exec hands to timeout) to a pid file so
    cancel() can signal exactly this process group; argv is passed as "$@", never parsed.
    """
    if _CANCEL[ident].is_set():
        raise DecompileCancelled(name)
    pidfile = out.parent / f".{name}.pid"
    pidfile.unlink(missing_ok=True)
    wrapped = ["sh", "-c", 'echo $$ > "$0"; exec "$@"', _linux_path(pidfile),
               "timeout", f"--kill-after={KILL_GRACE}s", f"{seconds}s", *argv]
    _RUNNING.setdefault(ident, []).append(pidfile)
    try:
        result = _wsl(wrapped, seconds + KILL_GRACE + 30)
        code = result.returncode
        text = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        code, text = 124, ""
    finally:
        _RUNNING[ident].remove(pidfile)
        pidfile.unlink(missing_ok=True)
    if _CANCEL[ident].is_set():
        out.mkdir(parents=True, exist_ok=True)
        (out / ".incomplete").write_text(f"{name} cancelled\n", encoding="utf-8")
        raise DecompileCancelled(name)
    if code and "OutOfMemoryError" in text:
        state = "out_of_memory"
    elif code in (124, 137):
        state = "timeout"
    elif code:
        state = "failed"
    else:
        state = "ok"
    if state != "ok":
        out.mkdir(parents=True, exist_ok=True)
        (out / ".incomplete").write_text(f"{name} {state} (exit {code})\n", encoding="utf-8")
    return {"tool": name, "state": state, "exit_code": code, "timeout_seconds": seconds,
            "error_lines": sum(1 for line in text.splitlines() if "ERROR" in line),
            "diagnostics": text[-4000:]}


def _claim(ident: str, purpose: str) -> dict:
    """Atomically claim the investigation (status -> analyzing) under a fresh per-claim token.

    The returned row carries ``_claim_token`` (never persisted). Only that token can release
    or finish the claim, so a late release from an earlier claim cannot interrupt a newer one.
    """
    with _CLAIM_LOCK:
        row = store.load(ident)
        if not row.get("apk"):
            raise ValueError("Investigation was not prepared as an APK target")
        # A reported investigation is final: further runs would rewrite the status of a published report.
        if row["status"] in {"cancelled", "closed", "reported", "analyzing"} or ident in _CLAIMS:
            raise ValueError(f"Investigation is {row['status']}; cannot start {purpose}")
        store.validate_snapshot(row)
        row["status"] = "analyzing"
        token = uuid.uuid4().hex
        saved = store.save(row)
        _CLAIMS[ident] = token
        _CANCEL[ident] = threading.Event()
    return {**saved, "_claim_token": token}


def preflight(ident: str) -> dict:
    """Check the static toolchain, then claim the investigation for one decompile."""
    ready = readiness_static()
    if ready["status"] != "ready":
        raise RuntimeError(ready.get("error") or "Static APK toolchain is not ready")
    return _claim(ident, "decompilation")


def release(ident: str, token: str | None = None) -> None:
    """Undo a claim no operation took over. No-op while an operation owns it, when the claim is
    already finished, or when ``token`` belongs to an earlier claim."""
    with _CLAIM_LOCK:
        current = _CLAIMS.get(ident)
        if ident in _OWNED or current is None or (token is not None and token != current):
            return
        row = store.load(ident)
        if row["status"] == "analyzing":
            row["status"] = "interrupted"
            row["last_error"] = "Operation was claimed but never started"
            store.save(row)
        _CLAIMS.pop(ident, None)
        _CANCEL.pop(ident, None)


def _finish_failed(ident: str, token: str, step: str, status: str, error: str) -> None:
    with _CLAIM_LOCK:
        if _CLAIMS.get(ident) != token:
            return
        row = store.load(ident)
        row.update(status=status, last_error=error)
        _coc(row, f"{step}_{status}", error[:500])
        store.save(row)
        _CLAIMS.pop(ident, None)



_JADX_FAILED_CLASS = re.compile(
    r"(?:Failed to (?:process|decompile) class |Can't load class |Error (?:processing|decompiled) class )"
    r"([A-Za-z0-9_$/\.]+;?)",
    re.I,
)
_DEX_DESCRIPTOR = re.compile(r"L[A-Za-z0-9_$/]+;")


def _jadx_failed_classes(diagnostics: str, limit: int = 50) -> list[str]:
    """Best-effort parse of class names jadx reported as failed (honest coverage)."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _JADX_FAILED_CLASS.finditer(diagnostics or ""):
        name = match.group(1)
        if _DEX_DESCRIPTOR.fullmatch(name):
            name = name[1:-1]  # Lcom/x/Y; -> com/x/Y (only the descriptor form)
        name = name.replace("/", ".")
        if name and name not in seen:
            seen.add(name)
            found.append(name)
            if len(found) >= limit:
                break
    return found


def _should_run_smali_fallback(*, enabled: bool, has_dex: bool, skip_jadx: bool,
                               jadx: dict | None) -> tuple[bool, str]:
    """Decide whether to recover smali via apktool without --no-src.

    Catastrophic jadx outcomes and an explicit skip_jadx (with the fallback flag on) both
    request smali so the investigation still has bytecode to inspect.
    """
    if not enabled:
        return False, "disabled"
    if not has_dex:
        return False, "no_dex"
    if skip_jadx:
        return True, "jadx_skipped"
    if not jadx:
        return False, "no_jadx"
    state = jadx.get("state")
    if state in {"failed", "timeout", "out_of_memory"}:
        return True, f"jadx_{state}"
    if state == "skipped":
        return False, "jadx_skipped_no_dex"
    if int(jadx.get("java_files") or 0) == 0:
        return True, "no_useful_java"
    return False, "jadx_ok"


_SMALI_CLASS = re.compile(rb"^[ \t]*\.class\b", re.M)


def _count_smali(smali_out: Path) -> dict:
    """Count recovered .smali files and the ``.class`` directives they contain."""
    if not smali_out.exists():
        return {"smali_files": 0, "smali_classes": 0, "smali_roots": [], "unreadable": []}
    files = [p for p in smali_out.rglob("*.smali") if p.is_file()]
    classes = 0
    unreadable: list[str] = []
    for f in files:
        try:
            classes += len(_SMALI_CLASS.findall(f.read_bytes()))
        except OSError as exc:
            # Reported by the caller as an unknown; its classes are not counted.
            unreadable.append(f"{f.relative_to(smali_out).as_posix()} ({exc.strerror or exc})")
    roots = sorted({p.relative_to(smali_out).parts[0] for p in files if p.relative_to(smali_out).parts})
    return {"smali_files": len(files), "smali_classes": classes, "smali_roots": roots, "unreadable": unreadable}


def _part_dir_name(name: str) -> str:
    """Directory name for one APK part under apk/smali/ (no separators, never '.' or '..')."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return safe if safe not in {"", ".", ".."} else "_part"


def _run_smali_fallback(ident: str, base: Path, smali_out: Path) -> dict:
    """Phase-A companion: apktool without --no-src, --no-res, into apk/smali/.

    Resources stay in apk/apktool (Phase A); this pass only recovers smali disassembly.
    """
    if smali_out.exists():
        shutil.rmtree(smali_out)
    run = _run_tool(ident, "apktool-smali", [
        "env", f"JAVA_HOME={JAVA_HOME}", f"PATH={JAVA_HOME}/bin:/usr/bin:/bin", JDK, *JVM_HEAP,
        "-jar", APKTOOL_JAR, "d", "-f", "--no-res", "-o", _linux_path(smali_out), _linux_path(base)],
        APKTOOL_TIMEOUT, smali_out)
    counts = _count_smali(smali_out)
    run.update(counts)
    run["smali_output"] = str(smali_out)
    run["ran"] = True
    return run


def decompile(ident: str, skip_jadx: bool = False, decompile_smali_fallback: bool = True,
             claimed: dict | None = None) -> dict:
    """apktool (resources/manifest) then jadx (DEX), with smali fallback on jadx failure.

    `claimed` is the row returned by preflight(); without it the claim is taken here.
    When jadx fails catastrophically (or is skipped) and `decompile_smali_fallback` is
    true, apktool is re-run without `--no-src` into `apk/smali/`.
    """
    row = dict(claimed) if claimed is not None else preflight(ident)
    token = row.pop("_claim_token", None)
    with _CLAIM_LOCK:
        _OWNED.add(ident)
    try:
        return _decompile_owned(ident, skip_jadx, decompile_smali_fallback, row)
    finally:
        with _CLAIM_LOCK:
            _OWNED.discard(ident)
            if token is not None and _CLAIMS.get(ident) == token:
                _CLAIMS.pop(ident, None)


def _decompile_owned(ident: str, skip_jadx: bool, decompile_smali_fallback: bool, row: dict) -> dict:
    with _DECOMPILE_SLOTS:
        work = store.directory(ident) / "apk"
        apktool_out, jadx_out, smali_out, meta = (
            work / "apktool", work / "jadx", work / "smali", work / "metadata")
        _coc(row, "decompile_started", "apktool/jadx static decompilation started.",
             {"skip_jadx": skip_jadx, "decompile_smali_fallback": decompile_smali_fallback})
        store.save(row)
        try:
            for d in (apktool_out, jadx_out, smali_out):
                if d.exists():
                    shutil.rmtree(d)
            meta.mkdir(mode=0o700, exist_ok=True)
            base = Path(row["apk"]["base"]["path"])
            unknowns: list[str] = []
            apktool = _run_tool(ident, "apktool", [
                "env", f"JAVA_HOME={JAVA_HOME}", f"PATH={JAVA_HOME}/bin:/usr/bin:/bin", JDK, *JVM_HEAP,
                "-jar", APKTOOL_JAR, "d", "-f", "--no-src", "-o", _linux_path(apktool_out), _linux_path(base)],
                APKTOOL_TIMEOUT, apktool_out)
            if apktool["state"] != "ok":
                unknowns.append(f"apktool resource decoding {apktool['state']} (exit {apktool['exit_code']}); "
                                "manifest, permissions and components may be unavailable.")
            jadx = None
            inputs = [Path(p["path"]) for p in row["apk"]["parts"] if p["dex"]]
            failed_classes: list[str] = []
            if not skip_jadx and not inputs:
                jadx = {"tool": "jadx", "state": "skipped", "reason": "No classes*.dex in any APK part; nothing to decompile.",
                        "java_files": 0, "inputs": []}
            elif not skip_jadx:
                jadx = _run_tool(ident, "jadx", [
                    "env", f"JAVA_HOME={JAVA_HOME}", f"PATH={JAVA_HOME}/bin:/usr/bin:/bin",
                    "JAVA_OPTS=" + " ".join(JVM_HEAP), JADX, "--no-res", "-d", _linux_path(jadx_out),
                    "--threads-count", "4", "--show-bad-code", "--escape-unicode",
                    *[_linux_path(p) for p in inputs]], JADX_TIMEOUT, jadx_out)
                jadx["java_files"] = sum(1 for _ in jadx_out.rglob("*.java")) if jadx_out.exists() else 0
                jadx["inputs"] = [p.name for p in inputs]
                failed_classes = _jadx_failed_classes(jadx.get("diagnostics") or "")
                jadx["failed_classes"] = failed_classes
                if jadx["state"] == "timeout":
                    unknowns.append(f"jadx timed out after {JADX_TIMEOUT} s and was terminated; "
                                    f"Java coverage is partial ({jadx['java_files']} files recovered).")
                elif jadx["state"] == "out_of_memory":
                    unknowns.append("jadx exhausted its 4 GiB heap; Java coverage is partial.")
                elif jadx["state"] == "failed":
                    unknowns.append(f"jadx exited {jadx['exit_code']} with {jadx['error_lines']} error line(s); "
                                    "some classes were not decompiled.")
                elif failed_classes:
                    sample = ", ".join(failed_classes[:5])
                    suffix = "…" if len(failed_classes) > 5 else ""
                    unknowns.append(
                        f"jadx reported {len(failed_classes)} class failure(s) "
                        f"(e.g. {sample}{suffix}); "
                        "Java coverage for those classes is incomplete.")
            smali: dict | None = None
            run_smali, smali_reason = _should_run_smali_fallback(
                enabled=decompile_smali_fallback, has_dex=bool(inputs), skip_jadx=skip_jadx, jadx=jadx)
            if run_smali:
                smali_out.mkdir(parents=True, mode=0o700, exist_ok=True)
                parts_out: list[dict] = []
                used: set[str] = set()
                for part in row["apk"]["parts"]:
                    if not part.get("dex"):
                        # No DEX means no bytecode to disassemble; listed, not an unknown.
                        parts_out.append({"part": part["name"], "state": "skipped", "reason": "no_dex",
                                          "smali_files": 0, "smali_classes": 0})
                        continue
                    sub = _part_dir_name(part["name"])
                    candidate, n = sub, 1
                    while candidate in used:  # sanitised names can collide; never reuse a directory
                        candidate = f"{sub}_{n}"
                        n += 1
                    sub = candidate
                    used.add(sub)
                    run = _run_smali_fallback(ident, Path(part["path"]), smali_out / sub)
                    entry = {"part": part["name"], "state": run["state"], "exit_code": run.get("exit_code"),
                             "smali_output": run["smali_output"], "smali_files": run["smali_files"],
                             "smali_classes": run["smali_classes"], "smali_roots": run["smali_roots"]}
                    parts_out.append(entry)
                    for bad in run.get("unreadable") or []:
                        unknowns.append(f"smali file {sub}/{bad} could not be read; its classes were not counted.")
                    if run["state"] != "ok":
                        unknowns.append(
                            f"smali fallback {run['state']} for {part['name']} (exit {run['exit_code']}; "
                            f"reason: {smali_reason}); bytecode disassembly of that part is unavailable.")
                    elif not run["smali_files"]:
                        unknowns.append(f"smali fallback ran for {part['name']} ({smali_reason}) but produced "
                                        "no .smali files.")
                ran = [e for e in parts_out if e["state"] != "skipped"]
                states = {e["state"] for e in ran}
                smali = {"tool": "apktool-smali", "ran": True, "reason": smali_reason,
                         "state": "ok" if states == {"ok"} else next(
                             s for s in ("failed", "timeout", "out_of_memory", "ok") if s in states),
                         "exit_code": next((e["exit_code"] for e in ran if e["state"] != "ok"), 0),
                         "smali_output": str(smali_out), "parts": parts_out,
                         "smali_files": sum(e["smali_files"] for e in ran),
                         "smali_classes": sum(e["smali_classes"] for e in ran),
                         "smali_roots": sorted(f"{PurePosixPath(e['smali_output']).name}/{r}"
                                               for e in ran for r in e.get("smali_roots") or [])}
                if failed_classes:
                    smali["failed_java_classes"] = failed_classes
                if jadx and jadx.get("state") == "ok" and not jadx.get("java_files"):
                    unknowns.append("jadx produced no Java; smali recovered." if smali["smali_files"] else
                                    "jadx produced no Java; no bytecode disassembly available.")
                store.atomic_json(meta / "smali.json", {
                    "ran": True, "reason": smali_reason, "state": smali["state"],
                    "exit_code": smali.get("exit_code"), "smali_output": smali.get("smali_output"),
                    "smali_files": smali.get("smali_files", 0),
                    "smali_classes": smali.get("smali_classes", 0),
                    "smali_roots": smali.get("smali_roots") or [],
                    "parts": parts_out,
                    "failed_java_classes": failed_classes,
                    "limitations": [
                        "Smali is apktool disassembly, not original source.",
                        "No target code was executed.",
                    ],
                })
                _coc(row, "smali_fallback_completed",
                     f"Smali fallback {smali['state']}: {smali.get('smali_files', 0)} file(s).",
                     {"reason": smali_reason, "smali_files": smali.get("smali_files", 0),
                      "state": smali["state"]})
            else:
                if jadx and jadx.get("state") == "ok" and not jadx.get("java_files"):
                    unknowns.append("jadx produced no Java; no bytecode disassembly available.")
                store.atomic_json(meta / "smali.json", {
                    "ran": False, "reason": smali_reason, "state": "skipped",
                    "smali_files": 0, "smali_classes": 0, "smali_roots": [],
                    "failed_java_classes": failed_classes,
                })
            manifest_eid = None
            manifest_file = apktool_out / "AndroidManifest.xml"
            decoder = f"apktool {toolchain()['apktool']}"
            if not manifest_file.is_file():
                try:
                    with zipfile.ZipFile(base) as z:
                        info = z.getinfo("AndroidManifest.xml")
                        if info.file_size > MAX_MANIFEST_BYTES:
                            raise ValueError("binary manifest exceeds 16 MiB")
                        axml_text = decode_axml(z.read(info))
                    manifest_file = meta / "AndroidManifest.decoded.xml"
                    manifest_file.write_text(axml_text, encoding="utf-8")
                    decoder = "ANZU host AXML decoder"
                    unknowns.append("Manifest was decoded by the host AXML decoder; resource references stay unresolved (@0x...).")
                except (ValueError, KeyError) as exc:
                    unknowns.append(f"Host AXML decoder could not read the binary manifest: {exc}")
            if manifest_file.is_file():
                try:
                    manifest, components = parse_manifest(manifest_file, apktool_out / "apktool.yml")
                except ValueError as exc:
                    unknowns.append(f"Decoded AndroidManifest.xml could not be parsed: {exc}")
                else:
                    store.atomic_json(meta / "manifest.json", manifest)
                    store.atomic_json(meta / "components.json", components)
                    manifest_eid = _record(row, "apk_manifest", {"source": "apktool/AndroidManifest.xml"}, {
                        "provider": decoder, "manifest": manifest,
                        "components": components,
                        "limitations": ["Static manifest parsing only; runtime authorization checks in code were not evaluated.",
                                        "Implicit export follows pre-Android 12 rules: an intent-filter without android:exported means exported."]})
            succeeded = (apktool["state"] == "ok"
                         or bool(jadx and jadx.get("java_files"))
                         or bool(smali and smali.get("smali_files")))
            decompile_eid = _record(row, "apk_decompile", {
                "skip_jadx": skip_jadx, "decompile_smali_fallback": decompile_smali_fallback}, {
                "provider": "ANZU APK sidecar", "toolchain": toolchain(), "apktool": apktool, "jadx": jadx,
                "smali_fallback": smali,
                "apktool_output": str(apktool_out), "jadx_output": str(jadx_out) if jadx else None,
                "smali_output": str(smali_out) if smali else None,
                "manifest_evidence": manifest_eid,
                "limitations": ["Recovered Java is decompiler output, not original source.",
                                "Smali is apktool disassembly when the fallback ran.",
                                "No target code was executed."]}, success=succeeded)
            row["unknowns"] = list(dict.fromkeys([*row.get("unknowns", []), *unknowns]))
            row["status"] = "partial" if unknowns else "investigating"
            row.pop("last_error", None)
            _coc(row, "decompile_completed", "Static decompilation finished.",
                 {"evidence": [e for e in (manifest_eid, decompile_eid) if e], "unknowns": len(unknowns),
                  "smali_fallback": bool(smali)})
            stamp = _now()
            custody_kw = {"decompiled_at": stamp, "completed_at": stamp}
            if smali:
                custody_kw["smali_fallback_at"] = stamp
            _custody(row, **custody_kw)
            return store.save(row)
        except DecompileCancelled as exc:
            row.update(status="cancelled", last_error=f"Cancelled while {exc} was running")
            _coc(row, "decompile_cancelled", f"Cancelled during {exc}; partial output marked .incomplete.")
            store.save(row)
            raise
        except BaseException as exc:
            row.update(status="interrupted", last_error=str(exc)[:2000])
            store.save(row)
            raise
        finally:
            _CANCEL.pop(ident, None)
            _RUNNING.pop(ident, None)


# --- Host binary AXML decoder (fallback when apktool cannot decode the manifest) -------

_AXML_ATTR_IDS = {0x01010003: "name", 0x01010001: "label", 0x01010010: "exported", 0x0101021b: "versionCode",
                  0x0101021c: "versionName", 0x0101020c: "minSdkVersion", 0x01010270: "targetSdkVersion",
                  0x01010271: "maxSdkVersion", 0x01010006: "permission", 0x01010018: "authorities",
                  0x01010007: "readPermission", 0x01010008: "writePermission", 0x01010009: "protectionLevel",
                  0x0101000f: "debuggable", 0x01010280: "allowBackup", 0x010104ec: "usesCleartextTraffic",
                  0x01010527: "networkSecurityConfig", 0x01010202: "targetActivity",
                  0x01010028: "scheme", 0x01010029: "host", 0x0101002a: "path"}


def _axml_strings(buf: bytes, off: int) -> list[str]:
    import struct
    _, header, size, count, _styles, flags, start, _ = struct.unpack_from("<HHIIIIII", buf, off)
    utf8 = bool(flags & 0x100)
    out = []
    for i in range(count):
        p = off + start + struct.unpack_from("<I", buf, off + header + 4 * i)[0]
        if utf8:
            p += 2 if buf[p] & 0x80 else 1
            n = buf[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | buf[p + 1]
                p += 1
            p += 1
            out.append(buf[p:p + n].decode("utf-8", errors="replace"))
        else:
            n = struct.unpack_from("<H", buf, p)[0]
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p + 2)[0]
                p += 2
            out.append(buf[p + 2:p + 2 + 2 * n].decode("utf-16-le", errors="replace"))
    return out


def decode_axml(buf: bytes) -> str:
    """Decode Android binary XML into text XML; structure only, no resource-table lookups."""
    import struct
    from xml.sax.saxutils import escape, quoteattr
    if len(buf) < 8 or struct.unpack_from("<HH", buf, 0) != (0x0003, 8):
        raise ValueError("not an Android binary XML document")
    if len(buf) > MAX_MANIFEST_BYTES:
        raise ValueError("binary manifest exceeds 16 MiB")
    strings: list[str] = []
    res_ids: list[int] = []

    def sref(index: int) -> str:
        if not 0 <= index < len(strings):
            raise ValueError(f"binary XML string index {index} is out of range")
        return strings[index]
    prefixes: dict[str, str] = {}
    out = ['<?xml version="1.0" encoding="utf-8"?>']
    pending_ns: list[tuple[str, str]] = []
    off = 8
    try:
        while off + 8 <= len(buf):
            ctype, header, size = struct.unpack_from("<HHI", buf, off)
            if size < 8 or off + size > len(buf):
                raise ValueError("truncated binary XML chunk")
            if ctype == 0x0001:
                strings = _axml_strings(buf, off)
            elif ctype == 0x0180:
                res_ids = list(struct.unpack_from(f"<{(size - header) // 4}I", buf, off + header))
            elif ctype == 0x0100:
                prefix, uri = struct.unpack_from("<ii", buf, off + 16)
                prefixes[sref(uri)] = sref(prefix)
                pending_ns.append((sref(prefix), sref(uri)))
            elif ctype == 0x0102:
                ns, name, _attr_start, attr_size, count = struct.unpack_from("<iiHHH", buf, off + 16)[:5]
                attrs = [f"xmlns:{p}={quoteattr(u)}" for p, u in pending_ns]
                pending_ns = []
                base = off + 16 + _attr_start
                for i in range(count):
                    a_ns, a_name, a_raw, _vsize, _r, vtype, vdata = struct.unpack_from("<iiiHBBI", buf, base + i * attr_size)
                    key = strings[a_name] if 0 <= a_name < len(strings) else ""
                    if not key and 0 <= a_name < len(res_ids):
                        key = _AXML_ATTR_IDS.get(res_ids[a_name], f"attr_{res_ids[a_name]:08x}")
                    if a_ns != -1:
                        key = f"{prefixes.get(sref(a_ns), 'ns')}:{key}"
                    if a_raw != -1:
                        value = sref(a_raw)
                    elif vtype == 0x03:
                        value = sref(vdata)
                    elif vtype == 0x12:
                        value = "true" if vdata else "false"
                    elif vtype == 0x10:
                        value = str(vdata if vdata < 0x80000000 else vdata - 0x100000000)
                    elif vtype == 0x11:
                        value = f"0x{vdata:08x}"
                    elif vtype == 0x01:
                        value = f"@0x{vdata:08x}"
                    else:
                        value = f"0x{vdata:08x}"
                    attrs.append(f"{key}={quoteattr(value)}")
                tag = sref(name)
                out.append(f"<{tag}{' ' if attrs else ''}{' '.join(attrs)}>")
            elif ctype == 0x0103:
                out.append(f"</{sref(struct.unpack_from('<ii', buf, off + 16)[1])}>")
            elif ctype == 0x0104:
                out.append(escape(sref(struct.unpack_from("<i", buf, off + 16)[0])))
            off += size
    except (struct.error, IndexError) as exc:
        raise ValueError("malformed binary XML") from exc
    return "\n".join(out) + "\n"


# --- Manifest extraction ---------------------------------------------------------------

def _bool(value: str | None) -> bool | None:
    return None if value is None else value.strip().lower() == "true"


def _yml_versions(path: Path) -> dict:
    if not path.is_file():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.fullmatch(r"\s+(minSdkVersion|targetSdkVersion|maxSdkVersion|versionCode|versionName):\s*'?([^'\n]*?)'?\s*", line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def _qualify(name: str | None, package: str) -> str | None:
    if not name:
        return name
    if name.startswith("."):
        return package + name
    return name if "." in name else f"{package}.{name}"


def parse_manifest(path: Path, apktool_yml: Path | None = None) -> tuple[dict, dict]:
    """Parse apktool's decoded AndroidManifest.xml into manifest and component documents."""
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("decoded manifest exceeds 16 MiB")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("decoded manifest declares a DTD or entities")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(str(exc)) from exc
    if root.tag != "manifest":
        raise ValueError("no <manifest> root element")

    def a(el, key):
        return None if el is None else el.get(_ANDROID + key)

    package = root.get("package") or ""
    yml = _yml_versions(apktool_yml) if apktool_yml else {}
    sdk = root.find("uses-sdk")
    app = root.find("application")
    flags = {"debuggable": _bool(a(app, "debuggable")), "allow_backup": _bool(a(app, "allowBackup")),
             "uses_cleartext_traffic": _bool(a(app, "usesCleartextTraffic")),
             "network_security_config": a(app, "networkSecurityConfig"),
             "request_legacy_external_storage": _bool(a(app, "requestLegacyExternalStorage"))}
    alerts = []
    if flags["debuggable"]:
        alerts.append({"flag": "debuggable", "severity": "critical", "detail": "android:debuggable is true"})
    if flags["allow_backup"]:
        alerts.append({"flag": "allow_backup", "severity": "warning", "detail": "adb backup can extract app data"})
    if flags["uses_cleartext_traffic"]:
        alerts.append({"flag": "uses_cleartext_traffic", "severity": "warning", "detail": "unencrypted HTTP is permitted"})
    if flags["request_legacy_external_storage"]:
        alerts.append({"flag": "request_legacy_external_storage", "severity": "info", "detail": "scoped storage opt-out"})

    requested = sorted({a(el, "name") for tag in ("uses-permission", "uses-permission-sdk-23")
                        for el in root.findall(tag) if a(el, "name")})
    high_risk = []
    for perm in requested:
        short = perm.rsplit(".", 1)[-1]
        for category, names in HIGH_RISK_PERMISSIONS.items():
            if perm.startswith("android.permission.") and short in names:
                high_risk.append({"name": perm, "category": category})
    declared = [{"name": a(el, "name"), "protection_level": a(el, "protectionLevel") or "normal"}
                for el in root.findall("permission")]

    app_permission = a(app, "permission")
    items = []
    for tag, kind in COMPONENT_TAGS.items():
        for el in (app.findall(tag) if app is not None else []):
            filters = []
            for f in el.findall("intent-filter"):
                filters.append({"actions": [a(x, "name") for x in f.findall("action")],
                                "categories": [a(x, "name") for x in f.findall("category")],
                                "data": [{k: a(x, k) for k in ("scheme", "host", "port", "path", "pathPrefix", "pathPattern", "mimeType") if a(x, k)}
                                         for x in f.findall("data")]})
            explicit = _bool(a(el, "exported"))
            exported = explicit if explicit is not None else bool(filters)
            permission = a(el, "permission") or app_permission
            item = {"type": kind, "tag": tag, "name": _qualify(a(el, "name"), package), "exported": exported,
                    "exported_source": "explicit" if explicit is not None else ("implicit_intent_filter" if filters else "default"),
                    "permission": permission, "intent_filters": filters}
            if kind == "provider":
                item.update(authorities=a(el, "authorities"), read_permission=a(el, "readPermission"),
                            write_permission=a(el, "writePermission"),
                            grant_uri_permissions=_bool(a(el, "grantUriPermissions")))
                protected = bool(permission) or bool(item["read_permission"] and item["write_permission"])
            else:
                protected = bool(permission)
            if tag == "activity-alias":
                item["target_activity"] = _qualify(a(el, "targetActivity"), package)
            item["protected"] = protected
            items.append(item)
    exported = [c for c in items if c["exported"]]
    surface = {"total": len(items), "exported": len(exported),
               "exported_unprotected_count": sum(1 for c in exported if not c["protected"]),
               "by_type": {k: {"total": sum(1 for c in items if c["type"] == k),
                               "exported": sum(1 for c in exported if c["type"] == k)}
                           for k in ("activity", "service", "receiver", "provider")}}
    manifest = {"package": package,
                "version_code": a(root, "versionCode") or yml.get("versionCode"),
                "version_name": a(root, "versionName") or yml.get("versionName"),
                "min_sdk": a(sdk, "minSdkVersion") or yml.get("minSdkVersion"),
                "target_sdk": a(sdk, "targetSdkVersion") or yml.get("targetSdkVersion"),
                "max_sdk": a(sdk, "maxSdkVersion") or yml.get("maxSdkVersion"),
                "install_location": a(root, "installLocation"), "shared_user_id": a(root, "sharedUserId"),
                "application": flags, "alerts": alerts,
                "permissions": {"declared": declared, "requested": requested, "high_risk": high_risk},
                "attack_surface": surface}
    return manifest, {"package": package, "components": items, "attack_surface": surface}


# --- Static analysis steps (shared guard) --------------------------------------------------

@contextmanager
def _static_op(ident: str, step: str, claimed: dict | None = None):
    """Hold the investigation claim for one in-process static step (endpoints, crypto hints).

    Uses the same claim as decompile and native inventory, so it is refused while any of them is
    analyzing and never interleaves evidence ids or custody entries with them. Yields the claimed
    row for reading; results are written through _commit_step(), which reloads the row first.
    """
    claim = claimed if claimed is not None else _claim(ident, step.replace("_", " "))
    token = claim["_claim_token"]
    with _CLAIM_LOCK:
        _OWNED.add(ident)
    try:
        yield {k: v for k, v in claim.items() if k != "_claim_token"}, token
    except DecompileCancelled as exc:
        _finish_failed(ident, token, step, "cancelled", f"Cancelled during {exc}")
        raise
    except BaseException as exc:
        _finish_failed(ident, token, step, "interrupted", str(exc)[:2000])
        raise
    finally:
        with _CLAIM_LOCK:
            _OWNED.discard(ident)
            if _CLAIMS.get(ident) is None or _CLAIMS.get(ident) == token:
                _CANCEL.pop(ident, None)


def _commit_step(ident: str, token: str, unknowns: list[str], write,
                 files: dict[str, dict] | None = None) -> dict:
    """Reload the row under the claim lock, verify the claim, let ``write`` add evidence and custody,
    set status from the merged unknowns, save and finish the claim. Returns the saved row.

    ``files`` (name -> document under apk/metadata/) are written only after the claim is verified
    and the evidence recorded, and restored to their previous contents if the row cannot be saved,
    so metadata never describes unrecorded results (same contract as native.json)."""
    with _CLAIM_LOCK:
        row = store.load(ident)
        if _CLAIMS.get(ident) != token:
            raise RuntimeError("Investigation claim was lost; results were not recorded")
        write(row)
        _settle(row, unknowns)
        row.pop("last_error", None)
        previous = _write_step_metadata(store.directory(ident) / "apk" / "metadata", files or {})
        try:
            store.save(row)
        except BaseException:
            _rollback_metadata(previous)
            raise
        _CLAIMS.pop(ident, None)
        return row


def _settle(row: dict, unknowns: list[str]) -> None:
    """Merge step unknowns into the row; status follows the merged unknowns."""
    row["unknowns"] = list(dict.fromkeys([*row.get("unknowns", []), *unknowns]))
    row["status"] = "partial" if row["unknowns"] else "investigating"


def _optional_metadata(ident: str, name: str, unknowns: list[str] | None = None) -> dict | None:
    """Load a metadata document that may not exist yet.

    A missing document is a normal ``None``. A document that exists but is corrupt is never
    silently treated as missing: with ``unknowns`` the problem is recorded there (and ``None``
    returned so the step can continue with explicit coverage loss); without it, ValueError is raised.
    """
    try:
        return metadata(ident, name)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        problem = (f"APK metadata {METADATA_DOCUMENTS[name]}.json is corrupt ({exc.__class__.__name__}: "
                   f"{str(exc)[:200]}); results that depend on it are unknown.")
        if unknowns is None:
            raise ValueError(problem) from exc
        log.warning("Investigation %s: %s", ident, problem)
        unknowns.append(problem)
        return None


def _write_step_metadata(meta: Path, docs: dict[str, dict]) -> list[tuple[Path, bytes | None]]:
    """Write step metadata files and return what they replaced, for rollback if the save fails."""
    meta.mkdir(parents=True, mode=0o700, exist_ok=True)
    previous: list[tuple[Path, bytes | None]] = []
    try:
        for name, doc in docs.items():
            path = meta / name
            previous.append((path, path.read_bytes() if path.is_file() else None))
            store.atomic_json(path, doc)
    except BaseException:
        _rollback_metadata(previous)
        raise
    return previous


def _rollback_metadata(previous: list[tuple[Path, bytes | None]]) -> None:
    for path, data in reversed(previous):
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)


# --- Native .so inventory (RFC-0207 §6) -------------------------------------------------

PACKER_SO_NAMES = {
    "libsecexe.so": "Bangcle",
    "libsecmain.so": "Bangcle",
    "libtxloader.so": "Tencent Legu",
    "libshell.so": "Tencent Legu",
    "libprotectClass.so": "Qihoo 360",
    "libjiagu.so": "Qihoo 360",
    "libDexHelper.so": "SecNeo",
}
# DexGuard and DashO ship native components under product-named files (RFC-0207 §6.3), matched by
# name stem since the exact file name varies by release, e.g. libdexguard.so or libdasho_rt.so.
PACKER_SO_PATTERNS = [
    (re.compile(r"lib(?:dexguard|dgrt)[\w.-]*\.so", re.I), "DexGuard"),
    (re.compile(r"libdasho[\w.-]*\.so", re.I), "DashO"),
]


def _packer_for(name: str) -> str | None:
    if name in PACKER_SO_NAMES:
        return PACKER_SO_NAMES[name]
    return next((label for pat, label in PACKER_SO_PATTERNS if pat.fullmatch(name)), None)

ELF_MACHINES = {3: "x86", 40: "ARM", 62: "x86_64", 183: "AArch64"}
# Android ABIs (current plus legacy ones still found in old APKs); the abi filter must name one.
KNOWN_ABIS = ("arm64-v8a", "armeabi-v7a", "armeabi", "x86", "x86_64", "riscv64", "mips", "mips64")


def _check_abi(abi) -> None:
    if abi is not None and abi not in KNOWN_ABIS:
        raise ValueError(f"abi must be one of {', '.join(KNOWN_ABIS)}")

_LIB_SO = re.compile(r"lib/([^/]+)/([^/]+\.so)")
MAX_NATIVE_BYTES = 256 * 1024 * 1024
MAX_NATIVE_LIBS = 4096
MAX_ENTROPY_BYTES = 64 * 1024 * 1024
MAX_ELF_TABLE_ENTRIES = 65536
READELF_TIMEOUT = 60
_ENTROPY_BLOCK = 4096
_ENTROPY_THRESHOLD = 7.2
_READ_CHUNK = 1024 * 1024
_PT_LOAD, _PT_GNU_STACK, _PT_GNU_RELRO, _PF_X = 1, 0x6474E551, 0x6474E552, 0x1
_SHT_DYNSYM, _SHT_DYNAMIC = 11, 6
_DT_NEEDED, _DT_SONAME, _DT_BIND_NOW, _DT_FLAGS, _DT_FLAGS_1 = 1, 14, 24, 30, 0x6FFFFFFB
_DF_BIND_NOW, _DF_1_NOW = 0x8, 0x1


def _shannon_entropy(data: bytes) -> float:
    import math
    from collections import Counter
    if not data:
        return 0.0
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in Counter(data).values())


def _entropy_hints(data: bytes, ranges: list[tuple[int, int]] | None = None,
                   cancel: threading.Event | None = None) -> dict:
    """Shannon entropy over 4 KiB blocks of the code ranges (whole file when none).

    The final short block of every range is scored too, so a packed tail is never skipped.
    At most MAX_ENTROPY_BYTES are scored per library; the result says when it stopped early.
    """
    scope = "executable segments" if ranges else "whole file"
    spans = ranges or [(0, len(data))]
    blocks = high = scanned = 0
    max_e = 0.0
    tail_bytes = 0
    truncated = False
    for start, size in spans:
        start, end = max(0, start), min(len(data), start + max(0, size))
        pos = start
        while pos < end:
            if scanned >= MAX_ENTROPY_BYTES:
                truncated = True
                break
            if cancel is not None and cancel.is_set():
                raise DecompileCancelled("native entropy scan")
            chunk = data[pos:min(pos + _ENTROPY_BLOCK, end)]
            pos += len(chunk)
            scanned += len(chunk)
            if len(chunk) < _ENTROPY_BLOCK:
                tail_bytes += len(chunk)
            blocks += 1
            e = _shannon_entropy(chunk)
            max_e = max(max_e, e)
            if e > _ENTROPY_THRESHOLD:
                high += 1
        if truncated:
            break
    return {"block_bytes": _ENTROPY_BLOCK, "scope": scope, "blocks": blocks, "tail_bytes": tail_bytes,
            "scanned_bytes": scanned, "truncated": truncated, "high_entropy_blocks": high,
            "max_block_entropy": round(max_e, 3), "high_entropy": high > 0}


def _cstr(buf: bytes, off: int) -> str:
    end = buf.find(b"\x00", off)
    return buf[off:end if end >= 0 else len(buf)].decode("utf-8", errors="replace")


def _parse_elf(data: bytes) -> dict:
    """In-process ELF reader: header, program headers, .dynsym and .dynamic (32/64-bit, either endian)."""
    import struct
    out: dict = {"parseable": False, "jni_exports": [], "needed": [], "soname": None, "relro": None,
                 "stack_canary": None, "executable_stack": None, "code_ranges": [], "symbols_read": False,
                 "dynamic_read": False, "note": None}
    if len(data) < 52 or data[:4] != b"\x7fELF":
        out["note"] = "not ELF or truncated"
        return out
    ei_class, ei_data = data[4], data[5]
    if ei_class not in (1, 2) or ei_data not in (1, 2):
        out["note"] = "unsupported ELF class/endian"
        return out
    en, is64 = ("<" if ei_data == 1 else ">"), ei_class == 2
    if is64 and len(data) < 64:
        out["note"] = "malformed ELF header"
        return out
    e_type, e_machine = struct.unpack_from(en + "HH", data, 16)
    if is64:
        e_phoff, e_shoff = struct.unpack_from(en + "QQ", data, 32)
        e_phentsize, e_phnum, e_shentsize, e_shnum = struct.unpack_from(en + "HHHH", data, 54)
    else:
        e_phoff, e_shoff = struct.unpack_from(en + "II", data, 28)
        e_phentsize, e_phnum, e_shentsize, e_shnum = struct.unpack_from(en + "HHHH", data, 42)
    out.update(parseable=True, elf_class=64 if is64 else 32, endian="little" if ei_data == 1 else "big",
               machine=ELF_MACHINES.get(e_machine, f"unknown_{e_machine}"), machine_code=e_machine, etype=e_type)
    notes: list[str] = []

    relro_segment = False
    ph_min = 56 if is64 else 32
    if e_phnum and (e_phentsize < ph_min or e_phoff + e_phnum * e_phentsize > len(data)):
        notes.append("program header table truncated")
    else:
        for i in range(e_phnum):
            o = e_phoff + i * e_phentsize
            if is64:
                p_type, p_flags, p_offset = struct.unpack_from(en + "IIQ", data, o)
                p_filesz = struct.unpack_from(en + "Q", data, o + 32)[0]
            else:
                p_type, p_offset = struct.unpack_from(en + "II", data, o)
                p_filesz, _memsz, p_flags = struct.unpack_from(en + "III", data, o + 16)
            if p_type == _PT_GNU_RELRO:
                relro_segment = True
            elif p_type == _PT_GNU_STACK:
                out["executable_stack"] = bool(p_flags & _PF_X)
            elif p_type == _PT_LOAD and p_flags & _PF_X and p_filesz:
                out["code_ranges"].append((p_offset, p_filesz))
        if out["executable_stack"] is None:
            notes.append("no PT_GNU_STACK; the loader may map an executable stack")

    def section(i: int) -> tuple[int, int, int, int, int]:
        o = e_shoff + i * e_shentsize
        if is64:
            _nm, typ, _fl, _ad, offset, size, link, _inf, _al, ent = struct.unpack_from(en + "IIQQQQIIQQ", data, o)
        else:
            _nm, typ, _fl, _ad, offset, size, link, _inf, _al, ent = struct.unpack_from(en + "IIIIIIIIII", data, o)
        return typ, offset, size, link, ent

    full_now = False
    if e_shoff == 0 or e_shnum == 0:
        notes.append("no section headers; JNI symbols and dynamic tags need the readelf fallback")
    elif e_shentsize < (64 if is64 else 40) or e_shnum > MAX_ELF_TABLE_ENTRIES or e_shoff + e_shnum * e_shentsize > len(data):
        notes.append("section table truncated; JNI symbols and dynamic tags need the readelf fallback")
    else:
        dynsym = dynamic = None
        for i in range(e_shnum):
            typ, offset, size, link, ent = section(i)
            if typ == _SHT_DYNSYM and dynsym is None:
                dynsym = (offset, size, link, ent)
            elif typ == _SHT_DYNAMIC and dynamic is None:
                dynamic = (offset, size, ent)
        dynstr = None
        if dynsym is None:
            notes.append("no .dynsym")
        else:
            sym_off, sym_size, str_link, sym_ent = dynsym
            if sym_ent < (24 if is64 else 16) or str_link >= e_shnum:
                notes.append("invalid dynsym linkage")
            else:
                _t, stroff, strsize, _l, _e = section(str_link)
                if stroff + strsize > len(data) or sym_off + sym_size > len(data) or sym_size // sym_ent > MAX_ELF_TABLE_ENTRIES:
                    notes.append("dynsym/strtab truncated")
                else:
                    dynstr = data[stroff:stroff + strsize]
                    jni, canary = set(), False
                    for k in range(sym_size // sym_ent):
                        st_name = struct.unpack_from(en + "I", data, sym_off + k * sym_ent)[0]
                        if st_name >= len(dynstr):
                            continue
                        name = _cstr(dynstr, st_name)
                        canary = canary or name == "__stack_chk_fail"
                        if name.startswith("Java_") or name in {"JNI_OnLoad", "JNI_OnUnload"}:
                            jni.add(name)
                    out.update(jni_exports=sorted(jni), stack_canary=canary, symbols_read=True)
        if dynamic is None:
            notes.append("no .dynamic")
        else:
            dyn_off, dyn_size, dyn_ent = dynamic
            dyn_ent = dyn_ent or (16 if is64 else 8)
            if dyn_ent < (16 if is64 else 8) or dyn_off + dyn_size > len(data) or dyn_size // dyn_ent > MAX_ELF_TABLE_ENTRIES:
                notes.append("dynamic section truncated")
            else:
                needed, soname = [], None
                for k in range(dyn_size // dyn_ent):
                    tag, val = struct.unpack_from(en + ("QQ" if is64 else "II"), data, dyn_off + k * dyn_ent)
                    if tag == 0:
                        break
                    if tag == _DT_NEEDED:
                        needed.append(val)
                    elif tag == _DT_SONAME:
                        soname = val
                    elif tag == _DT_BIND_NOW:
                        full_now = True
                    elif tag == _DT_FLAGS and val & _DF_BIND_NOW:
                        full_now = True
                    elif tag == _DT_FLAGS_1 and val & _DF_1_NOW:
                        full_now = True
                if dynstr is None:
                    notes.append("dynamic tags present but .dynstr unavailable")
                else:
                    out["needed"] = [_cstr(dynstr, v) for v in needed if v < len(dynstr)]
                    out["soname"] = _cstr(dynstr, soname) if soname is not None and soname < len(dynstr) else None
                out["dynamic_read"] = True
    out["relro"] = ("full" if full_now else "partial") if relro_segment else "none"
    out["note"] = "; ".join(notes) or None
    return out


# readelf --dyn-syms row: "Num: Value Size Type Bind Vis Ndx Name"; binutils appends a version
# ("@LIBC", "@@VERS_1") and a version index (" (2)") after the name, llvm-readelf only the version.
_READELF_SYM = re.compile(r"^[ \t]*\d+:[ \t]+[0-9A-Fa-f]+(?:[ \t]+\S+){5}[ \t]+([^\s@]+)", re.M)


def _readelf_symbols(text: str) -> set[str]:
    return set(_READELF_SYM.findall(text))


# GNU_STACK flags sit between MemSiz and Align; binutils prints Align as "0", llvm-readelf as "0x10".
_READELF_STACK = re.compile(r"GNU_STACK(?:[ \t]+\S+){5}[ \t]+([RWE ]+?)[ \t]+(?:0x)?[0-9A-Fa-f]+[ \t]*$", re.M)


def _readelf_stack_flags(text: str) -> str | None:
    m = _READELF_STACK.search(text)
    return m.group(1).replace(" ", "") if m else None


def _readelf_fallback(ident: str, path: Path) -> dict:
    """Ask binutils readelf in ANZU-REA for what the in-process reader could not get."""
    result = _wsl([READELF, "-W", "--dynamic", "--dyn-syms", "--program-headers", _linux_path(path)], READELF_TIMEOUT)
    text = result.stdout.decode("utf-8", errors="replace")
    if result.returncode or not text.strip():
        raise RuntimeError((result.stderr.decode("utf-8", errors="replace") or "readelf failed")[-500:])
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", text)
    soname = re.search(r"\(SONAME\)\s+Library soname: \[([^\]]+)\]", text)
    symbols = _readelf_symbols(text)
    jni = sorted(s for s in symbols if s.startswith("Java_") or s in {"JNI_OnLoad", "JNI_OnUnload"})
    full = bool(re.search(r"\((?:FLAGS|FLAGS_1)\)\s+.*\b(?:BIND_NOW|NOW)\b", text) or "(BIND_NOW)" in text)
    relro = "GNU_RELRO" in text
    stack = _readelf_stack_flags(text)
    return {"needed": needed, "soname": soname.group(1) if soname else None, "jni_exports": jni,
            "stack_canary": any(s == "__stack_chk_fail" for s in symbols),
            "relro": ("full" if full else "partial") if relro else "none",
            "executable_stack": ("E" in stack) if stack else None}


def _native_candidates(row: dict, abi: str | None) -> tuple[list[dict], list[str]]:
    """List lib/<abi>/*.so entries from ZIP metadata only; nothing is read or extracted here."""
    found: dict[str, dict] = {}
    unknowns: list[str] = []
    for part in row["apk"]["parts"]:
        try:
            with zipfile.ZipFile(part["path"]) as z:
                infos = [i for i in z.infolist() if not i.is_dir() and _LIB_SO.fullmatch(i.filename)]
        except (OSError, zipfile.BadZipFile) as exc:
            unknowns.append(f"APK part {part['name']} could not be opened for native inventory: {exc}")
            continue
        listed = set(part.get("native_libs") or [])
        present = {i.filename for i in infos}
        for missing in sorted(listed - present):
            unknowns.append(f"Native library {missing} was recorded at intake but is missing from {part['name']}.")
        for info in infos:
            lib_abi = _LIB_SO.fullmatch(info.filename).group(1)
            if abi and lib_abi != abi:
                continue
            if info.filename in found:
                if found[info.filename]["crc"] != info.CRC:
                    unknowns.append(f"{info.filename} differs between {found[info.filename]['part']} and "
                                    f"{part['name']}; only the first copy was inventoried.")
                continue
            if info.file_size > MAX_NATIVE_BYTES:
                unknowns.append(f"Native library {info.filename} in {part['name']} is {info.file_size} bytes, over the "
                                f"{MAX_NATIVE_BYTES}-byte cap; it was not read.")
                continue
            if len(found) >= MAX_NATIVE_LIBS:
                unknowns.append(f"More than {MAX_NATIVE_LIBS} native libraries; the rest were not inventoried.")
                break
            found[info.filename] = {"path": info.filename, "abi": lib_abi, "part": part["name"],
                                    "apk": Path(part["path"]), "size": info.file_size, "crc": info.CRC}
    return sorted(found.values(), key=lambda c: (c["abi"], c["path"])), unknowns


def _read_native(ident: str, cand: dict, cancel: threading.Event) -> tuple[bytes, str, Path]:
    """Stream one library out of its APK: hash, size cap and cancel checks per chunk; copy kept under apk/native/."""
    dest_root = (store.directory(ident) / "apk" / "native").resolve()
    target = (dest_root / cand["part"].replace("/", "_") / Path(*PurePosixPath(cand["path"]).parts)).resolve()
    if not target.is_relative_to(dest_root):
        raise ValueError(f"Unsafe native library path: {cand['path']}")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    h = hashlib.sha256()
    buf = bytearray()
    tmp = target.with_name(target.name + ".partial")
    with zipfile.ZipFile(cand["apk"]) as z, z.open(cand["path"]) as src, tmp.open("wb") as dst:
        for chunk in iter(lambda: src.read(_READ_CHUNK), b""):
            if cancel.is_set():
                raise DecompileCancelled("native inventory")
            buf += chunk
            if len(buf) > MAX_NATIVE_BYTES:
                raise ValueError(f"{cand['path']} expanded past the {MAX_NATIVE_BYTES}-byte cap")
            h.update(chunk)
            dst.write(chunk)
    os.replace(tmp, target)
    return bytes(buf), h.hexdigest(), target


def _inspect_so(ident: str, cand: dict, data: bytes, digest: str, disk: Path, cancel: threading.Event,
                unknowns: list[str]) -> dict:
    elf = _parse_elf(data)
    fallback = None
    if elf["parseable"] and not (elf["symbols_read"] and elf["dynamic_read"]):
        try:
            fallback = _readelf_fallback(ident, disk)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            log.warning("readelf fallback failed for %s: %s", cand["path"], exc)
            unknowns.append(f"{cand['path']}: {elf['note']}; readelf fallback failed ({str(exc)[:200]}).")
        else:
            for key in ("needed", "soname", "jni_exports", "stack_canary", "executable_stack"):
                if not elf.get(key) and fallback.get(key) not in (None, []):
                    elf[key] = fallback[key]
            rank = {"none": 0, "partial": 1, "full": 2}
            if not elf["dynamic_read"] or rank.get(fallback["relro"], 0) > rank.get(elf["relro"], 0):
                # Without the dynamic table our own parse cannot see BIND_NOW, so readelf's view wins.
                elf["relro"] = fallback["relro"]
    elif not elf["parseable"]:
        unknowns.append(f"{cand['path']} is not a parseable ELF ({elf['note']}); only size and SHA-256 were recorded.")
    ent = _entropy_hints(data, elf["code_ranges"], cancel)
    name = PurePosixPath(cand["path"]).name
    hints = []
    packer = _packer_for(name)
    if packer:
        hints.append({"kind": "packer_signature", "packer": packer,
                      "detail": f"Native code is protected by {packer}; static symbols are obscured."})
    if ent["high_entropy"]:
        hints.append({"kind": "high_entropy", "detail": (
            f"Shannon entropy > {_ENTROPY_THRESHOLD} on {ent['high_entropy_blocks']}/{ent['blocks']} "
            f"{_ENTROPY_BLOCK}-byte blocks of the {ent['scope']} (max {ent['max_block_entropy']}); packing or encryption likely.")})
    if ent["truncated"]:
        unknowns.append(f"{cand['path']}: entropy scored on the first {MAX_ENTROPY_BYTES} bytes only.")
    if elf.get("executable_stack"):
        hints.append({"kind": "executable_stack", "detail": "PT_GNU_STACK is RWE; the stack is executable."})
    if elf["parseable"] and elf["relro"] != "full":
        hints.append({"kind": "relro", "detail": f"{elf['relro'].capitalize()} RELRO; the GOT stays writable."})
    if elf["parseable"] and elf.get("stack_canary") is False:
        hints.append({"kind": "no_stack_canary", "detail": "__stack_chk_fail is not imported; no stack canaries."})
    return {"path": cand["path"], "abi": cand["abi"], "part": cand["part"], "name": name, "bytes": len(data),
            "sha256": digest,
            # The hashed bytes are the original APK entry; the file on disk is a derived working copy.
            "source": {"kind": "apk_entry", "part": cand["part"], "entry": cand["path"]},
            "derived_copy": {"kind": "derived_copy", "path": disk.relative_to(store.directory(ident)).as_posix(),
                             "sha256": digest},
            "elf": {k: elf.get(k) for k in ("parseable", "elf_class", "endian", "machine", "machine_code", "note")},
            "soname": elf.get("soname"), "needed": elf.get("needed") or [],
            "hardening": {"relro": elf.get("relro"), "stack_canary": elf.get("stack_canary"),
                          "executable_stack": elf.get("executable_stack")},
            "jni_exports": list(elf.get("jni_exports") or []), "readelf_fallback": fallback is not None,
            "entropy": ent, "hints": hints}


def apk_inventory_native(ident: str, abi: str | None = None, claimed: dict | None = None) -> dict:
    """Inventory native .so libraries across APK parts (RFC-0207 §6); writes apk_native_libs evidence.

    Holds the investigation claim for the whole run, so it never interleaves evidence or custody
    entries with a decompile; it is refused while another operation is analyzing.
    """
    _check_abi(abi)
    claim = claimed if claimed is not None else _claim(ident, "native inventory")
    token = claim["_claim_token"]
    with _CLAIM_LOCK:
        _OWNED.add(ident)
    try:
        cancel = _CANCEL[ident]
        candidates, unknowns = _native_candidates(claim, abi)
        libraries = []
        for cand in candidates:
            if cancel.is_set():
                raise DecompileCancelled("native inventory")
            try:
                data, digest, disk = _read_native(ident, cand, cancel)
            except (ValueError, OSError, zipfile.BadZipFile) as exc:
                log.warning("Native library %s could not be read: %s", cand["path"], exc)
                unknowns.append(f"Native library {cand['path']} could not be read: {exc}")
                continue
            libraries.append(_inspect_so(ident, cand, data, digest, disk, cancel, unknowns))
        abis = sorted({lib["abi"] for lib in libraries})
        packers = sorted({h["packer"] for lib in libraries for h in lib["hints"] if h["kind"] == "packer_signature"})
        high = sum(1 for lib in libraries if lib["entropy"]["high_entropy"])
        unknowns += [f"Native code is protected by {p}; static symbols are obscured." for p in packers]
        if high:
            unknowns.append(f"{high} native librar{'y' if high == 1 else 'ies'} show high entropy "
                            f"(>{_ENTROPY_THRESHOLD}); packed or encrypted, static symbol extraction incomplete.")
        unknowns = list(dict.fromkeys(unknowns))
        limitations = ["Static inspection only; no native code was executed.",
                       "ELF data comes from program headers, .dynsym and .dynamic; readelf in ANZU-REA fills gaps.",
                       f"Libraries over {MAX_NATIVE_BYTES} bytes are listed as unknowns, not read."]
        doc = {"investigation_id": ident, "filter_abi": abi, "abis": abis, "library_count": len(libraries),
               "libraries": libraries, "packers_detected": packers, "high_entropy_count": high,
               "unknowns": unknowns, "limitations": limitations}
        meta = store.directory(ident) / "apk" / "metadata"
        with _CLAIM_LOCK:
            row = store.load(ident)  # reload: evidence ids and custody entries continue from the stored row
            if _CLAIMS.get(ident) != token:
                raise RuntimeError("Investigation claim was lost; native inventory results were not recorded")
            eid = _record(row, "apk_native_libs", {"abi": abi}, {
                "provider": "ANZU APK sidecar", "abis": abis, "library_count": len(libraries),
                "libraries": [{k: lib[k] for k in ("path", "abi", "part", "bytes", "sha256", "source", "derived_copy",
                                                   "soname", "needed", "hardening", "jni_exports", "hints")} | {
                                   "elf_class": lib["elf"]["elf_class"], "machine": lib["elf"]["machine"]}
                              for lib in libraries],
                "packers_detected": packers, "high_entropy_count": high, "unknowns": unknowns,
                "metadata": "apk/metadata/native.json", "limitations": limitations})
            _settle(row, unknowns)
            row.pop("last_error", None)
            _coc(row, "apk_native_inventoried",
                 f"Inventoried {len(libraries)} native librar{'y' if len(libraries) == 1 else 'ies'}"
                 + (f" (abi={abi})." if abi else "."), {"evidence": eid, "abis": abis, "library_count": len(libraries)})
            _custody(row, native_inventoried_at=_now())
            # native.json is written only once the claim is verified and the evidence recorded, and
            # removed again if the row cannot be saved, so it never describes unrecorded results.
            meta.mkdir(parents=True, mode=0o700, exist_ok=True)
            native_json = meta / "native.json"
            previous = native_json.read_bytes() if native_json.is_file() else None
            store.atomic_json(native_json, doc)
            try:
                store.save(row)
            except BaseException:
                if previous is None:
                    native_json.unlink(missing_ok=True)
                else:
                    native_json.write_bytes(previous)
                raise
            _CLAIMS.pop(ident, None)
        return {**doc, "evidence_id": eid, "investigation_status": row["status"]}
    except DecompileCancelled as exc:
        _finish_failed(ident, token, "native_inventory", "cancelled", f"Cancelled during {exc}")
        raise
    except BaseException as exc:
        _finish_failed(ident, token, "native_inventory", "interrupted", str(exc)[:2000])
        raise
    finally:
        with _CLAIM_LOCK:
            _OWNED.discard(ident)
            if _CLAIMS.get(ident) is None or _CLAIMS.get(ident) == token:
                _CANCEL.pop(ident, None)


# --- Strings, endpoints and crypto hints (RFC-0207 §7-§8) --------------------------------

EVIDENCE_RECORD_CAP = 2000
ENDPOINT_LIMIT_MAX = 10000


def apk_extract_endpoints(ident: str, category: str | None = None, limit: int | None = None,
                          claimed: dict | None = None) -> dict:
    """Extract URLs, IPs, WebSockets, custom schemes and cloud backends (RFC-0207 §7).

    Always scans and stores the full result (apk/metadata/endpoints.json and strings.json) and
    records apk_endpoints evidence; ``category`` and ``limit`` only narrow the returned view.
    """
    from . import apk_strings
    if category is not None and category not in apk_strings.ENDPOINT_CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(apk_strings.ENDPOINT_CATEGORIES)}")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                              or not 1 <= limit <= ENDPOINT_LIMIT_MAX):
        raise ValueError(f"limit must be an integer between 1 and {ENDPOINT_LIMIT_MAX}")
    with _static_op(ident, "endpoint_extraction", claimed) as (claim, token):
        meta_unknowns: list[str] = []
        components = _optional_metadata(ident, "components", meta_unknowns)
        result = apk_strings.extract_endpoints(store.directory(ident) / "apk", claim["apk"]["parts"],
                                               components, _CANCEL.get(ident))
        if meta_unknowns:
            result["unknowns"] = list(dict.fromkeys(meta_unknowns + result["unknowns"]
                                                    + ["Deep links from components.json were not extracted."]))
        strings = result.pop("strings")
        records = result["endpoints"]
        doc = {"investigation_id": ident, **result}
        recorded: dict = {}

        def write(row: dict) -> None:
            recorded["eid"] = eid = _record(row, "apk_endpoints", {"category": category, "limit": limit}, {
                "provider": "ANZU APK sidecar", "counts": result["counts"], "endpoint_count": len(records),
                "cloud_services": result["cloud_services"], "endpoints": records[:EVIDENCE_RECORD_CAP],
                "evidence_truncated": len(records) > EVIDENCE_RECORD_CAP, "filtered": result["filtered"],
                "coverage": result["coverage"], "unique_strings": strings["unique_strings_stored"],
                "unknowns": result["unknowns"], "metadata": "apk/metadata/endpoints.json",
                "strings_metadata": "apk/metadata/strings.json", "limitations": result["limitations"]})
            _coc(row, "apk_endpoints_extracted", f"Extracted {len(records)} endpoint(s) from static strings.",
                 {"evidence": eid, "counts": result["counts"]})
            _custody(row, endpoints_extracted_at=_now())
        row = _commit_step(ident, token, result["unknowns"], write, {
            "endpoints.json": doc,
            "strings.json": {"investigation_id": ident, "coverage": result["coverage"], **strings}})
    view = [r for r in records if category is None or r["category"] == category]
    if limit is not None:
        view = view[:limit]
    return {**doc, "filter_category": category, "limit": limit, "endpoints": view, "returned": len(view),
            "evidence_id": recorded["eid"], "investigation_status": row["status"]}


def apk_crypto_hints(ident: str, claimed: dict | None = None) -> dict:
    """Flag hardcoded secrets, weak crypto, NSC trust policy and key-storage posture (RFC-0207 §8)."""
    from . import apk_strings
    with _static_op(ident, "crypto_hints", claimed) as (claim, token):
        meta_unknowns: list[str] = []
        manifest = _optional_metadata(ident, "manifest", meta_unknowns)
        result = apk_strings.crypto_hints(store.directory(ident) / "apk", claim["apk"]["parts"], manifest,
                                          cancel=_CANCEL.get(ident))
        if meta_unknowns:
            result["unknowns"] = list(dict.fromkeys(meta_unknowns + result["unknowns"] + [
                "debuggable, targetSdkVersion and the network security config reference could not be evaluated."]))
        doc = {"investigation_id": ident, **result}
        findings = result["findings"]
        recorded: dict = {}

        def write(row: dict) -> None:
            recorded["eid"] = eid = _record(row, "apk_crypto_hints", {}, {
                "provider": "ANZU APK sidecar", "finding_count": len(findings), "alert_count": result["alert_count"],
                "by_severity": result["by_severity"], "by_category": result["by_category"],
                "findings": findings[:EVIDENCE_RECORD_CAP], "evidence_truncated": len(findings) > EVIDENCE_RECORD_CAP,
                "network_security_config": result["network_security_config"],
                "key_storage": {"posture": result["key_storage"]["posture"], "detail": result["key_storage"]["detail"]},
                "coverage": result["coverage"], "unknowns": result["unknowns"],
                "metadata": "apk/metadata/crypto_hints.json", "limitations": result["limitations"]})
            _coc(row, "apk_crypto_hints_extracted",
                 f"Recorded {len(findings)} cryptographic hint(s), {result['alert_count']} alert(s).",
                 {"evidence": eid, "by_severity": result["by_severity"]})
            _custody(row, crypto_hints_extracted_at=_now())
        row = _commit_step(ident, token, result["unknowns"], write, {"crypto_hints.json": doc})
    return {**doc, "evidence_id": recorded["eid"], "investigation_status": row["status"]}


# --- Agent tool catalog (runtime.py) ----------------------------------------------------

CATALOG = {
    "apk_decompile": {"name": "apk_decompile",
                      "description": "Run apktool and jadx on the prepared APK; on jadx failure recover smali via apktool.",
                      "inputSchema": {"type": "object", "properties": {
                          "skip_jadx": {"type": "boolean"},
                          "decompile_smali_fallback": {"type": "boolean"}},
                                      "additionalProperties": False}},
    "apk_extract_manifest": {"name": "apk_extract_manifest",
                             "description": "Return the parsed manifest, permissions and exported attack surface.",
                             "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "apk_inventory_native": {"name": "apk_inventory_native",
                             "description": "Inventory native .so libraries, ABIs, ELF headers, JNI exports and packer/entropy hints.",
                             "inputSchema": {"type": "object",
                                             "properties": {"abi": {"type": "string", "enum": list(KNOWN_ABIS)}},
                                             "additionalProperties": False}},
    "apk_extract_endpoints": {"name": "apk_extract_endpoints",
                              "description": "Extract URLs, IPs, WebSockets, custom URI schemes and cloud backends "
                                             "from DEX strings, resources and recovered Java; records endpoint evidence.",
                              "inputSchema": {"type": "object",
                                              "properties": {"category": {"type": "string", "enum": [
                                                  "url", "websocket", "custom_scheme", "cloud_service", "ipv4", "ipv6"]},
                                                  "limit": {"type": "integer", "minimum": 1,
                                                            "maximum": ENDPOINT_LIMIT_MAX}},
                                              "additionalProperties": False}},
    "apk_crypto_hints": {"name": "apk_crypto_hints",
                         "description": "Flag hardcoded secrets, weak ciphers, static keys/IVs, network security "
                                        "config trust policy and AndroidKeyStore usage; records crypto evidence.",
                         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
}


def call(ident: str, operation: str, arguments: dict, claimed: dict | None = None) -> dict:
    """Execute an admitted catalog operation; decompile writes its own evidence records."""
    if operation == "apk_decompile":
        before = len(store.load(ident)["evidence"])
        row = decompile(ident, bool(arguments.get("skip_jadx", False)),
                        bool(arguments.get("decompile_smali_fallback", True)), claimed)
        return {"status": "evidence", "investigation_status": row["status"],
                "evidence": row["evidence"][before:], "unknowns": row.get("unknowns", [])}
    if operation == "apk_extract_manifest":
        row = store.load(ident)
        eid = next((e["id"] for e in reversed(row["evidence"]) if e["operation"] == "apk_manifest"), None)
        try:
            manifest, components = metadata(ident, "manifest"), metadata(ident, "components")
        except FileNotFoundError as exc:
            raise ValueError("No decoded manifest yet; call apk_decompile first") from exc
        return {"status": "evidence", "evidence_id": eid, "manifest": manifest, "components": components}
    if operation == "apk_inventory_native":
        abi = arguments.get("abi")
        _check_abi(abi)
        out = apk_inventory_native(ident, abi, claimed)
        return {"status": "evidence", "evidence_id": out["evidence_id"],
                "investigation_status": out["investigation_status"], "native": out}
    if operation == "apk_extract_endpoints":
        out = apk_extract_endpoints(ident, arguments.get("category"), arguments.get("limit"), claimed)
        return {"status": "evidence", "evidence_id": out["evidence_id"],
                "investigation_status": out["investigation_status"], "endpoints": out}
    if operation == "apk_crypto_hints":
        out = apk_crypto_hints(ident, claimed)
        return {"status": "evidence", "evidence_id": out["evidence_id"],
                "investigation_status": out["investigation_status"], "crypto": out}
    raise PermissionError("Operation is not admitted")


# --- Read side used by the API ---------------------------------------------------------

METADATA_DOCUMENTS = {"manifest": "manifest", "components": "components", "native": "native",
                      "endpoints": "endpoints", "crypto": "crypto_hints", "strings": "strings",
                      "smali": "smali"}


def _smali_summary(ident: str) -> dict | None:
    """Compact smali-fallback view for GET /apk/summary (None when metadata absent)."""
    try:
        doc = metadata(ident, "smali")
    except FileNotFoundError:
        return None
    return {"ran": bool(doc.get("ran")), "state": doc.get("state"), "reason": doc.get("reason"),
            "smali_files": doc.get("smali_files", 0), "smali_classes": doc.get("smali_classes", 0),
            "smali_output": doc.get("smali_output")}


def metadata(ident: str, name: str) -> dict:
    if name not in METADATA_DOCUMENTS:
        raise ValueError("Unknown APK metadata document")
    p = store.directory(ident) / "apk" / "metadata" / f"{METADATA_DOCUMENTS[name]}.json"
    if not p.is_file():
        raise FileNotFoundError(name)
    return json.loads(p.read_text(encoding="utf-8"))


def summary(ident: str) -> dict:
    row = store.load(ident)
    apk = row.get("apk")
    if not apk:
        raise FileNotFoundError("not an APK investigation")
    try:
        manifest = metadata(ident, "manifest")
    except FileNotFoundError:
        manifest = None
    abis = sorted({abi for p in apk["parts"] for abi in p["abis"]})
    try:
        native = metadata(ident, "native")
    except FileNotFoundError:
        native = None
    native_counts = native and {
        "libraries": native["library_count"], "abis": native["abis"],
        "jni_exports": sum(len(lib["jni_exports"]) for lib in native["libraries"]),
        "packers_detected": native["packers_detected"], "high_entropy": native["high_entropy_count"],
        "partial_or_no_relro": sum(1 for lib in native["libraries"] if lib["hardening"]["relro"] in {"partial", "none"}),
        "no_stack_canary": sum(1 for lib in native["libraries"] if lib["hardening"]["stack_canary"] is False),
        "executable_stack": sum(1 for lib in native["libraries"] if lib["hardening"]["executable_stack"]),
        "unknowns": len(native["unknowns"])}
    summary_unknowns: list[str] = []
    endpoints = _optional_metadata(ident, "endpoints", summary_unknowns)
    crypto = _optional_metadata(ident, "crypto", summary_unknowns)
    return {"id": ident, "status": row["status"], "format": apk["format"], "sha256": row.get("sha256"),
            "parts": len(apk["parts"]), "obb": len(apk["obb"]), "native_abis": abis,
            "native_libs": sum(len(p["native_libs"]) for p in apk["parts"]),
            "package": manifest["package"] if manifest else apk.get("declared_package"),
            "version_name": manifest and manifest["version_name"],
            "version_code": manifest and manifest["version_code"],
            "min_sdk": manifest and manifest["min_sdk"], "target_sdk": manifest and manifest["target_sdk"],
            "components": manifest["attack_surface"]["total"] if manifest else None,
            "exported": manifest["attack_surface"]["exported"] if manifest else None,
            "exported_unprotected": manifest["attack_surface"]["exported_unprotected_count"] if manifest else None,
            "high_risk_permissions": len(manifest["permissions"]["high_risk"]) if manifest else None,
            "endpoints": endpoints["endpoint_count"] if endpoints else None,
            "urls": endpoints["counts"]["url"] if endpoints else None,
            "crypto_alerts": crypto["alert_count"] if crypto else None,
            "decompiled": manifest is not None, "native_inventory": native_counts,
            "smali_fallback": _smali_summary(ident),
            "unknowns": list(dict.fromkeys([*row.get("unknowns", []), *summary_unknowns]))}
