"""Tests for RFC-0201 forensic image ingest (ffs_ingest.py) and investigations API."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import zipfile

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.reverse_engineering import store
from app.reverse_engineering.ffs_ingest import (
    FFSIngest,
    detect_magic,
    detect_source_type,
    ingest_source,
    stream_digest_and_magic,
)


@pytest.fixture
def ffs_env(tmp_path, monkeypatch):
    """Set up isolated investigation store and allowed directories."""
    investigations_root = tmp_path / "investigations_root"
    investigations_root.mkdir()
    monkeypatch.setattr(store, "data_dir", lambda: investigations_root)

    # Allow tmp_path in settings for path resolution
    from app.config import load_settings
    settings = load_settings()
    settings.allowed_directories = [str(tmp_path)]
    monkeypatch.setattr("app.reverse_engineering.ffs_ingest.resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    monkeypatch.setattr("app.api.investigations.load_settings", lambda: settings)

    return tmp_path


def test_detect_magic_signatures():
    """Verify built-in magic detection identifies key file types and forensic formats."""
    # Executables
    assert "elf" in detect_magic(b"\x7fELF\x02\x01\x01\x00")
    assert "pe" in detect_magic(b"MZ\x90\x00\x03\x00\x00\x00")
    assert "mach" in detect_magic(b"\xfe\xed\xfa\xce")
    assert "java" in detect_magic(b"\xca\xfe\xba\xbe")

    # Archives
    assert detect_magic(b"PK\x03\x04\x14\x00") == "application/zip"
    tar_header = b"\x00" * 257 + b"ustar\x00" + b"\x00" * 250
    assert detect_magic(tar_header) == "application/x-tar"
    assert detect_magic(b"\x1f\x8b\x08\x00") == "application/gzip"
    assert detect_magic(b"BZh91AY&SY") == "application/x-bzip2"
    assert detect_magic(b"\xfd7zXZ\x00") == "application/x-xz"
    assert detect_magic(b"7z\xbc\xaf\x27\x1c") == "application/x-7z-compressed"

    # Images & media
    assert detect_magic(b"\x89PNG\r\n\x1a\n\x00\x00") == "image/png"
    assert detect_magic(b"\xff\xd8\xff\xe0\x00\x10JFIF") == "image/jpeg"
    assert detect_magic(b"GIF89a\x01\x00") == "image/gif"
    assert detect_magic(b"BM\x36\x00") == "image/bmp"

    # Documents & databases
    assert detect_magic(b"%PDF-1.7\n") == "application/pdf"
    assert detect_magic(b"SQLite format 3\x00") == "application/vnd.sqlite3"

    # Forensic & disk structures
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xaa"
    assert detect_magic(bytes(mbr)) == "raw-image/mbr"

    gpt = bytearray(1024)
    gpt[510:512] = b"\x55\xaa"
    gpt[512:520] = b"EFI PART"
    assert detect_magic(bytes(gpt)) == "raw-image/gpt"

    iso = bytearray(33000)
    iso[32769:32774] = b"CD001"
    assert detect_magic(bytes(iso)) == "application/x-iso9660-image"

    ext4 = bytearray(2048)
    ext4[1080:1082] = b"\x53\xef"
    assert detect_magic(bytes(ext4)) == "filesystem/ext4"

    # Text & scripts
    assert detect_magic(b"#!/bin/bash\necho hello\n") == "text/x-shellscript"
    assert detect_magic(b'{"key": "value"}') == "application/json"
    assert detect_magic(b"<?xml version='1.0'?>\n<root/>") == "text/xml"
    assert detect_magic(b"Hello world, plain text.\n") == "text/plain"
    assert detect_magic(b"") == "application/x-empty"


def test_streaming_digest_chunks_without_memory_buffering():
    """Verify streaming reads block-by-block and accumulates SHA-256 and size correctly."""
    data = b"FORENSIC_CHUNK_DATA_" * 500  # 10,500 bytes
    stream = io.BytesIO(data)
    chunk_events: list[int] = []

    sha256, size, magic = stream_digest_and_magic(
        stream,
        chunk_size=128,
        on_chunk=lambda count: chunk_events.append(count),
    )

    import hashlib
    assert sha256 == hashlib.sha256(data).hexdigest()
    assert size == len(data)
    assert len(chunk_events) == (len(data) + 127) // 128
    assert magic == "text/plain"


@pytest.mark.asyncio
async def test_ingest_extracted_folder(ffs_env):
    """Test ingestion of an extracted directory fixture with nested files."""
    folder = ffs_env / "extracted_evidence"
    folder.mkdir()
    (folder / "manifest.txt").write_text("file manifest", encoding="utf-8")
    sub = folder / "nested"
    sub.mkdir()
    (sub / "config.json").write_text('{"target": "anzu"}', encoding="utf-8")

    mtime_before = (folder / "manifest.txt").stat().st_mtime

    result = await ingest_source(folder)
    assert result["status"] == "completed"
    assert result["progress"]["percent"] == 100.0

    # Ensure source was not modified (read-only verification)
    assert (folder / "manifest.txt").stat().st_mtime == mtime_before

    # Verify chain of custody logged in row
    coc = result["chain_of_custody"]
    assert len(coc) >= 2
    events = [entry["event"] for entry in coc]
    assert "ingest_started" in events
    assert "ingest_completed" in events

    # Verify evidence store entry
    ident = result["id"]
    evidence_list = result["evidence"]
    assert len(evidence_list) == 1
    evidence_id = evidence_list[0]["id"]

    ev_path = store.directory(ident) / "evidence" / f"{evidence_id}.json"
    assert ev_path.is_file()
    ev_data = json.loads(ev_path.read_text(encoding="utf-8"))

    assert ev_data["operation"] == "ffs_ingest"
    assert ev_data["success"] is True

    index = ev_data["result"]["index"]
    indexed_paths = {entry["path"]: entry for entry in index}
    assert "manifest.txt" in indexed_paths
    assert "nested/config.json" in indexed_paths

    manifest_entry = indexed_paths["manifest.txt"]
    assert manifest_entry["size"] == len(b"file manifest")
    assert manifest_entry["magic"] == "text/plain"
    assert len(manifest_entry["sha256"]) == 64

    json_entry = indexed_paths["nested/config.json"]
    assert json_entry["magic"] == "application/json"


@pytest.mark.asyncio
async def test_ingest_tar_archive(ffs_env):
    """Test streaming ingest of a tar archive."""
    tar_path = ffs_env / "evidence.tar"
    with tarfile.open(tar_path, mode="w") as tar:
        data1 = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00"
        ti1 = tarfile.TarInfo(name="bin/loader.elf")
        ti1.size = len(data1)
        tar.addfile(ti1, io.BytesIO(data1))

        data2 = b"sample log contents\n"
        ti2 = tarfile.TarInfo(name="var/log/syslog")
        ti2.size = len(data2)
        tar.addfile(ti2, io.BytesIO(data2))

    assert detect_source_type(tar_path) == "tar"

    result = await ingest_source(tar_path)
    assert result["status"] == "completed"

    ev_id = result["evidence"][0]["id"]
    ev_data = json.loads((store.directory(result["id"]) / "evidence" / f"{ev_id}.json").read_text(encoding="utf-8"))
    entries = {e["path"]: e for e in ev_data["result"]["index"]}

    assert "bin/loader.elf" in entries
    assert "var/log/syslog" in entries
    assert "elf" in entries["bin/loader.elf"]["magic"]
    assert entries["var/log/syslog"]["magic"] == "text/plain"


@pytest.mark.asyncio
async def test_ingest_zip_archive(ffs_env):
    """Test streaming ingest of a zip archive."""
    zip_path = ffs_env / "evidence.zip"
    png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    with zipfile.ZipFile(zip_path, mode="w") as z:
        z.writestr("screenshot.png", png_data)
        z.writestr("notes.txt", b"Incident notes")

    assert detect_source_type(zip_path) == "zip"

    result = await ingest_source(zip_path)
    assert result["status"] == "completed"

    ev_id = result["evidence"][0]["id"]
    ev_data = json.loads((store.directory(result["id"]) / "evidence" / f"{ev_id}.json").read_text(encoding="utf-8"))
    entries = {e["path"]: e for e in ev_data["result"]["index"]}

    assert entries["screenshot.png"]["magic"] == "image/png"
    assert entries["notes.txt"]["magic"] == "text/plain"


@pytest.mark.asyncio
async def test_ingest_raw_image_file(ffs_env):
    """Test streaming ingest of a raw forensic image file."""
    raw_path = ffs_env / "disk.raw"
    raw_bytes = bytearray(512)
    raw_bytes[510:512] = b"\x55\xaa"  # MBR signature
    raw_path.write_bytes(raw_bytes)

    assert detect_source_type(raw_path) == "raw"

    result = await ingest_source(raw_path)
    assert result["status"] == "completed"

    ev_id = result["evidence"][0]["id"]
    ev_data = json.loads((store.directory(result["id"]) / "evidence" / f"{ev_id}.json").read_text(encoding="utf-8"))
    entries = ev_data["result"]["index"]
    assert len(entries) == 1
    assert entries[0]["path"] == "disk.raw"
    assert entries[0]["magic"] == "raw-image/mbr"
    assert entries[0]["size"] == 512


@pytest.mark.asyncio
async def test_checkpointing_and_resumability(ffs_env):
    """Verify that an interrupted ingest checkpoints entries and resumes without re-reading."""
    folder = ffs_env / "resumable_source"
    folder.mkdir()
    (folder / "file_01.txt").write_text("first content", encoding="utf-8")
    (folder / "file_02.txt").write_text("second content", encoding="utf-8")
    (folder / "file_03.txt").write_text("third content", encoding="utf-8")

    # Step 1: Run with stop_after=1 to simulate an interruption
    ingest1 = FFSIngest(folder, checkpoint_interval=1, stop_after=1)
    interrupted_row = await ingest1.run()
    ident = interrupted_row["id"]

    assert interrupted_row["status"] == "interrupted"

    checkpoint_file = store.directory(ident) / "checkpoint.json"
    assert checkpoint_file.is_file()
    cp = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    assert cp["status"] == "interrupted"
    assert len(cp["entries"]) == 1

    first_file_path = list(cp["entries"].keys())[0]

    # Step 2: Resume with the same investigation ID without stop_after
    ingest2 = FFSIngest(folder, investigation_id=ident, checkpoint_interval=1)
    resumed_row = await ingest2.run()

    assert resumed_row["status"] == "completed"

    # Verify chain of custody logged resumption
    coc = resumed_row["chain_of_custody"]
    coc_events = [e["event"] for e in coc]
    assert "ingest_resumed" in coc_events
    assert "ingest_completed" in coc_events

    # Verify all 3 files are indexed
    ev_id = resumed_row["evidence"][0]["id"]
    ev_data = json.loads((store.directory(ident) / "evidence" / f"{ev_id}.json").read_text(encoding="utf-8"))
    indexed_files = {e["path"] for e in ev_data["result"]["index"]}
    assert indexed_files == {"file_01.txt", "file_02.txt", "file_03.txt"}

    # Verify checkpoint reflects completed state
    final_cp = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    assert final_cp["status"] == "completed"
    assert len(final_cp["entries"]) == 3


def test_api_investigations_ingest_endpoint(ffs_env, allow_loopback_api):
    """Test the /api/investigations/ingest endpoint and investigation status API."""
    client = TestClient(app)

    folder = ffs_env / "api_evidence"
    folder.mkdir()
    (folder / "data.bin").write_bytes(b"\x7fELF\x02\x01\x01\x00")

    # POST /api/investigations/ingest
    resp = client.post("/api/investigations/ingest", json={"target": str(folder)})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ident = data["id"]
    assert data["status"] == "completed"
    assert len(data["evidence"]) == 1

    # GET /api/investigations/{ident}
    detail_resp = client.get(f"/api/investigations/{ident}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["status"] == "completed"
    assert detail["progress"]["phase"] == "completed"
    assert detail["progress"]["percent"] == 100.0

    # GET /api/investigations/{ident}/status
    status_resp = client.get(f"/api/investigations/{ident}/status")
    assert status_resp.status_code == 200
    status_info = status_resp.json()
    assert status_info["status"] == "completed"
    assert len(status_info["chain_of_custody"]) >= 2

    # GET /api/investigations/{ident}/evidence/{evidence_id}
    ev_id = data["evidence"][0]["id"]
    ev_resp = client.get(f"/api/investigations/{ident}/evidence/{ev_id}")
    assert ev_resp.status_code == 200
    evidence_bundle = ev_resp.json()
    assert evidence_bundle["operation"] == "ffs_ingest"
    assert len(evidence_bundle["result"]["index"]) == 1
    assert "elf" in evidence_bundle["result"]["index"][0]["magic"]


def test_api_investigations_ingest_into_existing(ffs_env, allow_loopback_api):
    """Test POST /api/investigations/{ident}/ingest into an existing investigation."""
    client = TestClient(app)

    folder = ffs_env / "existing_case"
    folder.mkdir()
    (folder / "case.txt").write_text("Case details", encoding="utf-8")

    # Create empty investigation row first
    ident = store.prepare(str(folder), "Initial case study", [str(ffs_env)], None)["id"]

    # Ingest into existing investigation
    resp = client.post(f"/api/investigations/{ident}/ingest", json={"target": str(folder)})
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["id"] == ident
    assert row["status"] == "completed"
    assert len(row["evidence"]) == 1


def test_security_rejects_missing_and_empty_paths(ffs_env, allow_loopback_api):
    """Verify endpoint rejects empty or missing target paths."""
    client = TestClient(app)

    resp_empty = client.post("/api/investigations/ingest", json={"target": ""})
    assert resp_empty.status_code == 422

    resp_missing = client.post("/api/investigations/ingest", json={"target": str(ffs_env / "non_existent")})
    assert resp_missing.status_code == 422
