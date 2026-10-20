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
    monkeypatch.setattr("app.reverse_engineering.store.resolve_allowed_path", lambda path, allowed: Path(path).resolve())
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
    resp = client.post(f"/api/investigations/{ident}/ingest", json={"target": str(folder), "background": False})
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
    monkeypatch.setattr("app.reverse_engineering.store.resolve_allowed_path", safety.resolve_allowed_path)
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

# ----- #651 review: sticky close/cancel, tree change detection, FFS reports, RFC-0208 Decision -----

def api_client():
    """ASGI client on the test's own event loop, so background ingests outlive the request."""
    import httpx
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


class BlockedIngest:
    """Parks the ingest thread inside its first member read until the test releases it (no sleeps)."""

    def __init__(self, monkeypatch):
        import threading
        self.entered = threading.Event()
        self.release = threading.Event()
        real = ffs_ingest._digest

        def blocking_digest(stream, *args, **kwargs):
            if not self.entered.is_set():
                self.entered.set()
                assert self.release.wait(30), "test never released the ingest thread"
            return real(stream, *args, **kwargs)

        monkeypatch.setattr(ffs_ingest, "_digest", blocking_digest)

    async def wait_entered(self) -> FFSIngest:
        assert await asyncio.to_thread(self.entered.wait, 30)
        with ffs_ingest._RUNNING_LOCK:
            [worker] = list(ffs_ingest._RUNNING.values())
        return worker


def small_dump(root: Path, name: str, files: int = 3) -> Path:
    folder = root / name
    folder.mkdir()
    for i in range(files):
        (folder / f"m{i}.bin").write_bytes(os.urandom(2048))
    return folder


async def drain_ingest_tasks() -> None:
    await asyncio.wait_for(asyncio.gather(*SERVICE.ingest_tasks, return_exceptions=True), timeout=30)


@pytest.mark.asyncio
async def test_api_cancel_of_a_running_ingest_sticks_when_the_thread_writes_last(ffs_env, allow_loopback_api, monkeypatch):
    """D2's repro: the stale worker row used to overwrite cancelled with interrupted."""
    from app.reverse_engineering import runtime
    monkeypatch.setattr(runtime, "FFS_STOP_WAIT_SECONDS", 0)  # close returns before the thread's last write
    folder = small_dump(ffs_env, "cancel_api")
    blocked = BlockedIngest(monkeypatch)
    try:
        async with api_client() as client:
            ident = (await client.post("/api/investigations/ffs", json={"target": str(folder)})).json()["id"]
            started = await client.post(f"/api/investigations/{ident}/ingest", json={})
            assert started.status_code == 200 and started.json()["ingest"] == "started"
            worker = await blocked.wait_entered()

            cancelled = await client.post(f"/api/investigations/{ident}/cancel")
            assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
            assert not worker.finished.is_set()  # the thread is still inside its block
            blocked.release.set()
            assert await asyncio.to_thread(worker.finished.wait, 30)
            await drain_ingest_tasks()

            row = store.load(ident)
            assert row["status"] == "cancelled"  # the thread's later save did not downgrade it
            assert row["ffs"]["status"] == "cancelled"
            assert [e["event"] for e in row["chain_of_custody"]][-1] == "ingest_interrupted"
            again = await client.post(f"/api/investigations/{ident}/ingest", json={})
            assert again.status_code == 422 and "closed" in again.json()["detail"]
            assert store.load(ident)["status"] == "cancelled"
            assert index_lines(ident) == []  # the in-flight member was abandoned, nothing new indexed
    finally:
        blocked.release.set()


@pytest.mark.asyncio
async def test_service_close_waits_for_the_ingest_thread_and_refuses_new_ingests(ffs_env, monkeypatch):
    folder = small_dump(ffs_env, "close_svc")
    blocked = BlockedIngest(monkeypatch)
    try:
        started = await SERVICE.ingest(str(folder), background=True)
        ident = started["id"]
        worker = await blocked.wait_entered()
        closing = asyncio.create_task(SERVICE.close(ident, None))
        assert await asyncio.to_thread(worker.cancel_event.wait, 30)  # close signalled the thread
        blocked.release.set()
        closed = await asyncio.wait_for(closing, 30)
        assert worker.finished.is_set()  # close returned only after the thread exited
        assert closed["status"] == "closed" and closed["ffs"]["status"] == "cancelled"
        await drain_ingest_tasks()
        assert store.load(ident)["status"] == "closed"
        with pytest.raises(ValueError, match="closed"):
            await SERVICE.ingest(str(folder), investigation_id=ident)
        with pytest.raises(ValueError, match="closed"):
            await FFSIngest(folder, investigation_id=ident).run()
        assert store.load(ident)["status"] == "closed" and not ffs_ingest.running(ident)
    finally:
        blocked.release.set()


