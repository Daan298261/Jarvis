"""RFC-0207 slice 8: DEX identifier-renaming (ProGuard/R8), protector-stub and jadx decompile-coverage assessment. Static only: reads classes*.dex class tables from every APK part and jadx-recovered sources; never executes target code. Bounded (256 MiB per DEX, 16 MiB per Java file, 2 GiB in total); every gap is recorded as an explicit unknown."""

from __future__ import annotations

import os
import re
import struct
import threading
import zipfile
import zlib
from pathlib import Path

from .apk_sidecar import DecompileCancelled
from .apk_strings import MAX_DEX_BYTES, MAX_SCAN_BYTES, MAX_TEXT_FILE_BYTES, dex_strings

OBFUSCATION_RATIO_THRESHOLD = 0.40
MIN_CLASSES_FOR_RATIO = 20
MAX_DEX_CLASSES = 1_000_000
MAX_SAMPLES = 20
_CANCEL_EVERY = 4096
_DEX_NAME = re.compile(r"classes\d*\.dex")
_SHORT_NAME = re.compile(r"[A-Za-z]{1,2}|[a-z]{1,2}[0-9]{1,2}")
GENERATED_CLASSES = {"R", "BuildConfig", "Manifest", "BR"}
DEX_PROTECTOR_STUBS = (
    ("Lcom/secneo/apkwrapper/", "SecNeo/Bangcle"),
    ("Lcom/bangcle/", "Bangcle"),
    ("Lcom/tencent/StubShell/", "Tencent Legu"),
    ("Lcom/stub/StubApp;", "Qihoo 360 Jiagu"),
    ("Lcom/baidu/protect/", "Baidu Protect"),
    ("Lcom/ali/mobisecenhance/", "Alibaba Security"),
    ("Lcom/shell/SuperApplication;", "Ijiami"),
)
JADX_MARKERS = (
    ("JADX WARNING", "warnings"),
    ("JADX ERROR", "errors"),
    ("Code decompiled incorrectly", "bad_code_methods"),
)


def _check_cancel(cancel: threading.Event | None, where: str) -> None:
    """Raise DecompileCancelled when the investigation's cancel event is set."""
    if cancel is not None and cancel.is_set():
        raise DecompileCancelled(where)


def dex_class_descriptors(buf: bytes, cancel: threading.Event | None = None) -> list[str]:
    """Return the type descriptor of every class_def_item, following class_idx -> type_ids -> string_ids.

    Every table is bounds-checked against the file; malformed input raises ValueError.
    """
    strings = dex_strings(buf, cancel)
    type_ids_size, type_ids_off = struct.unpack_from("<II", buf, 0x40)
    class_defs_size, class_defs_off = struct.unpack_from("<II", buf, 0x60)

    if class_defs_size > MAX_DEX_CLASSES:
        raise ValueError(f"class_defs_size {class_defs_size} exceeds the {MAX_DEX_CLASSES} cap")

    if type_ids_size and (type_ids_off < 0x70 or type_ids_off + 4 * type_ids_size > len(buf)):
        raise ValueError("type_ids table lies outside the file")

    if class_defs_size and (class_defs_off < 0x70 or class_defs_off + 32 * class_defs_size > len(buf)):
        raise ValueError("class_defs table lies outside the file")

    descriptors: list[str] = []
    for i in range(class_defs_size):
        if i % _CANCEL_EVERY == 0:
            _check_cancel(cancel, "DEX class scan")

        class_idx = struct.unpack_from("<I", buf, class_defs_off + 32 * i)[0]
        if class_idx >= type_ids_size:
            raise ValueError(f"class_def {i} references type {class_idx} outside type_ids")

        descriptor_idx = struct.unpack_from("<I", buf, type_ids_off + 4 * class_idx)[0]
        if descriptor_idx >= len(strings):
            raise ValueError(f"type {class_idx} references string {descriptor_idx} outside string_ids")

        descriptors.append(strings[descriptor_idx])

    return descriptors


