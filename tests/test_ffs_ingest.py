"""RFC-0208 FFS dump self-ingest (ffs_ingest.py): index format, resume, custody, .tab profile, API, tool."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import zipfile

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.reverse_engineering import apk_sidecar, ffs_ingest, store
from app.reverse_engineering.ffs_ingest import (
    FFSIngest,
    RAW_IMAGE_UNKNOWN,
    detect_magic,
    detect_source_type,
    ingest_source,
    read_index,
    stream_digest_and_magic,
)
from app.reverse_engineering.runtime import SERVICE

FIXTURE_APK = Path(__file__).parent / "fixtures" / "apk" / "minimal_valid.apk"


@pytest.fixture
def ffs_env(tmp_path, monkeypatch):
    """Isolated investigation store; every tmp path is an allowed directory."""
    investigations_root = tmp_path / "investigations_root"
    investigations_root.mkdir()
    monkeypatch.setattr(store, "data_dir", lambda: investigations_root)
    from app.config import load_settings
    settings = load_settings()
    settings.allowed_directories = [str(tmp_path)]
    monkeypatch.setattr("app.reverse_engineering.ffs_ingest.resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    monkeypatch.setattr("app.api.investigations.load_settings", lambda: settings)
    return tmp_path


def index_lines(ident: str) -> list[dict]:
    path = store.directory(ident) / "index" / "files.ndjson"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evidence(ident: str, operation: str) -> dict:
    row = store.load(ident)
    [eid] = [e["id"] for e in row["evidence"] if e["operation"] == operation]
    return json.loads((store.directory(ident) / "evidence" / f"{eid}.json").read_text(encoding="utf-8"))


def tree_state(folder: Path) -> dict[str, tuple[int, int, str]]:
    out = {}
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(folder).as_posix()] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def test_detect_magic_signatures():
    assert "elf" in detect_magic(b"\x7fELF\x02\x01\x01\x00")
    assert "pe" in detect_magic(b"MZ\x90\x00\x03\x00\x00\x00")
    assert "mach" in detect_magic(b"\xfe\xed\xfa\xce")
    assert "java" in detect_magic(b"\xca\xfe\xba\xbe")
    assert detect_magic(b"PK\x03\x04\x14\x00") == "application/zip"
    assert detect_magic(b"\x00" * 257 + b"ustar\x00" + b"\x00" * 250) == "application/x-tar"
    assert detect_magic(b"\x1f\x8b\x08\x00") == "application/gzip"
    assert detect_magic(b"BZh91AY&SY") == "application/x-bzip2"
    assert detect_magic(b"\xfd7zXZ\x00") == "application/x-xz"
    assert detect_magic(b"7z\xbc\xaf\x27\x1c") == "application/x-7z-compressed"
    assert detect_magic(b"\x89PNG\r\n\x1a\n\x00\x00") == "image/png"
    assert detect_magic(b"\xff\xd8\xff\xe0\x00\x10JFIF") == "image/jpeg"
    assert detect_magic(b"%PDF-1.7\n") == "application/pdf"
    assert detect_magic(b"SQLite format 3\x00") == "application/vnd.sqlite3"
    mbr = bytearray(512)
    mbr[510:512] = b"\x55\xaa"
    assert detect_magic(bytes(mbr)) == "raw-image/mbr"
    gpt = bytearray(1024)
    gpt[510:512] = b"\x55\xaa"
    gpt[512:520] = b"EFI PART"
    assert detect_magic(bytes(gpt)) == "raw-image/gpt"
    ext4 = bytearray(2048)
    ext4[1080:1082] = b"\x53\xef"
    assert detect_magic(bytes(ext4)) == "filesystem/ext4"
    assert detect_magic(b"#!/bin/bash\necho hello\n") == "text/x-shellscript"
    assert detect_magic(b'{"key": "value"}') == "application/json"
    assert detect_magic(b"Hello world, plain text.\n") == "text/plain"
    assert detect_magic(b"") == "application/x-empty"


def test_streaming_digest_chunks_without_memory_buffering():
    data = b"FORENSIC_CHUNK_DATA_" * 500
    chunk_events: list[int] = []
    seen: list[bytes] = []
    sha256, size, magic = stream_digest_and_magic(
        io.BytesIO(data), chunk_size=128, on_chunk=chunk_events.append, on_data=seen.append)
    assert sha256 == hashlib.sha256(data).hexdigest()
    assert size == len(data)
    assert len(chunk_events) == (len(data) + 127) // 128
    assert b"".join(seen) == data
    assert magic == "text/plain"


@pytest.mark.asyncio
async def test_folder_ingest_writes_rfc0208_index_custody_and_evidence(ffs_env):
    folder = ffs_env / "extracted_evidence"
    (folder / "nested").mkdir(parents=True)
    (folder / "manifest.txt").write_text("file manifest", encoding="utf-8")
    (folder / "nested" / "config.json").write_text('{"target": "anzu"}', encoding="utf-8")
    before = tree_state(folder)

    row = await ingest_source(folder, task_id="t-ffs")
    ident = row["id"]
    assert row["kind"] == "ffs" and row["status"] == "completed"
    assert row["target"] == str(folder.resolve())
    assert row["progress"]["percent"] == 100.0
    assert row["ffs"]["status"] == "completed" and row["ffs"]["files_indexed"] == 2
    assert row["ffs"]["coverage"] == "complete"
    assert tree_state(folder) == before  # never copied, never modified
    assert not (store.directory(ident) / "target").exists()

    lines = {e["path"]: e for e in index_lines(ident)}
    assert set(lines) == {"manifest.txt", "nested/config.json"}
    manifest = lines["manifest.txt"]
    assert set(manifest) == {"path", "bytes", "sha256", "mtime", "magic_hex", "type"}
    assert manifest["bytes"] == len(b"file manifest")
    assert manifest["sha256"] == hashlib.sha256(b"file manifest").hexdigest()
    assert manifest["magic_hex"] == b"file manifest".hex()
    assert manifest["type"] == "text/plain"
    assert manifest["mtime"].endswith("+00:00")
    assert lines["nested/config.json"]["type"] == "application/json"

    custody = json.loads((store.directory(ident) / "index" / "custody.json").read_text(encoding="utf-8"))
    index_sha = hashlib.sha256((store.directory(ident) / "index" / "files.ndjson").read_bytes()).hexdigest()
    assert custody["source_kind"] == "folder" and custody["task_id"] == "t-ffs"
    assert custody["source_sha256"] == index_sha == custody["manifest"]["sha256"]
    assert custody["sessions"][-1]["outcome"] == "completed" and custody["sessions"][-1]["ended_at"]
    assert custody["tool_version"] == ffs_ingest.TOOL_VERSION

    events = [e["event"] for e in row["chain_of_custody"]]
    assert events[:2] == ["source_admitted", "ingest_started"]
    assert "ingest_completed" in events and "evidence_recorded" in events

    ingest_ev = evidence(ident, "ffs_ingest")
    assert ingest_ev["success"] is True and ingest_ev["target_sha256"] == index_sha
    assert ingest_ev["result"]["file_count"] == 2
    assert ingest_ev["result"]["index"] == "index/files.ndjson"
    assert ingest_ev["result"]["source_unchanged"] is True
    assert "index" not in ingest_ev["result"] or isinstance(ingest_ev["result"]["index"], str)  # no inlined 60 GB index
    tab_ev = evidence(ident, "ffs_tab_profile")
    assert tab_ev["result"]["summary"]["file_count"] == 0  # negative evidence is still citable


@pytest.mark.asyncio
async def test_tab_files_are_profiled_in_the_ingest_pass(ffs_env):
    archive = ffs_env / "autel_root.zip"
    encrypted = os.urandom(128 * 1024)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("Diagnosis/Car/BENZ/enc.tab", encrypted)
        z.writestr("Diagnosis/Car/BENZ/FLAT.TAB", b"\x00" * 4096)
        z.writestr("Diagnosis/readme.txt", b"hello")
    row = await ingest_source(archive)
    ident = row["id"]
    lines = {e["path"]: e for e in index_lines(ident)}
    assert lines["Diagnosis/Car/BENZ/enc.tab"]["entropy"] > 7.9
    assert lines["Diagnosis/Car/BENZ/FLAT.TAB"]["entropy"] == 0.0
    assert "entropy" not in lines["Diagnosis/readme.txt"]
    assert lines["Diagnosis/Car/BENZ/enc.tab"]["sha256"] == hashlib.sha256(encrypted).hexdigest()

    profile = json.loads((store.directory(ident) / "index" / "tab_profile.json").read_text(encoding="utf-8"))
    assert [f["path"] for f in profile["files"]] == ["Diagnosis/Car/BENZ/FLAT.TAB", "Diagnosis/Car/BENZ/enc.tab"]
    assert profile["summary"]["entropy_classes"]["high"] == 1
    assert profile["summary"]["entropy_classes"]["low"] == 1
    tab_ev = evidence(ident, "ffs_tab_profile")
    assert tab_ev["result"]["derived_from"] == evidence(ident, "ffs_ingest")["id"]
    assert tab_ev["result"]["files"][1]["header_hex"] == encrypted[:16].hex()
    assert row["ffs"]["tab_files"] == 2


@pytest.mark.asyncio
async def test_tar_archive_ingest(ffs_env):
    tar_path = ffs_env / "evidence.tar"
    with tarfile.open(tar_path, mode="w") as tar:
        for name, data in (("bin/loader.elf", b"\x7fELF\x02\x01\x01\x00\x00\x00"), ("var/log/syslog", b"sample log\n")):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    assert detect_source_type(tar_path) == "tar"
    row = await ingest_source(tar_path)
    lines = {e["path"]: e for e in index_lines(row["id"])}
    assert "elf" in lines["bin/loader.elf"]["type"]
    assert lines["var/log/syslog"]["type"] == "text/plain"
    assert row["source_type"] == "tar"


@pytest.mark.asyncio
async def test_raw_image_is_a_blob_with_declared_unknown(ffs_env):
    raw_path = ffs_env / "disk.raw"
    raw = bytearray(512)
    raw[510:512] = b"\x55\xaa"
    raw_path.write_bytes(raw)
    row = await ingest_source(raw_path)
    [entry] = index_lines(row["id"])
    assert entry["path"] == "disk.raw" and entry["type"] == "raw-image/mbr" and entry["bytes"] == 512
    assert RAW_IMAGE_UNKNOWN in row["unknowns"]
    assert row["ffs"]["coverage"] == "partial"
    assert RAW_IMAGE_UNKNOWN in evidence(row["id"], "ffs_ingest")["result"]["unknowns"]


@pytest.mark.asyncio
async def test_interrupted_ingest_resumes_without_duplicates_or_drops(ffs_env):
    folder = ffs_env / "resumable_source"
    folder.mkdir()
    for i in range(1, 6):
        (folder / f"file_{i:02d}.txt").write_text(f"content {i}", encoding="utf-8")

    first = await FFSIngest(folder, checkpoint_interval=1, stop_after=2).run()
    ident = first["id"]
    assert first["status"] == "interrupted" and first["ffs"]["status"] == "interrupted"
    assert [e["path"] for e in index_lines(ident)] == ["file_01.txt", "file_02.txt"]
    checkpoint = json.loads((store.directory(ident) / "index" / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "interrupted" and checkpoint["files_indexed"] == 2

    # Simulate a crash mid-append: a torn, newline-less final line must be dropped, not trusted.
    with (store.directory(ident) / "index" / "files.ndjson").open("ab") as fh:
        fh.write(b'{"path": "file_03.txt", "bytes": 9, "sha')

    done = await FFSIngest(folder, investigation_id=ident, checkpoint_interval=1).run()
    assert done["status"] == "completed"
    paths = [e["path"] for e in index_lines(ident)]
    assert paths == [f"file_{i:02d}.txt" for i in range(1, 6)]  # deterministic order, no dupes, no drops
    events = [e["event"] for e in done["chain_of_custody"]]
    assert "ingest_interrupted" in events and "ingest_resumed" in events and "ingest_completed" in events
    custody = json.loads((store.directory(ident) / "index" / "custody.json").read_text(encoding="utf-8"))
    assert [s["outcome"] for s in custody["sessions"]] == ["interrupted", "completed"]
    assert custody["sessions"][1]["resumed_from_files"] == 2

    # A finished index is evidence: re-running is a no-op.
    again = await FFSIngest(folder, investigation_id=ident).run()
    assert len(again["evidence"]) == len(done["evidence"])
    assert len(index_lines(ident)) == 5


def test_corrupt_index_line_fails_closed(tmp_path):
    index = tmp_path / "files.ndjson"
    index.write_bytes(b'{"path": "a", "bytes": 1}\nnot json\n{"path": "b", "bytes": 1}\n')
    with pytest.raises(ValueError, match="Corrupt FFS index line 2"):
        read_index(index)


@pytest.mark.asyncio
async def test_unreadable_member_is_declared_not_dropped(ffs_env, monkeypatch):
    folder = ffs_env / "bad_member"
    folder.mkdir()
    (folder / "good.txt").write_bytes(b"ok")
    (folder / "bad.bin").write_bytes(b"unreadable")
    real_open = Path.open

    def flaky_open(self, *args, **kwargs):
        if self.name == "bad.bin":
            raise PermissionError("locked by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    row = await ingest_source(folder)
    lines = {e["path"]: e for e in index_lines(row["id"])}
    assert lines["bad.bin"]["sha256"] is None and "locked" in lines["bad.bin"]["error"]
    assert lines["good.txt"]["sha256"] == hashlib.sha256(b"ok").hexdigest()
    assert any("could not be read" in u and "bad.bin" in u for u in row["unknowns"])
    assert row["ffs"]["coverage"] == "partial"


@pytest.mark.asyncio
async def test_duplicate_archive_members_are_declared(ffs_env):
    archive = ffs_env / "dupes.zip"
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("a.txt", b"first")
            z.writestr("a.txt", b"second")
    row = await ingest_source(archive)
    [entry] = index_lines(row["id"])
    assert entry["sha256"] == hashlib.sha256(b"first").hexdigest()
    assert any("more than once" in u for u in row["unknowns"])


@pytest.mark.asyncio
async def test_cancel_stops_at_next_block_and_stays_resumable(ffs_env, monkeypatch):
    folder = ffs_env / "cancel_me"
    folder.mkdir()
    for i in range(4):
        (folder / f"f{i}.bin").write_bytes(os.urandom(4096))
    ingest = FFSIngest(folder, checkpoint_interval=1)
    calls = {"n": 0}
    real_digest = ffs_ingest._digest

    def digest_then_cancel(stream, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            ffs_ingest.cancel(ingest.investigation_id)
        return real_digest(stream, *args, **kwargs)

    monkeypatch.setattr(ffs_ingest, "_digest", digest_then_cancel)
    row = await ingest.run()
    assert row["status"] == "interrupted" and row["ffs"]["status"] == "cancelled"
    assert len(index_lines(row["id"])) == 1  # the in-flight member was abandoned, not half-written
    assert not ffs_ingest.running(row["id"])
    monkeypatch.setattr(ffs_ingest, "_digest", real_digest)
    done = await FFSIngest(folder, investigation_id=row["id"]).run()
    assert done["status"] == "completed" and len(index_lines(row["id"])) == 4


@pytest.mark.asyncio
async def test_ingested_folder_dump_feeds_the_apk_sidecar_ffs_origin(ffs_env, monkeypatch):
    """RFC-0207 slice 4 must work against a real RFC-0208 ingest, not only a synthetic index."""
    monkeypatch.setattr(apk_sidecar, "resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    dump = ffs_env / "ffs_dump"
    apk_dir = dump / "data" / "app" / "org.anzu.minimal"
    apk_dir.mkdir(parents=True)
    apk_bytes = FIXTURE_APK.read_bytes()
    (apk_dir / "base.apk").write_bytes(apk_bytes)
    (dump / "system" / "build.prop").parent.mkdir(parents=True)
    (dump / "system" / "build.prop").write_text("ro.product.model=MS906BT\n", encoding="utf-8")

    ffs_row = await ingest_source(dump, task_id="task-ffs")
    found = ffs_ingest.query_index(ffs_row["id"], suffix=".apk")
    assert found["matched"] == 1 and found["items"][0]["path"] == "data/app/org.anzu.minimal/base.apk"
    assert found["items"][0]["type"] == "application/zip"

    apk_row = apk_sidecar.prepare_apk(
        found["items"][0]["path"], "What does the diagnostic app expose?", [], "task-ffs",
        source_type="ffs", ffs_investigation_id=ffs_row["id"],
    )
    assert apk_row["source_kind"] == "ffs_reference"
    assert apk_row["sha256"] == hashlib.sha256(apk_bytes).hexdigest()
    assert (apk_dir / "base.apk").read_bytes() == apk_bytes


def test_query_index_filters_and_pages(ffs_env):
    folder = ffs_env / "q"
    folder.mkdir()
    for name in ("a.tab", "b.TAB", "c.txt", "d.apk"):
        (folder / name).write_bytes(b"x" * 3)
    ident = asyncio.run(ingest_source(folder))["id"]
    tabs = ffs_ingest.query_index(ident, suffix=".tab", limit=1)
    assert tabs["matched"] == 2 and [i["path"] for i in tabs["items"]] == ["a.tab"]
    page2 = ffs_ingest.query_index(ident, suffix=".tab", offset=1, limit=1)
    assert [i["path"] for i in page2["items"]] == ["b.TAB"]
    assert ffs_ingest.query_index(ident, path_contains="C.T")["matched"] == 1
    assert ffs_ingest.query_index(ident, limit=10_000)["limit"] == ffs_ingest.MAX_QUERY_LIMIT


def test_api_ingest_status_files_and_tab_profile(ffs_env, allow_loopback_api):
    client = TestClient(app)
    folder = ffs_env / "api_evidence"
    folder.mkdir()
    (folder / "data.bin").write_bytes(b"\x7fELF\x02\x01\x01\x00")
    (folder / "VW.tab").write_bytes(os.urandom(64 * 1024))

    resp = client.post("/api/investigations/ingest", json={"target": str(folder)})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ident = data["id"]
    assert data["status"] == "completed" and data["kind"] == "ffs"
    assert [e["operation"] for e in data["evidence"]] == ["ffs_ingest", "ffs_tab_profile"]

    detail = client.get(f"/api/investigations/{ident}").json()
    assert detail["progress"]["phase"] == "completed" and detail["ffs"]["files_indexed"] == 2
    status_info = client.get(f"/api/investigations/{ident}/status").json()
    assert status_info["status"] == "completed" and len(status_info["chain_of_custody"]) >= 3

    files = client.get(f"/api/investigations/{ident}/ffs/files", params={"type_contains": "elf"}).json()
    assert files["matched"] == 1 and files["items"][0]["path"] == "data.bin"
    profile = client.get(f"/api/investigations/{ident}/ffs/tab-profile").json()
    assert profile["summary"]["file_count"] == 1 and profile["files"][0]["path"] == "VW.tab"

    ev_id = data["evidence"][0]["id"]
    bundle = client.get(f"/api/investigations/{ident}/evidence/{ev_id}").json()
    assert bundle["operation"] == "ffs_ingest" and bundle["result"]["file_count"] == 2


def test_api_ingest_into_existing_investigation(ffs_env, allow_loopback_api):
    client = TestClient(app)
    folder = ffs_env / "existing_case"
    folder.mkdir()
    (folder / "case.txt").write_text("Case details", encoding="utf-8")
    ident = store.prepare(str(folder), "Initial case study", [str(ffs_env)], None)["id"]
    resp = client.post(f"/api/investigations/{ident}/ingest", json={"target": str(folder)})
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["id"] == ident and row["status"] == "completed" and row["kind"] == "ffs"
    assert row["question"] == "Initial case study"
    other = ffs_env / "other_dump"
    other.mkdir()
    (other / "x").write_bytes(b"x")
    clash = client.post(f"/api/investigations/{ident}/ingest", json={"target": str(other)})
    assert clash.status_code == 422 and "different dump" in clash.json()["detail"]


@pytest.mark.asyncio
async def test_dump_outside_allowed_directories_is_refused(ffs_env, monkeypatch):
    from app.tools import safety
    monkeypatch.setattr("app.reverse_engineering.ffs_ingest.resolve_allowed_path", safety.resolve_allowed_path)
    dump = ffs_env / "outside"
    dump.mkdir()
    (dump / "a.txt").write_bytes(b"a")
    allowed_elsewhere = ffs_env / "allowed"
    allowed_elsewhere.mkdir()
    with pytest.raises(PermissionError):
        await ingest_source(dump, allowed_directories=[])
    with pytest.raises(PermissionError):
        await ingest_source(dump, allowed_directories=[str(allowed_elsewhere)])
    row = await ingest_source(dump, allowed_directories=[str(ffs_env)])
    assert row["status"] == "completed"


def test_api_rejects_missing_and_empty_paths(ffs_env, allow_loopback_api):
    client = TestClient(app)
    assert client.post("/api/investigations/ingest", json={"target": ""}).status_code == 422
    assert client.post("/api/investigations/ingest", json={"target": str(ffs_env / "non_existent")}).status_code == 422
    assert client.get("/api/investigations/" + "0" * 32 + "/ffs/tab-profile").status_code == 404


@pytest.mark.asyncio
async def test_agent_tool_ingests_in_background_and_reports_progress(ffs_env):
    from app.tools.reverse_engineer import ReverseEngineerTool
    folder = ffs_env / "tool_dump"
    folder.mkdir()
    (folder / "a.tab").write_bytes(os.urandom(64 * 1024))  # large enough for ~8.0 bits/byte
    (folder / "b.txt").write_bytes(b"text")
    tool = ReverseEngineerTool(lambda: {"allowed_directories": [str(ffs_env)]})

    started = await tool.execute(action="ingest", target=str(folder), question="Autel dump", _task_id="task-tool")
    assert started.success, started.error
    ident = started.data["id"]
    assert started.data["ingest"] == "started"
    await asyncio.wait_for(asyncio.gather(*SERVICE.ingest_tasks), timeout=30)

    status = await tool.execute(action="ingest_status", investigation_id=ident, _task_id="task-tool")
    assert status.success and status.data["status"] == "completed" and status.data["running"] is False
    query = await tool.execute(action="ffs_query", investigation_id=ident, arguments={"suffix": ".tab"}, _task_id="task-tool")
    assert query.success and query.data["matched"] == 1
    bad = await tool.execute(action="ffs_query", investigation_id=ident, arguments={"glob": "*"}, _task_id="task-tool")
    assert not bad.success and "Unsupported" in bad.error
    tab_id = [e["id"] for e in status.data["evidence"] if e["operation"] == "ffs_tab_profile"][0]
    ev = await tool.execute(action="evidence", investigation_id=ident, evidence_id=tab_id, _task_id="task-tool")
    assert ev.success and ev.data["result"]["summary"]["entropy_classes"]["high"] == 1
    catalog = await tool.execute(action="catalog", investigation_id=ident, _task_id="task-tool")
    assert catalog.success and "ffs_query" in catalog.data["workflow"]
    guide = await tool.execute(action="guide", investigation_id=ident, _task_id="task-tool")
    assert "ffs_tab_profile" in guide.data["skill"]
    other_task = await tool.execute(action="ingest_status", investigation_id=ident, _task_id="someone-else")
    assert not other_task.success


@pytest.mark.asyncio
async def test_tab_container_header_and_xor_key_reach_index_and_profile(ffs_env):
    keyed_header = bytes.fromhex("415400024e4c06010001000000000aa9300045589400010000") + b"\x00" * 39
    tsv = b"52\tAll\t1\t31\t20\t00\t00,00,1B\tN\tY\tY\tNA\r\n" * 50
    archive = ffs_env / "autel_at2.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("Scan/Vehicle/Domestic/BAICMotor/nl_FunctionText.tab", keyed_header + bytes(b ^ 0x37 for b in tsv))
        z.writestr("Scan/Vehicle/Asia/TATA/live_data/0x07_2.tab", bytes(b ^ 0xA5 for b in tsv))
    row = await ingest_source(archive)
    ident = row["id"]
    lines = {e["path"]: e for e in index_lines(ident)}
    keyed = lines["Scan/Vehicle/Domestic/BAICMotor/nl_FunctionText.tab"]
    xored = lines["Scan/Vehicle/Asia/TATA/live_data/0x07_2.tab"]
    assert keyed["tab_header_hex"] == keyed_header.hex() and "xor_key" not in keyed
    assert keyed["top_byte"] == 0x09 ^ 0x37
    assert xored["xor_key"] == 0xA5

    profile = json.loads((store.directory(ident) / "index" / "tab_profile.json").read_text(encoding="utf-8"))
    rows = {f["path"]: f for f in profile["files"]}
    assert rows["Scan/Vehicle/Domestic/BAICMotor/nl_FunctionText.tab"]["container"]["key_id"] == 0x94
    assert rows["Scan/Vehicle/Asia/TATA/live_data/0x07_2.tab"]["container"]["container"] == "unknown"
    census = profile["summary"]["container_census"]
    assert census["at2"]["key_ids"] == [{"key_id": 0x94, "files": 1, "dominant_top_byte": 0x09 ^ 0x37,
                                         "dominant_top_byte_files": 1}]
    assert census["single_byte_xor_text"]["files"] == 1
    tab_ev = evidence(ident, "ffs_tab_profile")
    assert tab_ev["result"]["summary"]["container_census"]["containers"] == {"autel-at2": 1, "unknown": 1}