@pytest.mark.asyncio
async def test_release_task_cancel_sticks_over_a_running_ingest(ffs_env, monkeypatch):
    from app.reverse_engineering import runtime
    monkeypatch.setattr(runtime, "FFS_STOP_WAIT_SECONDS", 0)
    folder = small_dump(ffs_env, "release_svc")
    blocked = BlockedIngest(monkeypatch)
    try:
        ident = (await SERVICE.ingest(str(folder), task_id="task-rel", background=True))["id"]
        worker = await blocked.wait_entered()
        await SERVICE.release_task("task-rel", cancelled=True)
        assert store.load(ident)["status"] == "cancelled"
        blocked.release.set()
        assert await asyncio.to_thread(worker.finished.wait, 30)
        await drain_ingest_tasks()
        assert store.load(ident)["status"] == "cancelled"
    finally:
        blocked.release.set()


@pytest.mark.asyncio
async def test_close_between_admission_and_start_is_honoured(ffs_env, monkeypatch):
    """A close that lands before the thread registers (cancel() has nothing to signal) still wins."""
    folder = small_dump(ffs_env, "close_window")
    real_prepare = FFSIngest.prepare_investigation

    def prepare_then_owner_cancels(self):
        row = real_prepare(self)
        store.set_status(row["id"], "cancelled")
        return row

    monkeypatch.setattr(FFSIngest, "prepare_investigation", prepare_then_owner_cancels)
    ingest = FFSIngest(folder)
    with pytest.raises(ValueError, match="closed"):
        await ingest.run()
    assert store.load(ingest.investigation_id)["status"] == "cancelled"
    assert not (store.directory(ingest.investigation_id) / "index" / "files.ndjson").exists()
    assert not ffs_ingest.running(ingest.investigation_id)