def is_obfuscated_name(name: str) -> bool:
    """True for ProGuard/R8-style renamed identifiers (a, b, aa, a0); generated classes never count."""
    return bool(_SHORT_NAME.fullmatch(name)) and name not in GENERATED_CLASSES


def classify_descriptor(descriptor: str) -> dict | None:
    """Classify one ``L...;`` class descriptor; None for primitives, arrays and malformed descriptors."""
    if not descriptor.startswith("L") or not descriptor.endswith(";") or len(descriptor) <= 2:
        return None

    body = descriptor[1:-1]
    segments = body.split("/")
    package_segments = segments[:-1]
    simple = segments[-1]

    return {
        "name": body.replace("/", "."),
        "package": ".".join(package_segments),
        "inner": "$" in simple,
        "generated": simple.split("$", 1)[0] in GENERATED_CLASSES,
        "obfuscated": is_obfuscated_name(simple.split("$", 1)[0]),
        "obfuscated_package": bool(package_segments) and all(is_obfuscated_name(s) for s in package_segments),
    }


def protector_for(descriptor: str) -> str | None:
    """Name of the known DEX protector whose stub class matches ``descriptor``, if any."""
    for prefix, name in DEX_PROTECTOR_STUBS:
        if prefix.endswith(";"):
            if descriptor == prefix:
                return name
        else:
            if descriptor.startswith(prefix):
                return name
    return None


def assess_descriptors(descriptors: list[str]) -> dict:
    """Aggregate renaming, renamed packages, samples and protector stubs over class descriptors."""
    class_count = 0
    top_level_classes = 0
    obfuscated_classes = 0
    obfuscated_packages: set[str] = set()
    samples: list[str] = []
    protectors: list[dict] = []
    seen_protectors: set[str] = set()

    for descriptor in descriptors:
        info = classify_descriptor(descriptor)
        if info is None:
            continue

        class_count += 1

        if not info["inner"] and not info["generated"]:
            top_level_classes += 1
            if info["obfuscated"]:
                obfuscated_classes += 1
                if len(samples) < MAX_SAMPLES:
                    samples.append(info["name"])
            if info["obfuscated_package"] and info["package"]:
                obfuscated_packages.add(info["package"])

        protector = protector_for(descriptor)
        if protector and protector not in seen_protectors:
            seen_protectors.add(protector)
            protectors.append({"protector": protector, "class": info["name"]})

    ratio = round(obfuscated_classes / top_level_classes, 4) if top_level_classes else 0.0

    return {
        "class_count": class_count,
        "top_level_classes": top_level_classes,
        "obfuscated_classes": obfuscated_classes,
        "obfuscated_packages": len(obfuscated_packages),
        "obfuscated_ratio": ratio,
        "samples": samples,
        "protectors": protectors,
    }


