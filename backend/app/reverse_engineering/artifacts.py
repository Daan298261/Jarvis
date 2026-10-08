"""Execution-free, bounded package materialization and source evidence."""
from __future__ import annotations

import asyncio
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

from . import provision, store


def _extract_zip(source: Path, destination: Path) -> dict:
    files, skipped, size = [], [], 0
    with zipfile.ZipFile(source) as z:
        if len(z.infolist()) > store.MAX_FILES:
            raise ValueError("Archive exceeds file-count limit")
        for item in z.infolist():
            rel = PurePosixPath(item.filename.replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts or ":" in item.filename:
                raise ValueError("Unsafe archive entry")
            if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                skipped.append(item.filename)
                continue
            size += item.file_size
            if size > store.MAX_BYTES:
                raise ValueError("Archive exceeds expanded-size limit")
            if item.is_dir():
                continue
            target = (destination / str(rel)).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Archive entry escapes destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with z.open(item) as src, target.open("wb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    written += len(block)
                    if written > item.file_size:
                        raise ValueError("Archive entry exceeds declared size")
                    dst.write(block)
            files.append(rel.as_posix())
    return {"files": files, "skipped_link_or_encrypted_entries": skipped}


async def materialize(row: dict) -> dict:
    source = Path(row["snapshot"])
    destination = store.directory(row["id"]) / "derived"
    if destination.exists():
        raise ValueError("Derived package directory already exists; reuse it")
    destination.mkdir(mode=0o700)
    if source.suffix.lower() == ".asar":
        script = Path(__file__).with_name("extract-asar.mjs")
        module = provision.runtime_root() / "host/node_modules/@electron/asar/lib/asar.js"
        result = await asyncio.to_thread(subprocess.run,
            [provision.host_node(), str(script), str(module), str(source), str(destination)],
            capture_output=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[-2000:])
        import json
        inventory = json.loads(result.stdout)
    elif zipfile.is_zipfile(source):
        inventory = await asyncio.to_thread(_extract_zip, source, destination)
    else:
        raise ValueError("Materialization supports ZIP/APK/IPA/MSIX/AppX and ASAR")
    return {"provider": "ANZU bounded archive materialization", "root": str(destination),
            **inventory, "limitations": ["Package bytes were extracted without executing code.", "Linked/encrypted entries are not materialized."]}


async def read_source(row: dict, args: dict) -> dict:
    path = (store.directory(row["id"]) / args["path"]).resolve()
    allowed = store.directory(row["id"]).resolve()
    if not path.is_relative_to(allowed) or path.is_symlink():
        raise PermissionError("Source read must remain inside the prepared investigation")
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError("Source file exceeds 2 MiB; select a smaller artifact")
    lines = path.read_text(encoding="utf-8").splitlines()
    start, end = int(args.get("start", 1)), int(args.get("end", min(len(lines), 500)))
    if start < 1 or end < start or end > len(lines) or end - start > 2000:
        raise ValueError("Invalid source line range")
    return {"path": path.relative_to(allowed).as_posix(), "start": start, "end": end,
            "text": "\n".join(lines[start-1:end]), "limitations": ["Text may be recovered/decompiled code; it is not proof of runtime execution."]}


BUILTIN_SCHEMAS = {
    "materialize_artifact": {"name": "materialize_artifact", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "read_artifact_source": {"name": "read_artifact_source", "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path inside this investigation, such as derived/main.js or jadx/sources/org/example/App.java"},
        "start": {"type": "integer", "minimum": 1}, "end": {"type": "integer", "minimum": 1}},
        "required": ["path"], "additionalProperties": False}},
}