@pytest.mark.asyncio
async def test_change_in_a_subfolder_mid_ingest_is_detected_and_declared(ffs_env, monkeypatch):
    folder = ffs_env / "tree_change"
    (folder / "a").mkdir(parents=True)
    (folder / "b").mkdir()
    for name in ("a/f1.bin", "a/f2.bin", "a/f3.bin", "b/f4.bin"):
        (folder / name).write_bytes(os.urandom(1024))
    calls = {"n": 0}
    real = ffs_ingest._digest

    def digest_and_tamper(stream, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # a/f1.bin and a/f2.bin are already indexed
            with (folder / "a" / "f1.bin").open("ab") as fh:
                fh.write(b"appended after it was hashed")
            (folder / "a" / "f2.bin").unlink()
            (folder / "a" / "late.bin").write_bytes(b"new")  # a/ was already listed by the walk
        return real(stream, *args, **kwargs)

    monkeypatch.setattr(ffs_ingest, "_digest", digest_and_tamper)
    row = await ingest_source(folder)
    ident = row["id"]
    custody = json.loads((store.directory(ident) / "index" / "custody.json").read_text(encoding="utf-8"))
    # The root directory's own stat did not move, which is why the old check sealed this as unchanged.
    assert custody["source_stat_at_admission"] == ffs_ingest.source_stat(folder)
    assert row["status"] == "completed" and row["ffs"]["coverage"] == "partial"
    assert custody["source_unchanged"] is False
    assert custody["source_changes"] == {"modified": 1, "removed": 1, "added": 1}
    assert "per-member" in custody["change_detection"]
    unknowns = row["ffs"]["unknowns"]
    assert any("changed size or modification time" in u and "a/f1.bin" in u for u in unknowns)
    assert any("disappeared" in u and "a/f2.bin" in u for u in unknowns)
    assert any("appeared" in u and "a/late.bin" in u for u in unknowns)
    result = evidence(ident, "ffs_ingest")["result"]
    assert result["source_unchanged"] is False and set(unknowns) <= set(result["unknowns"])
    assert [e for e in row["chain_of_custody"] if e["event"] == "ingest_completed"][0]["metadata"]["source_unchanged"] is False


@pytest.mark.asyncio
async def test_same_size_rewrite_of_a_nested_member_is_detected(ffs_env, monkeypatch):
    folder = ffs_env / "touch_change"
    (folder / "deep" / "er").mkdir(parents=True)
    (folder / "deep" / "er" / "x.tab").write_bytes(b"\x01" * 512)
    (folder / "z.bin").write_bytes(b"z")
    real = ffs_ingest._digest
    calls = {"n": 0}

    def digest_and_rewrite(stream, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            target = folder / "deep" / "er" / "x.tab"
            target.write_bytes(b"\x02" * 512)  # same size, different bytes
            st = target.stat()
            os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        return real(stream, *args, **kwargs)

    monkeypatch.setattr(ffs_ingest, "_digest", digest_and_rewrite)
    row = await ingest_source(folder)
    assert row["ffs"]["coverage"] == "partial"
    assert any("deep/er/x.tab" in u and "changed" in u for u in row["unknowns"])


@pytest.mark.asyncio
async def test_unchanged_folder_is_verified_member_by_member(ffs_env):
    folder = small_dump(ffs_env, "steady")
    row = await ingest_source(folder)
    custody = json.loads((store.directory(row["id"]) / "index" / "custody.json").read_text(encoding="utf-8"))
    assert custody["source_unchanged"] is True and custody["source_changes"] == {"modified": 0, "removed": 0, "added": 0}
    assert row["ffs"]["coverage"] == "complete" and row["ffs"]["unknowns"] == []


def ingest_finding(ident: str) -> list[dict]:
    eid = evidence(ident, "ffs_ingest")["id"]
    return [{"claim": "The dump was indexed read-only.", "kind": "observation", "evidence_ids": [eid]}]


def test_ffs_report_cites_the_manifest_and_keeps_ingest_unknowns(ffs_env, allow_loopback_api, monkeypatch):
    folder = ffs_env / "report_partial"
    folder.mkdir()
    (folder / "good.txt").write_bytes(b"ok")
    (folder / "bad.bin").write_bytes(b"unreadable")
    real_open = Path.open

    def flaky_open(self, *args, **kwargs):
        if self.name == "bad.bin":
            raise PermissionError("locked by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    ident = asyncio.run(ingest_source(folder))["id"]
    monkeypatch.setattr(Path, "open", real_open)
    custody = json.loads((store.directory(ident) / "index" / "custody.json").read_text(encoding="utf-8"))

    resp = TestClient(app).post(f"/api/investigations/{ident}/report", json={"findings": ingest_finding(ident)})
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["status"] == "partial"  # analyst declared nothing, the ingest's gap still counts
    assert any("could not be read" in u and "bad.bin" in u for u in row["unknowns"])
    report = (store.directory(ident) / "report.md").read_text(encoding="utf-8")
    assert f"Identity: FFS manifest SHA-256 {custody['source_sha256']}" in report
    assert "live browser" not in report and "bad.bin" in report
    saved = json.loads((store.directory(ident) / "report.json").read_text(encoding="utf-8"))
    assert saved["unknowns"] == row["unknowns"]


def test_complete_ffs_report_is_reported_and_analyst_unknowns_are_merged(ffs_env, allow_loopback_api):
    folder = small_dump(ffs_env, "report_clean")
    ident = asyncio.run(ingest_source(folder))["id"]
    client = TestClient(app)
    row = client.post(f"/api/investigations/{ident}/report", json={"findings": ingest_finding(ident)}).json()
    assert row["status"] == "reported" and row["unknowns"] == []
    sha = store.load(ident)["ffs"]["manifest_sha256"]
    assert f"FFS manifest SHA-256 {sha}" in (store.directory(ident) / "report.md").read_text(encoding="utf-8")
    row = client.post(f"/api/investigations/{ident}/report",
                      json={"findings": ingest_finding(ident), "unknowns": ["Is m0.bin encrypted?"]}).json()
    assert row["status"] == "partial" and row["unknowns"] == ["Is m0.bin encrypted?"]


@pytest.mark.asyncio
async def test_report_on_an_unfinished_ingest_is_partial_and_unsealed(ffs_env):
    folder = small_dump(ffs_env, "report_unfinished")
    ident = (await FFSIngest(folder, checkpoint_interval=1, stop_after=1).run())["id"]
    with pytest.raises(ValueError):  # no evidence yet: findings cannot cite anything
        await SERVICE.report(ident, [{"claim": "x", "kind": "observation", "evidence_ids": ["E00001"]}], [], None)
    row = await SERVICE.report(ident, [], ["What else is in the dump?"], None)
    assert row["status"] == "partial"
    assert any("interrupted with 1 file(s) indexed" in u for u in row["unknowns"])
    assert "What else is in the dump?" in row["unknowns"]
    report = (store.directory(ident) / "report.md").read_text(encoding="utf-8")
    assert "Identity: FFS index not sealed" in report and "live browser" not in report


@pytest.mark.asyncio
async def test_api_prepare_ffs_references_the_dump_as_read_only_snapshot(ffs_env, allow_loopback_api, monkeypatch):
    folder = small_dump(ffs_env, "prepare_route")
    before = tree_state(folder)
    async with api_client() as client:
        resp = await client.post("/api/investigations/ffs", json={"target": str(folder), "question": "Autel MS906BT dump",
                                                                  "task_id": "task-prep"})
        assert resp.status_code == 200, resp.text
        prepared = resp.json()
        ident = prepared["id"]
        assert prepared["kind"] == "ffs" and prepared["status"] == "prepared" and prepared["source_type"] == "folder"
        assert prepared["ffs"]["status"] == "prepared" and "snapshot" not in prepared
        row = store.load(ident)
        assert row["snapshot"] == row["target"] == str(folder.resolve())  # referenced in place, not copied
        assert not (store.directory(ident) / "target").exists()
        custody = json.loads((store.directory(ident) / "index" / "custody.json").read_text(encoding="utf-8"))
        assert custody["source"] == str(folder.resolve()) and custody["task_id"] == "task-prep"
        assert [e["event"] for e in row["chain_of_custody"]] == ["source_admitted"]
        assert not (store.directory(ident) / "index" / "files.ndjson").exists()  # prepare does not ingest

        # POST /{id}/ingest starts a background ingest by default; status comes through the detail endpoint.
        started = await client.post(f"/api/investigations/{ident}/ingest", json={})
        assert started.status_code == 200 and started.json()["ingest"] == "started"
        await drain_ingest_tasks()
        detail = (await client.get(f"/api/investigations/{ident}")).json()
        assert detail["status"] == "completed" and detail["ffs"]["files_indexed"] == 3
        assert detail["question"] == "Autel MS906BT dump"
        assert len(index_lines(ident)) == 3 and tree_state(folder) == before

        missing = await client.post("/api/investigations/ffs", json={"target": str(ffs_env / "nope")})
        assert missing.status_code == 422
        mismatch = await client.post("/api/investigations/ffs", json={"target": str(folder), "source_type": "zip"})
        assert mismatch.status_code == 422 and "does not match" in mismatch.json()["detail"]
        from app.tools import safety
        monkeypatch.setattr("app.reverse_engineering.store.resolve_allowed_path", safety.resolve_allowed_path)
        from types import SimpleNamespace
        (ffs_env / "elsewhere").mkdir()
        monkeypatch.setattr("app.api.investigations.load_settings",
                            lambda: SimpleNamespace(allowed_directories=[str(ffs_env / "elsewhere")]))
        refused = await client.post("/api/investigations/ffs", json={"target": str(folder)})
        assert refused.status_code == 422


@pytest.mark.asyncio
async def test_members_are_hashed_in_1_mib_blocks(ffs_env, monkeypatch):
    folder = ffs_env / "blocks"
    folder.mkdir()
    data = os.urandom(2 * 1024 * 1024 + 4096)
    (folder / "big.img").write_bytes(data)
    reads: list[int] = []
    real = ffs_ingest._digest

    class Recorder:
        def __init__(self, stream):
            self.stream = stream

        def read(self, n=-1):
            reads.append(n)
            return self.stream.read(n)

    monkeypatch.setattr(ffs_ingest, "_digest", lambda stream, *a, **kw: real(Recorder(stream), *a, **kw))
    row = await ingest_source(folder)
    assert ffs_ingest.CHUNK_SIZE == 1024 * 1024
    assert reads == [1024 * 1024] * 4  # three data blocks and the EOF read, never smaller or larger
    [entry] = index_lines(row["id"])
    assert entry["sha256"] == hashlib.sha256(data).hexdigest() and entry["bytes"] == len(data)


@pytest.mark.asyncio
async def test_provider_operations_never_touch_the_ffs_snapshot(ffs_env):
    archive = ffs_env / "dump.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.txt", b"a")
    ident = (await ingest_source(archive))["id"]
    for operation in ("materialize_artifact", "open_binary"):
        with pytest.raises(ValueError, match="no provider operations"):
            await SERVICE.call(ident, operation, {}, None)
    assert not (store.directory(ident) / "derived").exists()
    assert store.load(ident)["status"] == "completed"


@pytest.mark.asyncio
async def test_legacy_forensic_rows_use_the_ffs_catalog_guide_and_report(ffs_env):
    from app.reverse_engineering.skill import guide
    folder = small_dump(ffs_env, "legacy")
    ident = (await ingest_source(folder))["id"]
    row = store.load(ident)
    row["kind"] = "forensic"  # a row written by the pre-conformance ingest
    row.pop("ffs")
    store.save(row)
    assert ffs_ingest.LEGACY_KINDS <= ffs_ingest.FFS_KINDS
    catalog = await SERVICE.catalog(ident, None)
    assert catalog["operations"] == [] and "ffs_query" in catalog["workflow"]
    assert "ffs_tab_profile" in guide("forensic")
    store.validate_snapshot(store.load(ident))  # the in-place dump is not re-fingerprinted
    reported = await SERVICE.report(ident, ingest_finding(ident), [], None)
    assert reported["status"] == "partial" and any("Legacy forensic ingest" in u for u in reported["unknowns"])


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


@pytest.mark.asyncio
async def test_short_keyed_tab_member_is_reported_as_anomalous_header(ffs_env):
    keyed_header = bytes.fromhex("415400024e4c06010001000000000aa9300045589400010000") + b"\x00" * 39
    body = b"\x5b" * 10 + bytes(range(0x60, 0x74))
    archive = ffs_env / "autel_short.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("Scan/Vehicle/Domestic/BAICMotor/short.tab", keyed_header[:30])
        z.writestr("Scan/Vehicle/Domestic/BAICMotor/small_body.tab", keyed_header + body)
    row = await ingest_source(archive)
    ident = row["id"]
    lines = {e["path"]: e for e in index_lines(ident)}
    # The 30 zero-heavy header bytes of a 94-byte member must not outvote the body's 0x5b.
    assert lines["Scan/Vehicle/Domestic/BAICMotor/small_body.tab"]["top_byte"] == 0x5B
    assert lines["Scan/Vehicle/Domestic/BAICMotor/short.tab"]["top_byte"] is None

    profile = json.loads((store.directory(ident) / "index" / "tab_profile.json").read_text(encoding="utf-8"))
    rows = {f["path"]: f for f in profile["files"]}
    short = rows["Scan/Vehicle/Domestic/BAICMotor/short.tab"]["container"]
    assert short["anomalies"] == ["truncated keyed header: member is 30 bytes, keyed header needs 64"]
    assert rows["Scan/Vehicle/Domestic/BAICMotor/small_body.tab"]["container"]["anomalies"] == []
    at2 = profile["summary"]["container_census"]["at2"]
    assert at2["anomalous_headers"] == 1
    assert at2["key_ids"] == [{"key_id": 0x94, "files": 2, "dominant_top_byte": 0x5B, "dominant_top_byte_files": 1}]
    tab_ev = evidence(ident, "ffs_tab_profile")
    assert tab_ev["result"]["summary"]["container_census"]["at2"]["anomalous_headers"] == 1