def scan_jadx_markers(sources: Path, cancel: threading.Event | None = None) -> dict:
    """Count jadx incomplete-coverage markers (WARNING, ERROR, incorrectly decompiled) in recovered Java."""
    if not sources.is_dir():
        return {
            "scanned": False,
            "java_files": 0,
            "files_with_markers": 0,
            "warnings": 0,
            "errors": 0,
            "bad_code_methods": 0,
            "samples": [],
            "oversized": [],
            "truncated": False,
            "unreadable": [],
            "symlinks": [],
        }

    java_files = 0
    files_with_markers = 0
    warnings = 0
    errors = 0
    bad_code_methods = 0
    samples: list[dict] = []
    oversized: list[str] = []
    unreadable: list[str] = []
    symlinks: list[str] = []
    truncated = False
    total_bytes = 0

    candidates: list[Path] = []
    # os.walk(followlinks=False) never descends into symlinked directories; a symlinked directory
    # is reported (its contents could point anywhere) and a symlinked .java file is never read.
    for dirpath, dirnames, filenames in os.walk(sources, followlinks=False):
        base = Path(dirpath)
        for d in sorted(dirnames):
            if (base / d).is_symlink():
                symlinks.append((base / d).relative_to(sources).as_posix() + "/")
        dirnames[:] = sorted(d for d in dirnames if not (base / d).is_symlink())
        for name in filenames:
            if not name.endswith(".java"):
                continue
            path = base / name
            if path.is_symlink():
                symlinks.append(path.relative_to(sources).as_posix())
            elif path.is_file():
                candidates.append(path)
    symlinks.sort()

    for p in sorted(candidates):
        _check_cancel(cancel, "jadx marker scan")

        rel = p.relative_to(sources).as_posix()

        try:
            size = p.stat().st_size
        except OSError as exc:
            unreadable.append(f"{rel} ({exc.strerror or exc})")
            continue

        if size > MAX_TEXT_FILE_BYTES:
            oversized.append(rel)
            continue

        if total_bytes + size > MAX_SCAN_BYTES:
            truncated = True
            break

        total_bytes += size

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unreadable.append(f"{rel} ({exc.strerror or exc})")
            continue

        java_files += 1

        file_has_marker = False
        for lineno, line in enumerate(text.splitlines(), 1):
            for marker, key in JADX_MARKERS:
                n = line.count(marker)
                if n:
                    if key == "warnings":
                        warnings += n
                    elif key == "errors":
                        errors += n
                    elif key == "bad_code_methods":
                        bad_code_methods += n

                    if not file_has_marker:
                        file_has_marker = True

                    if len(samples) < MAX_SAMPLES:
                        samples.append({"ref": f"sources/{rel}:{lineno}", "marker": marker})

        if file_has_marker:
            files_with_markers += 1

    return {
        "scanned": True,
        "java_files": java_files,
        "files_with_markers": files_with_markers,
        "warnings": warnings,
        "errors": errors,
        "bad_code_methods": bad_code_methods,
        "samples": samples,
        "oversized": oversized,
        "truncated": truncated,
        "unreadable": unreadable,
        "symlinks": symlinks,
    }


