"""RFC-0207 RE Phase 1, slice 1: execution-free APK reverse-engineering sidecar.

Static toolchain readiness (JDK, jadx, apktool), safe intake of standalone APKs,
XAPK/APKS containers and split-APK directories, apktool + jadx orchestration inside
the ANZU-REA WSL distribution with heap caps and timeouts, and manifest, permission
and component extraction. Every step is written to the RFC-0201 investigation store
as citable evidence plus a chain-of-custody record. No target code is executed.
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
_RUNNING: dict[str, list[str]] = {}


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
        for marker in list(_RUNNING.get(ident, [])):
            try:
                _wsl(["pkill", signal, "-f", marker], 30)
            except (OSError, subprocess.TimeoutExpired):
                continue
        deadline = time.monotonic() + KILL_GRACE
        while _RUNNING.get(ident) and time.monotonic() < deadline:
            time.sleep(0.2)
        if not _RUNNING.get(ident):
            return


def _run_tool(ident: str, name: str, argv: list[str], seconds: int, out: Path, marker: str) -> dict:
    """Run one tool under coreutils timeout: SIGTERM at the deadline, SIGKILL after 10 s."""
    if _CANCEL[ident].is_set():
        raise DecompileCancelled(name)
    wrapped = ["timeout", f"--kill-after={KILL_GRACE}s", f"{seconds}s", *argv]
    _RUNNING.setdefault(ident, []).append(marker)
    try:
        result = _wsl(wrapped, seconds + KILL_GRACE + 30)
        code = result.returncode
        text = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        code, text = 124, ""
    finally:
        _RUNNING[ident].remove(marker)
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
        store.validate_snapshot(row)
        row["status"] = "analyzing"
        _CANCEL[ident] = threading.Event()
        return store.save(row)


def release(ident: str) -> None:
    """Undo a claim that never reached decompile() (e.g. the task could not be scheduled)."""
    with _CLAIM_LOCK:
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
                APKTOOL_TIMEOUT, apktool_out, _linux_path(apktool_out))
            if apktool["state"] != "ok":
                unknowns.append(f"apktool resource decoding {apktool['state']} (exit {apktool['exit_code']}); "
                                "manifest, permissions and components may be unavailable.")
            jadx = None
            if not skip_jadx:
                inputs = [base] + [Path(p["path"]) for p in row["apk"]["parts"] if p["role"] == "split" and p["dex"]]
                jadx = _run_tool(ident, "jadx", [
                    "env", f"JAVA_HOME={JAVA_HOME}", f"PATH={JAVA_HOME}/bin:/usr/bin:/bin",
                    "JAVA_OPTS=" + " ".join(JVM_HEAP), JADX, "--no-res", "-d", _linux_path(jadx_out),
                    "--threads-count", "4", "--show-bad-code", "--escape-unicode",
                    *[_linux_path(p) for p in inputs]], JADX_TIMEOUT, jadx_out, _linux_path(jadx_out))
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
                prefixes[strings[uri]] = strings[prefix]
                pending_ns.append((strings[prefix], strings[uri]))
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
                    if a_ns >= 0:
                        key = f"{prefixes.get(strings[a_ns], 'ns')}:{key}"
                    if a_raw >= 0:
                        value = strings[a_raw]
                    elif vtype == 0x03:
                        value = strings[vdata]
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
                tag = strings[name]
                out.append(f"<{tag}{' ' if attrs else ''}{' '.join(attrs)}>")
            elif ctype == 0x0103:
                out.append(f"</{strings[struct.unpack_from('<ii', buf, off + 16)[1]]}>")
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


# --- Agent tool catalog (runtime.py) ----------------------------------------------------

CATALOG = {
    "apk_decompile": {"name": "apk_decompile",
                      "description": "Run apktool and jadx on the prepared APK and record manifest and decompile evidence.",
                      "inputSchema": {"type": "object", "properties": {"skip_jadx": {"type": "boolean"}},
                                      "additionalProperties": False}},
    "apk_extract_manifest": {"name": "apk_extract_manifest",
                             "description": "Return the parsed manifest, permissions and exported attack surface.",
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
    raise PermissionError("Operation is not admitted")


# --- Read side used by the API ---------------------------------------------------------

def metadata(ident: str, name: str) -> dict:
    if name not in {"manifest", "components"}:
        raise ValueError("Unknown APK metadata document")
    p = store.directory(ident) / "apk" / "metadata" / f"{name}.json"
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
            "decompiled": manifest is not None, "unknowns": row.get("unknowns", [])}
