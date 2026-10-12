"""RFC-0207 RE Phase 1: execution-free APK reverse-engineering sidecar.

Slice 1: static toolchain readiness (JDK, jadx, apktool), safe intake of standalone
APKs, XAPK/APKS containers and split-APK directories, apktool + jadx orchestration
inside the ANZU-REA WSL distribution with heap caps and timeouts, and manifest,
permission and component extraction.
Slice 2: native .so inventory (ABIs, ELF class/machine, JNI exports, packer/entropy).
Slice 3: string and network endpoint extraction and cryptographic key-material hints
(``apk_strings``), including network security config evaluation.
Every step is written to the RFC-0201 investigation store as citable evidence plus a
chain-of-custody record. No target code is executed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import subprocess
import threading
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import provision, store
from .ffs_ingest import make_chain_of_custody_entry

JAVA_HOME = "/opt/anzu/jdk"
JDK = "/opt/anzu/jdk/bin/java"
JADX = "/opt/anzu/jadx/bin/jadx"
APKTOOL_JAR = "/opt/anzu/apktool/apktool.jar"
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
_BUSY: set[str] = set()


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
    for name, path in [("JDK", JDK), ("jadx", JADX), ("apktool", APKTOOL_JAR)]:
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
    current.update({"investigation_id": row["id"], "task_id": row.get("task_id"),
                    "source_uri": row["target"], "source_kind": "local_path",
                    "source_sha256": row["apk"]["container"]["sha256"],
                    "source_bytes": row["apk"]["container"]["bytes"], "toolchain": toolchain(),
                    "analyst": "ANZU", "verified_digest": row.get("sha256")})
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


def prepare_apk(target: str, question: str, allowed: list[str], task_id: str | None) -> dict:
    """Admit an APK, XAPK/APKS or split-APK directory as a new static investigation."""
    raw = Path(target).expanduser()
    if not raw.is_dir() and raw.suffix.lower() not in APK_SUFFIXES:
        raise ValueError("APK target must be a .apk, .xapk or .apks file, or a split-APK directory")
    row = store.prepare(target, question, allowed, task_id)
    try:
        intake = _intake(row)
        snapshot = Path(row["snapshot"])
        container = ({"sha256": row["sha256"], "bytes": sum(p["bytes"] for p in intake["parts"])}
                     if snapshot.is_dir() else dict(zip(("sha256", "bytes"), _hash_file(snapshot))))
        row.update(kind="mobile", apk={**intake, "container": container,
                                         "staged": str(store.directory(row["id"]) / "apk" / "staged")})
        _coc(row, "source_admitted", f"APK target admitted for static analysis ({intake['format']}).",
             {"sha256": container["sha256"], "bytes": container["bytes"]})
        _coc(row, "apk_unpacked", f"{len(intake['parts'])} APK part(s) validated and hashed.",
             {"parts": [{"name": p["name"], "sha256": p["sha256"]} for p in intake["parts"]]})
        _record(row, "apk_unpack", {"target": row["target"]}, {
            "provider": "ANZU APK sidecar", "format": intake["format"], "container": container,
            "declared_package": intake["declared_package"], "association": intake["association"],
            "parts": [{k: v for k, v in p.items() if k != "path"} for p in intake["parts"]],
            "obb": intake["obb"],
            "limitations": ["Static intake only; no target code was executed.",
                            "OBB files are indexed by name and size, not extracted."]})
        _custody(row, ingested_at=_now())
        return store.save(row)
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
            except OSError:
                continue
            if not pid.isdigit() or int(pid) < 2:
                continue
            try:
                # coreutils timeout leads its own process group; signal the whole group by PID.
                _wsl(["kill", signal, "--", f"-{pid}"], 30)
            except (OSError, subprocess.TimeoutExpired):
                continue
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


def preflight(ident: str) -> dict:
    """Validate and atomically claim the investigation (status -> analyzing) for one decompile."""
    ready = readiness_static()
    if ready["status"] != "ready":
        raise RuntimeError(ready.get("error") or "Static APK toolchain is not ready")
    with _CLAIM_LOCK:
        row = store.load(ident)
        if not row.get("apk"):
            raise ValueError("Investigation was not prepared as an APK target")
        if row["status"] in {"cancelled", "closed", "analyzing"}:
            raise ValueError(f"Investigation is {row['status']}; cannot start decompilation")
        if ident in _BUSY:
            raise ValueError("A static analysis step is running for this investigation; retry when it finishes")
        store.validate_snapshot(row)
        row["status"] = "analyzing"
        _CANCEL[ident] = threading.Event()
        return store.save(row)


def release(ident: str) -> None:
    """Undo a preflight claim that decompile() never took over; a no-op while decompile owns it."""
    with _CLAIM_LOCK:
        if ident in _OWNED:
            return
        row = store.load(ident)
        if row["status"] == "analyzing":
            row["status"] = "interrupted"
            row["last_error"] = "Decompile was claimed but never started"
            store.save(row)
        _CANCEL.pop(ident, None)


def decompile(ident: str, skip_jadx: bool = False, claimed: dict | None = None) -> dict:
    """apktool (resources/manifest) then jadx (DEX), at most two runs system-wide.

    ``claimed`` is the row returned by preflight(); without it the claim is taken here.
    """
    row = claimed if claimed is not None else preflight(ident)
    with _CLAIM_LOCK:
        _OWNED.add(ident)
    try:
        return _decompile_owned(ident, skip_jadx, row)
    finally:
        with _CLAIM_LOCK:
            _OWNED.discard(ident)


def _decompile_owned(ident: str, skip_jadx: bool, row: dict) -> dict:
    with _DECOMPILE_SLOTS:
        work = store.directory(ident) / "apk"
        apktool_out, jadx_out, meta = work / "apktool", work / "jadx", work / "metadata"
        _coc(row, "decompile_started", "apktool/jadx static decompilation started.", {"skip_jadx": skip_jadx})
        store.save(row)
        try:
            for d in (apktool_out, jadx_out):
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
                if jadx["state"] == "timeout":
                    unknowns.append(f"jadx timed out after {JADX_TIMEOUT} s and was terminated; "
                                    f"Java coverage is partial ({jadx['java_files']} files recovered).")
                elif jadx["state"] == "out_of_memory":
                    unknowns.append("jadx exhausted its 4 GiB heap; Java coverage is partial.")
                elif jadx["state"] == "failed":
                    unknowns.append(f"jadx exited {jadx['exit_code']} with {jadx['error_lines']} error line(s); "
                                    "some classes were not decompiled.")
            manifest_eid = None
            manifest_file = apktool_out / "AndroidManifest.xml"
            decoder = f"apktool {toolchain()['apktool']}"
            if not manifest_file.is_file():
                try:
                    with zipfile.ZipFile(base) as z:
                        info = z.getinfo("AndroidManifest.xml")
                        if info.file_size > MAX_MANIFEST_BYTES:
                            raise ValueError("binary manifest exceeds 16 MiB")
                        text = decode_axml(z.read(info))
                    manifest_file = meta / "AndroidManifest.decoded.xml"
                    manifest_file.write_text(text, encoding="utf-8")
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
            succeeded = apktool["state"] == "ok" or bool(jadx and jadx["java_files"])
            decompile_eid = _record(row, "apk_decompile", {"skip_jadx": skip_jadx}, {
                "provider": "ANZU APK sidecar", "toolchain": toolchain(), "apktool": apktool, "jadx": jadx,
                "apktool_output": str(apktool_out), "jadx_output": str(jadx_out) if jadx else None,
                "manifest_evidence": manifest_eid,
                "limitations": ["Recovered Java is decompiler output, not original source.",
                                "No target code was executed."]}, success=succeeded)
            row["unknowns"] = list(dict.fromkeys([*row.get("unknowns", []), *unknowns]))
            row["status"] = "partial" if unknowns else "investigating"
            row.pop("last_error", None)
            _coc(row, "decompile_completed", "Static decompilation finished.",
                 {"evidence": [e for e in (manifest_eid, decompile_eid) if e], "unknowns": len(unknowns)})
            stamp = _now()
            _custody(row, decompiled_at=stamp, completed_at=stamp)
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
def _static_op(ident: str):
    """Claim one in-process static step; never overlaps a decompile or another step on the row.

    Evidence IDs are allocated from the row, so two writers on one investigation would clobber
    each other's records; preflight() refuses to claim while a step is in flight and vice versa.
    """
    with _CLAIM_LOCK:
        row = store.load(ident)
        if not row.get("apk"):
            raise ValueError("Investigation was not prepared as an APK target")
        if row["status"] in {"analyzing", "cancelled", "closed"}:
            raise ValueError(f"Investigation is {row['status']}; cannot run a static analysis step")
        if ident in _BUSY:
            raise ValueError("A static analysis step is already running for this investigation")
        _BUSY.add(ident)
    try:
        store.validate_snapshot(row)
        yield row
    finally:
        with _CLAIM_LOCK:
            _BUSY.discard(ident)


def _settle(row: dict, unknowns: list[str]) -> None:
    """Merge step unknowns into the row; the row stays partial while any unknown is declared."""
    row["unknowns"] = list(dict.fromkeys([*row.get("unknowns", []), *unknowns]))
    if row["status"] in {"prepared", "investigating", "partial"}:
        row["status"] = "partial" if row["unknowns"] else "investigating"


def _optional_metadata(ident: str, name: str) -> dict | None:
    try:
        return metadata(ident, name)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


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
ELF_MACHINES = {3: "x86", 40: "ARM", 62: "x86_64", 183: "AArch64"}
_LIB_SO = re.compile(r"lib/([^/]+)/([^/]+\.so)$")
_ENTROPY_BLOCK = 4096
_ENTROPY_THRESHOLD = 7.2


def _shannon_entropy(data: bytes) -> float:
    import math
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def _entropy_hints(data: bytes) -> dict:
    high = 0
    blocks = 0
    max_e = 0.0
    for i in range(0, len(data), _ENTROPY_BLOCK):
        chunk = data[i:i + _ENTROPY_BLOCK]
        if len(chunk) < _ENTROPY_BLOCK and blocks:
            break
        if not chunk:
            continue
        blocks += 1
        e = _shannon_entropy(chunk)
        if e > max_e:
            max_e = e
        if e > _ENTROPY_THRESHOLD:
            high += 1
    return {
        "block_bytes": _ENTROPY_BLOCK,
        "blocks": blocks,
        "high_entropy_blocks": high,
        "max_block_entropy": round(max_e, 3),
        "high_entropy": high > 0,
    }


def _parse_elf(data: bytes) -> dict:
    """Minimal ELF header + dynsym JNI scan for common Android little-endian 32/64 .so files."""
    import struct
    out: dict = {"parseable": False, "jni_exports": []}
    if len(data) < 52 or data[:4] != b"\x7fELF":
        out["note"] = "not ELF or truncated"
        return out
    ei_class, ei_data = data[4], data[5]
    if ei_class not in (1, 2) or ei_data not in (1, 2):
        out["note"] = "unsupported ELF class/endian"
        return out
    endian = "<" if ei_data == 1 else ">"
    is64 = ei_class == 2
    try:
        if is64:
            if len(data) < 64:
                raise struct.error("short ehdr")
            e_type, e_machine = struct.unpack_from(endian + "HH", data, 16)
            e_shoff, = struct.unpack_from(endian + "Q", data, 40)
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(endian + "HHH", data, 58)
        else:
            e_type, e_machine = struct.unpack_from(endian + "HH", data, 16)
            e_shoff, = struct.unpack_from(endian + "I", data, 32)
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(endian + "HHH", data, 46)
    except struct.error:
        out["note"] = "malformed ELF header"
        return out
    out.update({
        "parseable": True,
        "elf_class": 64 if is64 else 32,
        "endian": "little" if ei_data == 1 else "big",
        "machine": ELF_MACHINES.get(e_machine, f"unknown_{e_machine}"),
        "machine_code": e_machine,
        "etype": e_type,
        "note": None,
    })
    if e_shoff == 0 or e_shnum == 0 or e_shentsize < (64 if is64 else 40):
        out["note"] = "no section headers; JNI symbols not scanned"
        return out
    if e_shoff + e_shnum * e_shentsize > len(data):
        out["note"] = "section table truncated; JNI symbols not scanned"
        return out

    def sh_at(i: int):
        off = e_shoff + i * e_shentsize
        if is64:
            name, typ, _flags, _addr, offset, size, link, _info, _align, entsize = struct.unpack_from(
                endian + "IIQQQQIIQQ", data, off)
        else:
            name, typ, _flags, _addr, offset, size, link, _info, _align, entsize = struct.unpack_from(
                endian + "IIIIIIIIII", data, off)
        return name, typ, offset, size, link, entsize

    dynsym = None
    for i in range(e_shnum):
        _n, typ, offset, size, link, entsize = sh_at(i)
        if typ == 11:  # SHT_DYNSYM
            dynsym = (offset, size, link, entsize)
            break
    if dynsym is None:
        out["note"] = "no .dynsym; JNI symbols not scanned"
        return out
    sym_off, sym_size, str_link, sym_entsize = dynsym
    if sym_entsize <= 0 or str_link >= e_shnum:
        out["note"] = "invalid dynsym linkage"
        return out
    _sn, _st, stroff, strsize, _sl, _se = sh_at(str_link)
    if stroff + strsize > len(data) or sym_off + sym_size > len(data):
        out["note"] = "dynsym/strtab truncated"
        return out
    strtab = data[stroff:stroff + strsize]
    expected = 24 if is64 else 16
    if sym_entsize < expected:
        out["note"] = "unexpected dynsym entry size"
        return out
    jni = []
    for i in range(sym_size // sym_entsize):
        base = sym_off + i * sym_entsize
        try:
            st_name, = struct.unpack_from(endian + "I", data, base)
        except struct.error:
            break
        if st_name >= len(strtab):
            continue
        end = strtab.find(b"\x00", st_name)
        if end < 0:
            continue
        name = strtab[st_name:end].decode("utf-8", errors="replace")
        if name.startswith("Java_") or name in {"JNI_OnLoad", "JNI_OnUnload"}:
            jni.append(name)
    out["jni_exports"] = sorted(set(jni))
    return out


def _lib_rel_from_parts(parts: tuple[str, ...]) -> str | None:
    if "lib" not in parts:
        return None
    i = parts.index("lib")
    rel = "/".join(parts[i:])
    return rel if _LIB_SO.fullmatch(rel) else None


def _collect_native_candidates(row: dict) -> list[tuple[str, str, Path | None, bytes | None]]:
    """Return (relative_path, abi, disk_path|None, zip_bytes|None) for each unique lib/**/*.so."""
    seen: set[str] = set()
    found: list[tuple[str, str, Path | None, bytes | None]] = []
    root = store.directory(row["id"]) / "apk"

    def add(rel: str, disk: Path | None = None, blob: bytes | None = None) -> None:
        rel = rel.replace("\\", "/")
        m = _LIB_SO.fullmatch(rel)
        if not m:
            return
        if rel in seen:
            return
        seen.add(rel)
        found.append((rel, m.group(1), disk, blob))

    for base in (root / "native", root / "apktool", root / "staged"):
        if not base.is_dir():
            continue
        for so in base.rglob("*.so"):
            if not so.is_file():
                continue
            try:
                rel = _lib_rel_from_parts(so.relative_to(base).parts)
            except ValueError:
                rel = None
            if rel is None:
                rel = _lib_rel_from_parts(so.parts)
            if rel:
                add(rel, disk=so)

    for part in row.get("apk", {}).get("parts", []):
        recorded = [n.replace("\\", "/") for n in (part.get("native_libs") or [])]
        path = Path(part["path"]) if part.get("path") else None
        if path and path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = {i.filename.replace("\\", "/") for i in z.infolist() if not i.is_dir()}
                for name in sorted(names | set(recorded)):
                    if not _LIB_SO.fullmatch(name):
                        continue
                    if name in seen:
                        continue
                    key = name if name in z.namelist() else next(
                        (n for n in z.namelist() if n.replace("\\", "/") == name), None)
                    if key is None:
                        continue
                    info = z.getinfo(key)
                    if info.file_size > MAX_BYTES:
                        continue
                    add(name, blob=z.read(info))
        elif path and path.is_dir():
            for so in path.rglob("*.so"):
                if not so.is_file():
                    continue
                rel = _lib_rel_from_parts(so.relative_to(path).parts)
                if rel:
                    add(rel, disk=so)
        else:
            for name in recorded:
                add(name)
    return found


def _materialize_so(ident: str, rel: str, data: bytes) -> Path:
    """Write lib bytes under apk/native/<rel> with zip-slip checks."""
    dest_root = (store.directory(ident) / "apk" / "native").resolve()
    dest_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    target = (dest_root / Path(*PurePosixPath(rel).parts)).resolve()
    if not target.is_relative_to(dest_root):
        raise ValueError(f"Unsafe native library path: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    return target


def _inspect_so(rel: str, abi: str, data: bytes, source: str) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    elf = _parse_elf(data)
    ent = _entropy_hints(data)
    so_name = PurePosixPath(rel).name
    packer = PACKER_SO_NAMES.get(so_name)
    hints = []
    if packer:
        hints.append({
            "kind": "packer_signature",
            "packer": packer,
            "detail": f"Native code is protected by {packer}; static symbols are obscured.",
        })
    if ent["high_entropy"]:
        hints.append({
            "kind": "high_entropy",
            "detail": (
                f"Shannon entropy > {_ENTROPY_THRESHOLD} on {ent['high_entropy_blocks']}/"
                f"{ent['blocks']} {_ENTROPY_BLOCK}-byte blocks "
                f"(max {ent['max_block_entropy']}); packing or encryption likely."
            ),
        })
    elf_view = {
        "parseable": elf.get("parseable", False),
        "elf_class": elf.get("elf_class"),
        "endian": elf.get("endian"),
        "machine": elf.get("machine"),
        "machine_code": elf.get("machine_code"),
        "note": elf.get("note"),
    }
    return {
        "path": rel,
        "abi": abi,
        "name": so_name,
        "bytes": len(data),
        "sha256": digest,
        "source": source,
        "elf": elf_view,
        "jni_exports": list(elf.get("jni_exports") or []),
        "entropy": ent,
        "hints": hints,
    }


def apk_inventory_native(ident: str, abi: str | None = None) -> dict:
    """Inventory native .so libraries across APK/split parts (RFC-0207 §6); writes apk_native_libs evidence."""
    with _static_op(ident) as row:
        return _inventory_native(ident, row, abi)


def _inventory_native(ident: str, row: dict, abi: str | None) -> dict:
    candidates = _collect_native_candidates(row)
    libraries = []
    unknowns: list[str] = []
    for rel, lib_abi, disk, blob in candidates:
        if abi and lib_abi != abi:
            continue
        if disk is not None and disk.is_file():
            data = disk.read_bytes()
            source = "disk"
        elif blob is not None:
            data = blob
            source = "apk_zip"
            try:
                _materialize_so(ident, rel, data)
            except ValueError:
                pass
        else:
            unknowns.append(f"Native library {rel} was listed but bytes were not available.")
            continue
        libraries.append(_inspect_so(rel, lib_abi, data, source))

    libraries.sort(key=lambda item: (item["abi"], item["path"]))
    abis = sorted({lib["abi"] for lib in libraries})
    packers = sorted({
        hint["packer"] for lib in libraries for hint in lib["hints"] if hint["kind"] == "packer_signature"
    })
    high_entropy = sum(1 for lib in libraries if lib["entropy"]["high_entropy"])
    for packer in packers:
        unknowns.append(f"Native code is protected by {packer}; static symbols are obscured.")
    if high_entropy:
        unknowns.append(
            f"{high_entropy} native librar{'y' if high_entropy == 1 else 'ies'} show high entropy "
            f"(>{_ENTROPY_THRESHOLD} on {_ENTROPY_BLOCK}-byte blocks); "
            "static symbol extraction may be incomplete."
        )

    doc = {
        "investigation_id": ident,
        "filter_abi": abi,
        "abis": abis,
        "library_count": len(libraries),
        "libraries": libraries,
        "packers_detected": packers,
        "high_entropy_count": high_entropy,
        "unknowns": unknowns,
        "limitations": [
            "Static inspection only; no native code was executed.",
            "JNI exports come from .dynsym when section headers are present.",
            "Unparseable or truncated ELF files still appear with path, size and SHA-256.",
        ],
    }
    meta = store.directory(ident) / "apk" / "metadata"
    meta.mkdir(parents=True, mode=0o700, exist_ok=True)
    store.atomic_json(meta / "native.json", doc)
    eid = _record(row, "apk_native_libs", {"abi": abi}, {
        "provider": "ANZU APK sidecar",
        "abis": abis,
        "library_count": len(libraries),
        "libraries": [{
            "path": lib["path"], "abi": lib["abi"], "bytes": lib["bytes"], "sha256": lib["sha256"],
            "elf_class": lib["elf"].get("elf_class"), "machine": lib["elf"].get("machine"),
            "jni_exports": lib["jni_exports"], "hints": lib["hints"],
        } for lib in libraries],
        "packers_detected": packers,
        "high_entropy_count": high_entropy,
        "unknowns": unknowns,
        "metadata": "apk/metadata/native.json",
        "limitations": doc["limitations"],
    })
    _settle(row, unknowns)
    noun = "library" if len(libraries) == 1 else "libraries"
    detail = f"Inventoried {len(libraries)} native {noun}"
    if abi:
        detail += f" (abi={abi})"
    detail += "."
    _coc(row, "apk_native_inventoried", detail,
         {"evidence": eid, "abis": abis, "library_count": len(libraries)})
    _custody(row, native_inventoried_at=_now())
    store.save(row)
    return {**doc, "evidence_id": eid, "investigation_status": row["status"]}


# --- Strings, endpoints and crypto hints (RFC-0207 §7-§8) --------------------------------

EVIDENCE_RECORD_CAP = 2000
ENDPOINT_LIMIT_MAX = 10000


def apk_extract_endpoints(ident: str, category: str | None = None, limit: int | None = None) -> dict:
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
    with _static_op(ident) as row:
        result = apk_strings.extract_endpoints(store.directory(ident) / "apk", row["apk"]["parts"],
                                               _optional_metadata(ident, "components"))
        strings = result.pop("strings")
        records = result["endpoints"]
        doc = {"investigation_id": ident, **result}
        meta = store.directory(ident) / "apk" / "metadata"
        meta.mkdir(parents=True, mode=0o700, exist_ok=True)
        store.atomic_json(meta / "endpoints.json", doc)
        store.atomic_json(meta / "strings.json", {"investigation_id": ident, "coverage": result["coverage"], **strings})
        eid = _record(row, "apk_endpoints", {"category": category, "limit": limit}, {
            "provider": "ANZU APK sidecar", "counts": result["counts"], "endpoint_count": len(records),
            "cloud_services": result["cloud_services"], "endpoints": records[:EVIDENCE_RECORD_CAP],
            "evidence_truncated": len(records) > EVIDENCE_RECORD_CAP, "filtered": result["filtered"],
            "coverage": result["coverage"], "unique_strings": strings["unique_strings_stored"],
            "unknowns": result["unknowns"], "metadata": "apk/metadata/endpoints.json",
            "strings_metadata": "apk/metadata/strings.json", "limitations": result["limitations"]})
        _settle(row, result["unknowns"])
        _coc(row, "apk_endpoints_extracted", f"Extracted {len(records)} endpoint(s) from static strings.",
             {"evidence": eid, "counts": result["counts"]})
        _custody(row, endpoints_extracted_at=_now())
        store.save(row)
    view = [r for r in records if category is None or r["category"] == category]
    if limit is not None:
        view = view[:limit]
    return {**doc, "filter_category": category, "limit": limit, "endpoints": view, "returned": len(view),
            "evidence_id": eid, "investigation_status": row["status"]}


def apk_crypto_hints(ident: str) -> dict:
    """Flag hardcoded secrets, weak crypto, NSC trust policy and key-storage posture (RFC-0207 §8)."""
    from . import apk_strings
    with _static_op(ident) as row:
        result = apk_strings.crypto_hints(store.directory(ident) / "apk", row["apk"]["parts"],
                                          _optional_metadata(ident, "manifest"))
        doc = {"investigation_id": ident, **result}
        meta = store.directory(ident) / "apk" / "metadata"
        meta.mkdir(parents=True, mode=0o700, exist_ok=True)
        store.atomic_json(meta / "crypto_hints.json", doc)
        findings = result["findings"]
        eid = _record(row, "apk_crypto_hints", {}, {
            "provider": "ANZU APK sidecar", "finding_count": len(findings), "alert_count": result["alert_count"],
            "by_severity": result["by_severity"], "by_category": result["by_category"],
            "findings": findings[:EVIDENCE_RECORD_CAP], "evidence_truncated": len(findings) > EVIDENCE_RECORD_CAP,
            "network_security_config": result["network_security_config"],
            "key_storage": {"posture": result["key_storage"]["posture"], "detail": result["key_storage"]["detail"]},
            "coverage": result["coverage"], "unknowns": result["unknowns"],
            "metadata": "apk/metadata/crypto_hints.json", "limitations": result["limitations"]})
        _settle(row, result["unknowns"])
        _coc(row, "apk_crypto_hints_extracted",
             f"Recorded {len(findings)} cryptographic hint(s), {result['alert_count']} alert(s).",
             {"evidence": eid, "by_severity": result["by_severity"]})
        _custody(row, crypto_hints_extracted_at=_now())
        store.save(row)
    return {**doc, "evidence_id": eid, "investigation_status": row["status"]}


# --- Agent tool catalog (runtime.py) ----------------------------------------------------

CATALOG = {
    "apk_decompile": {"name": "apk_decompile",
                      "description": "Run apktool and jadx on the prepared APK and record manifest and decompile evidence.",
                      "inputSchema": {"type": "object", "properties": {"skip_jadx": {"type": "boolean"}},
                                      "additionalProperties": False}},
    "apk_extract_manifest": {"name": "apk_extract_manifest",
                             "description": "Return the parsed manifest, permissions and exported attack surface.",
                             "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "apk_inventory_native": {"name": "apk_inventory_native",
                             "description": "Inventory native .so libraries, ABIs, ELF headers, JNI exports and packer/entropy hints.",
                             "inputSchema": {"type": "object",
                                             "properties": {"abi": {"type": "string"}},
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
        row = decompile(ident, bool(arguments.get("skip_jadx", False)), claimed)
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
        if abi is not None and not isinstance(abi, str):
            raise ValueError("abi must be a string")
        out = apk_inventory_native(ident, abi)
        return {"status": "evidence", "evidence_id": out["evidence_id"],
                "investigation_status": out["investigation_status"], "native": out}
    if operation == "apk_extract_endpoints":
        out = apk_extract_endpoints(ident, arguments.get("category"), arguments.get("limit"))
        return {"status": "evidence", "evidence_id": out["evidence_id"],
                "investigation_status": out["investigation_status"], "endpoints": out}
    if operation == "apk_crypto_hints":
        out = apk_crypto_hints(ident)
        return {"status": "evidence", "evidence_id": out["evidence_id"],
                "investigation_status": out["investigation_status"], "crypto": out}
    raise PermissionError("Operation is not admitted")


# --- Read side used by the API ---------------------------------------------------------

METADATA_DOCUMENTS = {"manifest": "manifest", "components": "components", "native": "native",
                      "endpoints": "endpoints", "crypto": "crypto_hints", "strings": "strings"}


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
    endpoints = _optional_metadata(ident, "endpoints")
    crypto = _optional_metadata(ident, "crypto")
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
            "decompiled": manifest is not None, "unknowns": row.get("unknowns", [])}