def assess(apk_root: Path, parts: list[dict], cancel: threading.Event | None = None) -> dict:
    """Full slice-8 assessment over every DEX-bearing APK part and ``apk_root/jadx/sources``.

    Returns the obfuscation.json document body: per-DEX and aggregate renaming statistics, protector
    stubs, jadx markers, coverage, declared unknowns and limitations.
    """
    unknowns: list[str] = []
    dex_files: list[dict] = []
    descriptors: list[str] = []
    bytes_scanned = 0
    truncated = False
    dex_parts = 0

    for part in parts:
        if truncated:
            break
        if not part.get("dex"):
            continue

        dex_parts += 1
        part_name = part["name"]
        part_path = part["path"]

        try:
            z = zipfile.ZipFile(part_path)
        except (OSError, zipfile.BadZipFile):
            unknowns.append(f"APK part {part_name} could not be opened for class-table assessment.")
            continue

        with z:
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                entry = info.filename.replace("\\", "/")
                if not _DEX_NAME.fullmatch(entry):
                    continue

                ref = f"{part_name}!{entry}"
                _check_cancel(cancel, "DEX class scan")

                if info.file_size > MAX_DEX_BYTES:
                    unknowns.append(f"{ref} exceeds the {MAX_DEX_BYTES // 2**20} MiB DEX cap; its classes were not assessed.")
                    continue

                if bytes_scanned + info.file_size > MAX_SCAN_BYTES:
                    if not truncated:
                        truncated = True
                        unknowns.append(f"Obfuscation assessment stopped at its {MAX_SCAN_BYTES // 2**30} GiB budget; later DEX files were not assessed.")
                    break

                bytes_scanned += info.file_size

                try:
                    data = z.read(info)
                except (OSError, zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError) as exc:
                    unknowns.append(f"{ref}: DEX could not be read ({exc}); its classes were not assessed.")
                    continue

                try:
                    found = dex_class_descriptors(data, cancel)
                except ValueError as exc:
                    unknowns.append(f"{ref}: DEX class table could not be parsed ({exc}); its classes were not assessed.")
                    continue

                stats = assess_descriptors(found)
                dex_files.append(
                    {
                        "ref": ref,
                        "part": part_name,
                        "dex": entry,
                        "classes": stats["class_count"],
                        "top_level_classes": stats["top_level_classes"],
                        "obfuscated_classes": stats["obfuscated_classes"],
                        "obfuscated_ratio": stats["obfuscated_ratio"],
                    }
                )
                descriptors.extend(found)

    total = assess_descriptors(descriptors)

    heavily = total["top_level_classes"] >= MIN_CLASSES_FOR_RATIO and total["obfuscated_ratio"] >= OBFUSCATION_RATIO_THRESHOLD
    if heavily:
        unknowns.append(f"DEX code exhibits heavy identifier renaming (ProGuard/R8); {round(total['obfuscated_ratio'] * 100)}% of class names are obfuscated.")

    for hit in total["protectors"]:
        unknowns.append(f"DEX contains the {hit['protector']} protector stub {hit['class']}; the real bytecode is likely encrypted and loaded at runtime, so static coverage is incomplete.")

    markers = scan_jadx_markers(apk_root / "jadx" / "sources", cancel)

    if markers["warnings"] or markers["errors"] or markers["bad_code_methods"]:
        unknowns.append(
            f"jadx emitted {markers['warnings']} JADX WARNING and {markers['errors']} JADX ERROR marker(s) and {markers['bad_code_methods']} incorrectly decompiled method(s) across {markers['files_with_markers']} Java file(s); those methods are partial pseudo-code."
        )

    if markers["oversized"]:
        unknowns.append(f"{len(markers['oversized'])} recovered Java file(s) exceeded the {MAX_TEXT_FILE_BYTES // 2**20} MiB scan cap and were not checked for jadx markers.")

    if markers["truncated"]:
        unknowns.append(f"jadx marker scan stopped at its {MAX_SCAN_BYTES // 2**30} GiB budget; later Java files were not checked.")

    for bad in markers["unreadable"]:
        unknowns.append(f"Recovered Java file {bad} could not be read; it was not checked for jadx markers.")

    for link in markers.get("symlinks", []):
        kind = "directory" if link.endswith("/") else "file"
        unknowns.append(f"Recovered Java {kind} {link} is a symlink and was not followed; it was not checked for jadx markers.")

    state = "no_dex" if dex_parts == 0 else ("assessed" if dex_files else "unassessed")
    if state == "unassessed" and not truncated:
        unknowns.append("No DEX class table could be assessed; identifier renaming and protector stubs are unknown.")

    return {
        "state": state,
        "dex_files": dex_files,
        "class_count": total["class_count"],
        "top_level_classes": total["top_level_classes"],
        "obfuscated_classes": total["obfuscated_classes"],
        "obfuscated_ratio": total["obfuscated_ratio"],
        "obfuscated_packages": total["obfuscated_packages"],
        "heavily_obfuscated": heavily,
        "threshold": OBFUSCATION_RATIO_THRESHOLD,
        "min_classes": MIN_CLASSES_FOR_RATIO,
        "samples": total["samples"],
        "protectors": total["protectors"],
        "jadx_markers": markers,
        "coverage": {
            "dex_parts": dex_parts,
            "dex_files": len(dex_files),
            "bytes_scanned": bytes_scanned,
            "truncated": truncated,
        },
        "unknowns": list(dict.fromkeys(unknowns)),
        "limitations": [
            "Identifier renaming is inferred from short class names (ProGuard/R8 style); intentionally short names are counted too.",
            "Protector detection matches known stub class names only; custom or newer packers are not recognised.",
            "jadx markers are counted only in recovered Java; classes jadx did not emit are covered by the decompile evidence.",
            "No target code was executed.",
        ],
    }
