"""RFC-0207 slice 1: APK sidecar readiness, intake, decompile orchestration, manifest and API.

Fixtures are synthetic ZIPs built in tmp_path; WSL, apktool and jadx are mocked at the
subprocess.run boundary so no real toolchain or device is needed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reverse_engineering import apk_sidecar, store

LOCK = json.loads(Path(apk_sidecar.provision.LOCK_PATH).read_text(encoding="utf-8"))
APKTOOL_SHA = LOCK["apktool"]["sha256"]
REAL_RUN = subprocess.run

MANIFEST = """<?xml version="1.0" encoding="utf-8" standalone="no"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.anzu.test">
  <uses-permission android:name="android.permission.CAMERA"/>
  <uses-permission android:name="android.permission.INTERNET"/>
  <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>
  <permission android:name="org.anzu.test.PRIVATE" android:protectionLevel="signature"/>
  <application android:debuggable="true" android:allowBackup="true" android:usesCleartextTraffic="true"
               android:networkSecurityConfig="@xml/network_security_config">
    <activity android:name=".MainActivity" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.VIEW"/>
        <category android:name="android.intent.category.BROWSABLE"/>
        <data android:scheme="anzu" android:host="open"/>
      </intent-filter>
    </activity>
    <service android:name=".SyncService" android:exported="false"/>
    <receiver android:name="org.anzu.test.BootReceiver">
      <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED"/></intent-filter>
    </receiver>
    <provider android:name=".DataProvider" android:authorities="org.anzu.test.data" android:exported="true"
              android:readPermission="org.anzu.test.PRIVATE"/>
    <service android:name=".GuardedService" android:exported="true" android:permission="org.anzu.test.PRIVATE"/>
  </application>
</manifest>
"""
APKTOOL_YML = """!!brut.androlib.meta.MetaInfo
sdkInfo:
  minSdkVersion: '26'
  targetSdkVersion: '35'
versionInfo:
  versionCode: '1'
  versionName: 1.0
"""


def make_apk(path: Path, extra: dict[str, bytes] | None = None, dex: bool = True, libs=("arm64-v8a/libtestnative.so",)) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        if dex:
            z.writestr("classes.dex", b"dex\n035\x00synthetic")
        z.writestr("res/values/strings.xml", "<resources><string name='app_name'>T</string></resources>")
        for lib in libs:
            z.writestr(f"lib/{lib}", b"\x7fELF\x02\x01\x01synthetic")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def make_xapk(tmp: Path, name="bundle_split.xapk", manifest=True) -> Path:
    base = make_apk(tmp / "base_src.apk", libs=())
    split = make_apk(tmp / "split_src.apk", dex=False, libs=("arm64-v8a/libsplit.so",))
    out = tmp / name
    with zipfile.ZipFile(out, "w") as z:
        if manifest:
            z.writestr("manifest.json", json.dumps({"package_name": "org.anzu.test", "split_apks": [
                {"file": "base.apk", "id": "base"}, {"file": "config.arm64_v8a.apk", "id": "config.arm64_v8a"}]}))
        z.write(base, "base.apk")
        z.write(split, "config.arm64_v8a.apk")
        z.writestr("Android/obb/org.anzu.test/main.1.org.anzu.test.obb", b"obbdata")
        z.writestr("icon.png", b"png")
    return out


class FakeWSL:
    """Stands in for wsl.exe at subprocess.run; emulates wslpath, test, sha256sum, apktool and jadx."""

    def __init__(self):
        self.present = {apk_sidecar.JDK, apk_sidecar.JADX, apk_sidecar.APKTOOL_JAR}
        self.sha = APKTOOL_SHA
        self.calls: list[tuple[list[str], int]] = []
        self.jadx_mode = "ok"
        self.apktool_mode = "ok"
        self.manifest = MANIFEST

    def __call__(self, args, *a, **kw):
        if not args or args[0] != "wsl.exe":
            return REAL_RUN(args, *a, **kw)
        timeout = kw.get("timeout")
        assert args[:6] == ["wsl.exe", "-d", apk_sidecar.provision.DISTRO, "-u", "root", "--exec"]
        argv = list(args[6:])
        if argv[:2] == ["sh", "-c"]:
            assert argv[2] == 'echo $$ > "$0"; exec "$@"'
            Path(argv[3]).write_text("4242\n", encoding="ascii")
            argv = argv[4:]
        self.calls.append((argv, timeout))
        done = lambda rc=0, out=b"", err=b"": subprocess.CompletedProcess(args, rc, out, err)
        if argv[0] == "wslpath":
            return done(out=(argv[-1] + "\n").encode())
        if argv[0] == "test":
            return done(0 if argv[-1] in self.present else 1)
        if argv[0] == "sha256sum":
            return done(out=f"{self.sha}  {argv[-1]}\n".encode())
        if argv[0] == "/opt/anzu/bin/rea":
            return done(out=b"{}")
        assert argv[0] == "timeout" and argv[1] == "--kill-after=10s"
        if apk_sidecar.APKTOOL_JAR in argv:
            out = Path(argv[argv.index("-o") + 1])
            if self.apktool_mode != "ok":
                return done(1, err=b"brut.androlib.AndrolibException: ERROR decoding")
            out.mkdir(parents=True, exist_ok=True)
            (out / "AndroidManifest.xml").write_text(self.manifest, encoding="utf-8")
            (out / "apktool.yml").write_text(APKTOOL_YML, encoding="utf-8")
            return done(out=b"I: Decoding AndroidManifest.xml")
        if apk_sidecar.JADX in argv:
            out = Path(argv[argv.index("-d") + 1]) / "sources" / "org" / "anzu" / "test"
            out.mkdir(parents=True, exist_ok=True)
            (out / "MainActivity.java").write_text("class MainActivity {}", encoding="utf-8")
            if self.jadx_mode == "timeout":
                return done(124, err=b"")
            if self.jadx_mode == "oom":
                return done(1, err=b"java.lang.OutOfMemoryError: Java heap space")
            return done(out=b"INFO  - done")
        raise AssertionError(f"unexpected argv {argv}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(store, "data_dir", lambda: data)
    monkeypatch.setattr(store, "resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    fake = FakeWSL()
    monkeypatch.setattr(subprocess, "run", fake)
    from app.config import load_settings
    settings = load_settings()
    settings.allowed_directories = [str(tmp_path)]
    monkeypatch.setattr("app.api.investigations.load_settings", lambda: settings)
    src = tmp_path / "src"
    src.mkdir()
    return src, fake


def prepare(path: Path) -> dict:
    return apk_sidecar.prepare_apk(str(path), "What does this app expose?", [], "task-1")


def evidence(row: dict, eid: str) -> dict:
    return json.loads((store.directory(row["id"]) / "evidence" / f"{eid}.json").read_text(encoding="utf-8"))


def test_toolchain_readiness_static(env):
    _, fake = env
    ready = apk_sidecar.readiness_static()
    assert ready["status"] == "ready"
    assert ready["versions"] == {"platform": "WSL2 ANZU-REA", "jdk": "21.0.12.1+1", "jadx": "1.5.6", "apktool": "2.10.0"}
    # No emulator, adb or AVD probe is part of static readiness.
    assert not any("emulator" in " ".join(argv) or "adb" in " ".join(argv) for argv, _ in fake.calls)
    fake.present.discard(apk_sidecar.APKTOOL_JAR)
    missing = apk_sidecar.readiness_static()
    assert missing["status"] == "needs_repair" and missing["stage"] == "Static APK toolchain missing"
    assert missing["error"] == "Missing: apktool; run setup to install"
    fake.present.add(apk_sidecar.APKTOOL_JAR)
    fake.sha = "0" * 64
    assert "pinned SHA-256 mismatch" in apk_sidecar.readiness_static()["error"]


def test_readiness_static_without_wsl(env, monkeypatch):
    def no_wsl(*a, **k):
        raise FileNotFoundError("wsl.exe")
    monkeypatch.setattr(subprocess, "run", no_wsl)
    out = apk_sidecar.readiness_static()
    assert out["status"] == "needs_repair" and "JDK, jadx, apktool" in out["error"]


def test_ingest_standalone_apk(env):
    src, _ = env
    apk = make_apk(src / "minimal_valid.apk")
    row = prepare(apk)
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    assert row["kind"] == "mobile" and row["sha256"] == digest and row["apk"]["format"] == "apk"
    assert row["apk"]["container"] == {"sha256": digest, "bytes": apk.stat().st_size}
    base = row["apk"]["base"]
    assert base["sha256"] == digest and base["dex"] == ["classes.dex"] and base["abis"] == ["arm64-v8a"]
    assert row["evidence"] == [{"id": "E00001", "operation": "apk_unpack", "success": True}]
    e = evidence(row, "E00001")
    assert e["target_sha256"] == digest and e["result"]["parts"][0]["bytes"] == apk.stat().st_size
    assert "path" not in e["result"]["parts"][0]
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["source_sha256"] == digest and custody["verified_digest"] == digest
    assert custody["toolchain"]["apktool"] == "2.10.0" and custody["ingested_at"]
    assert [c["event"] for c in custody["events"]] == ["source_admitted", "apk_unpacked"]


def test_ingest_xapk_and_split_resolution(env):
    src, _ = env
    row = prepare(make_xapk(src))
    apk = row["apk"]
    assert apk["format"] == "xapk" and apk["association"] == "manifest.json"
    assert apk["declared_package"] == "org.anzu.test"
    roles = {p["name"]: p["role"] for p in apk["parts"]}
    assert roles == {"base.apk": "base", "config.arm64_v8a.apk": "split"}
    split = next(p for p in apk["parts"] if p["role"] == "split")
    assert split["native_libs"] == ["lib/arm64-v8a/libsplit.so"] and split["dex"] == []
    assert Path(split["path"]).is_relative_to(store.directory(row["id"]) / "apk" / "staged")
    assert apk["obb"] == [{"path": "Android/obb/org.anzu.test/main.1.org.anzu.test.obb", "bytes": 7}]
    assert apk_sidecar.summary(row["id"])["native_abis"] == ["arm64-v8a"]


def test_xapk_without_manifest_uses_base_name(env):
    src, _ = env
    row = prepare(make_xapk(src, "noman.apks", manifest=False))
    assert row["apk"]["association"] == "base.apk filename" and row["apk"]["base"]["name"] == "base.apk"


def test_ingest_split_directory(env):
    src, _ = env
    d = src / "bundle"
    d.mkdir()
    make_apk(d / "base.apk")
    make_apk(d / "split_config.arm64_v8a.apk", dex=False)
    row = prepare(d)
    assert row["apk"]["format"] == "split_set" and row["apk"]["base"]["name"] == "base.apk"
    assert len(row["apk"]["parts"]) == 2 and row["kind"] == "mobile"


def test_split_directory_needs_base(env):
    src, _ = env
    d = src / "nobase"
    d.mkdir()
    make_apk(d / "a.apk")
    make_apk(d / "b.apk")
    with pytest.raises(ValueError, match="no unambiguous base.apk"):
        prepare(d)


@pytest.mark.parametrize("entry", ["../../etc/passwd", "/abs/evil", "C:/evil.txt", "ok.txt:stream", "a/../../x"])
def test_zip_slip_and_bounds_enforcement(env, entry):
    src, _ = env
    apk = make_apk(src / "malformed_zip_slip.apk", extra={entry: b"pwned"})
    with pytest.raises(ValueError, match="Unsafe archive entry"):
        prepare(apk)
    assert list((store.data_dir() / "investigations").iterdir()) == []
    assert not (src.parent / "etc").exists()


def test_zip_slip_inside_xapk_rejected_before_extraction(env):
    src, _ = env
    out = src / "evil.xapk"
    with zipfile.ZipFile(out, "w") as z:
        z.write(make_apk(src / "b.apk"), "base.apk")
        z.writestr("../escape.apk", b"x")
    with pytest.raises(ValueError, match="Unsafe archive entry"):
        prepare(out)
    assert not (src.parent / "escape.apk").exists()


def test_file_and_size_caps(env, monkeypatch):
    src, _ = env
    apk = make_apk(src / "big.apk")
    monkeypatch.setattr(apk_sidecar, "MAX_FILES", 2)
    with pytest.raises(ValueError, match="expanded size/file limit"):
        prepare(apk)
    monkeypatch.setattr(apk_sidecar, "MAX_FILES", 50000)
    monkeypatch.setattr(apk_sidecar, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="expanded size/file limit"):
        prepare(apk)


def test_rejects_non_zip_and_non_apk(env):
    src, _ = env
    bad = src / "truncated.apk"
    bad.write_bytes(b"not a zip at all")
    with pytest.raises(ValueError, match="not a valid APK/ZIP container"):
        prepare(bad)
    nomanifest = src / "empty.apk"
    with zipfile.ZipFile(nomanifest, "w") as z:
        z.writestr("classes.dex", b"dex")
    with pytest.raises(ValueError, match="AndroidManifest.xml is missing"):
        prepare(nomanifest)
    other = src / "x.txt"
    other.write_text("x")
    with pytest.raises(ValueError, match="must be a .apk"):
        prepare(other)


def test_decompile_pipeline_manifest_and_evidence(env):
    src, fake = env
    row = prepare(make_xapk(src))
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "investigating" and out["unknowns"] == []
    assert [e["operation"] for e in out["evidence"]] == ["apk_unpack", "apk_manifest", "apk_decompile"]
    apktool = next(argv for argv, _ in fake.calls if argv[0] == "timeout" and apk_sidecar.APKTOOL_JAR in argv)
    assert apktool[:3] == ["timeout", "--kill-after=10s", "300s"] and "-Xmx4g" in apktool and "--no-src" in apktool
    jadx_call = next((argv, t) for argv, t in fake.calls if argv[0] == "timeout" and apk_sidecar.JADX in argv)
    assert jadx_call[0][2] == "600s" and "JAVA_OPTS=-Xmx4g -XX:+UseG1GC" in jadx_call[0]
    assert jadx_call[1] == 640 and "--show-bad-code" in jadx_call[0]
    # Only the base APK carries DEX in this fixture, so jadx gets one input.
    assert sum(1 for a in jadx_call[0] if a.endswith(".apk")) == 1

    manifest = apk_sidecar.metadata(row["id"], "manifest")
    assert manifest["package"] == "org.anzu.test"
    assert (manifest["min_sdk"], manifest["target_sdk"], manifest["version_code"]) == ("26", "35", "1")
    assert {a["flag"] for a in manifest["alerts"]} == {"debuggable", "allow_backup", "uses_cleartext_traffic"}
    assert manifest["permissions"]["declared"] == [{"name": "org.anzu.test.PRIVATE", "protection_level": "signature"}]
    assert {p["category"] for p in manifest["permissions"]["high_risk"]} == {"media_hardware", "location"}
    comps = {c["name"]: c for c in apk_sidecar.metadata(row["id"], "components")["components"]}
    assert comps["org.anzu.test.MainActivity"]["exported"] is True
    assert comps["org.anzu.test.MainActivity"]["intent_filters"][0]["data"] == [{"scheme": "anzu", "host": "open"}]
    assert comps["org.anzu.test.SyncService"]["exported"] is False
    assert comps["org.anzu.test.BootReceiver"]["exported_source"] == "implicit_intent_filter"
    assert comps["org.anzu.test.DataProvider"]["authorities"] == "org.anzu.test.data"
    assert comps["org.anzu.test.DataProvider"]["protected"] is False  # read-only permission leaves writes open
    assert comps["org.anzu.test.GuardedService"]["protected"] is True
    assert manifest["attack_surface"] == {"total": 5, "exported": 4, "exported_unprotected_count": 3, "by_type": {
        "activity": {"total": 1, "exported": 1}, "service": {"total": 2, "exported": 1},
        "receiver": {"total": 1, "exported": 1}, "provider": {"total": 1, "exported": 1}}}

    dec = evidence(out, "E00003")["result"]
    assert dec["jadx"]["state"] == "ok" and dec["jadx"]["java_files"] == 1 and dec["manifest_evidence"] == "E00002"
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["decompiled_at"] and custody["completed_at"]
    assert custody["events"][-1]["event"] == "decompile_completed"
    reported = store.write_report(store.load(row["id"]), [{"kind": "observation", "evidence_ids": ["E00002"],
        "claim": "3 exported components lack permission enforcement."}], [])
    assert reported["status"] == "reported"
    s = apk_sidecar.summary(row["id"])
    assert s["package"] == "org.anzu.test" and s["exported_unprotected"] == 3 and s["decompiled"] is True


def test_decompile_timeout_and_graceful_degradation(env):
    src, fake = env
    row = prepare(make_apk(src / "a.apk"))
    fake.jadx_mode = "timeout"
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert any("timed out after 600 s" in u for u in out["unknowns"])
    work = store.directory(row["id"]) / "apk"
    assert (work / "jadx" / ".incomplete").read_text(encoding="utf-8").startswith("jadx timeout")
    assert apk_sidecar.metadata(row["id"], "manifest")["package"] == "org.anzu.test"
    dec = evidence(out, "E00003")
    assert dec["success"] is True and dec["result"]["jadx"]["state"] == "timeout"


def test_decompile_oom_and_apktool_failure(env):
    src, fake = env
    row = prepare(make_apk(src / "a.apk"))
    fake.jadx_mode, fake.apktool_mode = "oom", "fail"
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert any("4 GiB heap" in u for u in out["unknowns"]) and any("apktool" in u for u in out["unknowns"])
    assert [e["operation"] for e in out["evidence"]] == ["apk_unpack", "apk_decompile"]
    with pytest.raises(FileNotFoundError):
        apk_sidecar.metadata(row["id"], "manifest")


def test_subprocess_timeout_is_recorded(env, monkeypatch):
    src, fake = env
    row = prepare(make_apk(src / "a.apk"))

    def slow(args, **kw):
        if args and args[0] == "wsl.exe" and "timeout" in args and apk_sidecar.JADX in args:
            raise subprocess.TimeoutExpired(args, kw.get("timeout"))
        return fake(args, **kw)
    monkeypatch.setattr(subprocess, "run", slow)
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial" and any("timed out" in u for u in out["unknowns"])


def test_decompile_refuses_when_toolchain_missing(env):
    src, fake = env
    row = prepare(make_apk(src / "a.apk"))
    fake.present.clear()
    fake.calls.clear()
    with pytest.raises(RuntimeError, match="Missing: JDK, jadx, apktool"):
        apk_sidecar.decompile(row["id"])
    assert not any(argv[0] == "timeout" for argv, _ in fake.calls)
    assert store.load(row["id"])["status"] == "prepared"


def test_manifest_dtd_rejected(tmp_path):
    p = tmp_path / "AndroidManifest.xml"
    p.write_text('<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "x">]><manifest/>', encoding="utf-8")
    with pytest.raises(ValueError, match="DTD"):
        apk_sidecar.parse_manifest(p)


def test_apk_api_endpoints(env):
    src, _ = env
    client = TestClient(app)
    bad = client.post("/api/investigations/apk/prepare",
                      json={"target": str(make_apk(src / "evil.apk", extra={"../x": b"1"}))})
    assert bad.status_code == 422 and "Unsafe archive entry" in bad.json()["detail"]
    res = client.post("/api/investigations/apk/prepare", json={"source_type": "file", "target": str(make_xapk(src)), "task_id": "t"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "prepared" and len(body["sha256"]) == 64 and "snapshot" not in body
    ident = body["id"]
    assert client.get(f"/api/investigations/{ident}/apk/components").status_code == 404
    assert client.get(f"/api/investigations/{ident}/apk/summary").json()["decompiled"] is False
    dec = client.post(f"/api/investigations/{ident}/apk/decompile", json={"skip_jadx": True})
    assert dec.status_code == 200, dec.text
    assert dec.json()["status"] == "investigating"
    assert client.get(f"/api/investigations/{ident}/apk/manifest").json()["package"] == "org.anzu.test"
    assert client.get(f"/api/investigations/{ident}/apk/components").json()["attack_surface"]["exported"] == 4
    summary = client.get(f"/api/investigations/{ident}/apk/summary").json()
    assert summary["decompiled"] is True and summary["parts"] == 2
    assert client.get("/api/investigations/0123456789abcdef0123456789abcdef/apk/summary").status_code == 404
    assert client.get("/api/investigations/readiness").json()["apk_static"]["status"] == "ready"


FIXTURES = Path(__file__).parent / "fixtures" / "apk"


def test_real_aapt2_built_apk_intake(env):
    """minimal_valid.apk was linked by aapt2 35.0.0 from minimal_valid.AndroidManifest.xml (binary AXML + resources.arsc)."""
    src, _ = env
    real = FIXTURES / "minimal_valid.apk"
    with zipfile.ZipFile(real) as z:
        assert z.read("AndroidManifest.xml")[:4] == b"\x03\x00\x08\x00"  # binary AXML chunk header
        assert "resources.arsc" in z.namelist()
    copy = src / "minimal_valid.apk"
    copy.write_bytes(real.read_bytes())
    row = prepare(copy)
    assert row["sha256"] == hashlib.sha256(real.read_bytes()).hexdigest()
    assert row["apk"]["base"]["entries"] == len(zipfile.ZipFile(real).infolist())
    assert evidence(row, "E00001")["result"]["format"] == "apk"


def test_readiness_split_and_live_check(env, monkeypatch):
    _, fake = env
    from app.reverse_engineering import android
    assert android.readiness_static()["status"] == "ready"
    monkeypatch.setattr(android, "root", lambda: env[0])
    assert android.readiness_dynamic()["status"] == "not_installed"  # emulator absent; static stays ready
    real_call = fake.__call__

    def versions(args, *a, **kw):
        argv = args[6:] if args and args[0] == "wsl.exe" else []
        if "-version" in argv:
            return subprocess.CompletedProcess(args, 0, b"", b'openjdk version "21.0.12" 2026')
        if "--version" in argv:
            return subprocess.CompletedProcess(args, 0, (b"1.5.6" if apk_sidecar.JADX in argv else b"2.10.0"), b"")
        return real_call(args, *a, **kw)
    monkeypatch.setattr(subprocess, "run", versions)
    assert apk_sidecar.readiness_live()["status"] == "ready"

    def wrong(args, *a, **kw):
        argv = args[6:] if args and args[0] == "wsl.exe" else []
        if "--version" in argv and apk_sidecar.APKTOOL_JAR in argv:
            return subprocess.CompletedProcess(args, 0, b"2.9.3", b"")
        return versions(args, *a, **kw)
    monkeypatch.setattr(subprocess, "run", wrong)
    live = apk_sidecar.readiness_live()
    assert live["status"] == "needs_repair" and "apktool" in live["error"]


@pytest.mark.asyncio
async def test_runtime_catalog_exposes_and_runs_apk_operations(env, monkeypatch):
    from types import SimpleNamespace
    from app.reverse_engineering.runtime import Investigations
    src, _ = env
    row = prepare(make_xapk(src))
    service = Investigations()

    async def actor(ident):
        return SimpleNamespace(tools={})
    monkeypatch.setattr(service, "actor", actor)
    monkeypatch.setattr("app.policy.action_gate.gate_side_effect",
                        lambda *a, **k: SimpleNamespace(allowed=True, requires_approval=False, pending_approval_id=None, reason=""))
    catalog = await service.catalog(row["id"], None)
    names = {t["name"] for t in catalog["operations"]}
    assert {"apk_decompile", "apk_extract_manifest"} <= names
    with pytest.raises(ValueError, match="apk_decompile first"):
        await service.call(row["id"], "apk_extract_manifest", {}, None)
    out = await service.call(row["id"], "apk_decompile", {"skip_jadx": True}, None)
    assert out["status"] == "evidence" and [e["operation"] for e in out["evidence"]] == ["apk_manifest", "apk_decompile"]
    got = await service.call(row["id"], "apk_extract_manifest", {}, None)
    assert got["evidence_id"] == "E00002" and got["manifest"]["package"] == "org.anzu.test"


def _norm(manifest: dict, components: dict) -> dict:
    keep = {k: manifest[k] for k in ("package", "version_code", "version_name", "min_sdk", "target_sdk", "permissions")}
    keep["components"] = sorted((c["type"], c["name"], c["exported"], c["exported_source"]) for c in components["components"])
    return keep


def test_host_axml_decoder_matches_source_manifest(tmp_path):
    with zipfile.ZipFile(FIXTURES / "minimal_valid.apk") as z:
        text = apk_sidecar.decode_axml(z.read("AndroidManifest.xml"))
    decoded = tmp_path / "decoded.xml"
    decoded.write_text(text, encoding="utf-8")
    got = _norm(*apk_sidecar.parse_manifest(decoded))
    want = _norm(*apk_sidecar.parse_manifest(FIXTURES / "minimal_valid.AndroidManifest.xml"))
    assert got == want
    assert got["package"] == "org.anzu.test" and got["min_sdk"] == "26" and got["target_sdk"] == "35"
    assert ("activity", "org.anzu.test.MainActivity", True, "explicit") in got["components"]
    with pytest.raises(ValueError):
        apk_sidecar.decode_axml(b"\x03\x00\x08\x00" + b"\xff" * 16)


def test_apktool_failure_falls_back_to_host_axml(env):
    src, fake = env
    copy = src / "minimal_valid.apk"
    copy.write_bytes((FIXTURES / "minimal_valid.apk").read_bytes())
    row = prepare(copy)
    fake.apktool_mode = "fail"
    out = apk_sidecar.decompile(row["id"], skip_jadx=True)
    assert out["status"] == "partial" and any("host AXML decoder" in u for u in out["unknowns"])
    assert evidence(out, "E00002")["result"]["provider"] == "ANZU host AXML decoder"
    assert apk_sidecar.metadata(row["id"], "manifest")["package"] == "org.anzu.test"


def test_preflight_claims_atomically(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk"))
    claimed = apk_sidecar.preflight(row["id"])
    assert claimed["status"] == "analyzing" and store.load(row["id"])["status"] == "analyzing"
    with pytest.raises(ValueError, match="analyzing"):
        apk_sidecar.preflight(row["id"])
    apk_sidecar.release(row["id"])
    assert store.load(row["id"])["status"] == "interrupted"


async def test_android_decompile_routes_to_sidecar_and_cancel_stops_it(env, monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from app.reverse_engineering.runtime import Investigations
    src, fake = env
    copy = src / "minimal_valid.apk"
    copy.write_bytes((FIXTURES / "minimal_valid.apk").read_bytes())
    row = prepare(copy)
    service = Investigations()

    async def actor(ident):
        return SimpleNamespace(tools={})
    monkeypatch.setattr(service, "actor", actor)
    monkeypatch.setattr("app.policy.action_gate.gate_side_effect",
                        lambda *a, **k: SimpleNamespace(allowed=True, requires_approval=False, pending_approval_id=None, reason=""))
    names = {t["name"] for t in (await service.catalog(row["id"], None))["operations"]}
    assert "android_decompile" not in names and "apk_decompile" in names

    started, killed, kills = threading.Event(), threading.Event(), []
    inner = fake.__call__

    def blocking(args, *a, **kw):
        argv = args[6:] if args and args[0] == "wsl.exe" else []
        if argv[:1] == ["kill"]:
            kills.append(argv)
            killed.set()
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if argv[:2] == ["sh", "-c"] and apk_sidecar.APKTOOL_JAR in argv:
            Path(argv[3]).write_text("4242\n", encoding="ascii")
            started.set()
            killed.wait(30)
            return subprocess.CompletedProcess(args, 143, b"", b"Terminated")
        return inner(args, *a, **kw)
    monkeypatch.setattr(subprocess, "run", blocking)
    # The legacy name is redirected to the sidecar for APK investigations.
    task = asyncio.create_task(service.call(row["id"], "android_decompile", {}, None))
    assert await asyncio.to_thread(started.wait, 30)
    assert service.active.get(row["id"]) is task
    closed = await service.close(row["id"], None, cancelled=True)
    assert closed["status"] == "cancelled" and killed.is_set() and task.done()
    assert kills[0] == ["kill", "-TERM", "--", "-4242"]  # exact process group, no pattern matching
    assert (store.directory(row["id"]) / "apk" / "apktool" / ".incomplete").read_text(encoding="utf-8") == "apktool cancelled\n"
    assert store.load(row["id"])["status"] == "cancelled"


REAL_JAVA = os.environ.get("ANZU_TEST_JAVA") or shutil.which("java")
REAL_APKTOOL = os.environ.get("ANZU_TEST_APKTOOL_JAR")
REAL_JADX = os.environ.get("ANZU_TEST_JADX")


@pytest.mark.skipif(not (REAL_JAVA and REAL_APKTOOL and REAL_JADX and Path(REAL_APKTOOL).is_file() and Path(REAL_JADX).is_file()),
                    reason="real toolchain not available; set ANZU_TEST_JAVA, ANZU_TEST_APKTOOL_JAR and ANZU_TEST_JADX")
def test_real_toolchain_decompiles_fixture(env, monkeypatch):
    """Runs the real apktool and jadx on minimal_valid.apk through the sidecar's orchestration, on the host."""
    src, _ = env
    copy = src / "minimal_valid.apk"
    copy.write_bytes((FIXTURES / "minimal_valid.apk").read_bytes())
    row = prepare(copy)
    real_run = REAL_RUN
    mapping = {apk_sidecar.JDK: REAL_JAVA, apk_sidecar.APKTOOL_JAR: REAL_APKTOOL, apk_sidecar.JADX: REAL_JADX}

    def host_wsl(argv, timeout):
        if argv[0] == "wslpath":
            return subprocess.CompletedProcess(argv, 0, (argv[-1] + "\n").encode(), b"")
        if argv[0] == "test":
            return subprocess.CompletedProcess(argv, 0 if Path(mapping[argv[-1]]).is_file() else 1, b"", b"")
        if argv[0] == "sha256sum":
            return subprocess.CompletedProcess(argv, 0, (hashlib.sha256(Path(REAL_APKTOOL).read_bytes()).hexdigest() + "  x").encode(), b"")
        if argv[:2] == ["sh", "-c"]:
            argv = argv[4:]
        assert argv[0] == "timeout"
        cmd, env_vars = argv[3:], dict(os.environ)
        if cmd[0] == "env":
            cmd = cmd[1:]
            while "=" in cmd[0] and not cmd[0].startswith("/"):
                key, value = cmd.pop(0).split("=", 1)
                if key == "JAVA_OPTS":
                    env_vars[key] = value
            env_vars["JAVA_HOME"] = str(Path(REAL_JAVA).resolve().parents[1])
        cmd = [mapping.get(c, c) for c in cmd]
        return real_run(cmd, capture_output=True, timeout=timeout, env=env_vars)
    monkeypatch.setattr(apk_sidecar, "_wsl", host_wsl)
    out = apk_sidecar.decompile(row["id"])
    work = store.directory(row["id"]) / "apk"
    assert (work / "apktool" / "AndroidManifest.xml").is_file(), evidence(out, "E00003")
    manifest = apk_sidecar.metadata(row["id"], "manifest")
    assert manifest["package"] == "org.anzu.test" and manifest["min_sdk"] == "26" and manifest["target_sdk"] == "35"
    assert evidence(out, "E00003")["result"]["apktool"]["state"] == "ok"
    assert evidence(out, "E00003")["result"]["jadx"]["state"] == "skipped"  # the fixture has no DEX


def test_jadx_skipped_without_dex(env):
    src, fake = env
    row = prepare(make_apk(src / "nodex.apk", dex=False))
    out = apk_sidecar.decompile(row["id"])
    assert not any(argv[0] == "timeout" and apk_sidecar.JADX in argv for argv, _ in fake.calls)
    assert evidence(out, "E00003")["result"]["jadx"]["state"] == "skipped" and out["status"] == "investigating"


def test_axml_out_of_range_string_index_raises():
    import struct
    buf = bytearray(zipfile.ZipFile(FIXTURES / "minimal_valid.apk").read("AndroidManifest.xml"))
    off = 8
    while struct.unpack_from("<H", buf, off)[0] != 0x0102:
        off += struct.unpack_from("<I", buf, off + 4)[0]
    struct.pack_into("<i", buf, off + 20, -5)  # element name string index
    with pytest.raises(ValueError, match="out of range"):
        apk_sidecar.decode_axml(bytes(buf))


async def test_failure_before_decompile_releases_claim_and_retry_succeeds(env, monkeypatch):
    from app.reverse_engineering.runtime import Investigations
    src, _ = env
    row = prepare(make_apk(src / "a.apk"))
    service = Investigations()
    real_call = apk_sidecar.call

    def broken(*a, **k):
        raise RuntimeError("worker thread failed before decompile")
    monkeypatch.setattr(apk_sidecar, "call", broken)
    with pytest.raises(RuntimeError, match="before decompile"):
        await service.run_apk(row["id"], "apk_decompile", {})
    assert store.load(row["id"])["status"] == "interrupted"
    assert row["id"] not in service.active
    monkeypatch.setattr(apk_sidecar, "call", real_call)
    out = await service.run_apk(row["id"], "apk_decompile", {})
    assert out["investigation_status"] == "investigating"

    # Same through REST: a failed sync request does not wedge the row in "analyzing".
    other = prepare(make_apk(src / "b.apk"))
    client = TestClient(app)
    monkeypatch.setattr(apk_sidecar, "call", broken)
    assert client.post(f"/api/investigations/{other['id']}/apk/decompile", json={}).status_code == 422
    assert store.load(other["id"])["status"] == "interrupted"
    monkeypatch.setattr(apk_sidecar, "call", real_call)
    ok = client.post(f"/api/investigations/{other['id']}/apk/decompile", json={})
    assert ok.status_code == 200 and ok.json()["status"] == "investigating"


def test_release_is_noop_while_decompile_owns_claim(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk"))
    apk_sidecar.preflight(row["id"])
    apk_sidecar._OWNED.add(row["id"])
    try:
        apk_sidecar.release(row["id"])
        assert store.load(row["id"])["status"] == "analyzing"
    finally:
        apk_sidecar._OWNED.discard(row["id"])
    apk_sidecar.release(row["id"])
    assert store.load(row["id"])["status"] == "interrupted"

# --- RFC-0207 slice 2: native .so inventory ----------------------------------------------

def _elf64_le_with_jni(symbols, pad_high_entropy=False):
    """Tiny little-endian ELF64 shared object with .dynsym/.dynstr carrying the given names."""
    import struct
    shoff = 64
    shentsize = 64
    shnum = 4
    shstr = b"\x00.dynstr\x00.dynsym\x00.shstrtab\x00"
    dynstr = b"\x00" + b"".join(s.encode("ascii") + b"\x00" for s in symbols)
    syms = [struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0)]
    off = 1
    for s in symbols:
        syms.append(struct.pack("<IBBHQQ", off, 0x12, 0, 1, 0x1000, 0x10))
        off += len(s) + 1
    dynsym = b"".join(syms)
    content_off = shoff + shnum * shentsize
    dynstr_off = content_off
    dynsym_off = dynstr_off + len(dynstr)
    align = (8 - (dynsym_off % 8)) % 8
    dynsym_off += align
    shstr_off = dynsym_off + len(dynsym)

    def shdr(name_off, typ, flags, addr, offset, size, link, info, align_v, entsize):
        return struct.pack("<IIQQQQIIQQ", name_off, typ, flags, addr, offset, size, link, info, align_v, entsize)

    sections = [
        shdr(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        shdr(1, 3, 0, 0, dynstr_off, len(dynstr), 0, 0, 1, 0),
        shdr(9, 11, 2, 0, dynsym_off, len(dynsym), 1, 1, 8, 24),
        shdr(17, 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0),
    ]
    ehdr = bytearray(64)
    ehdr[0:4] = b"\x7fELF"
    ehdr[4] = 2
    ehdr[5] = 1
    ehdr[6] = 1
    struct.pack_into("<HHIQQQIHHHHHH", ehdr, 16, 3, 183, 1, 0, 0, shoff, 0, 64, 0, 0, shentsize, shnum, 3)
    blob = bytearray(shstr_off + len(shstr))
    blob[0:64] = ehdr
    for i, sh in enumerate(sections):
        blob[shoff + i * shentsize:shoff + (i + 1) * shentsize] = sh
    blob[dynstr_off:dynstr_off + len(dynstr)] = dynstr
    blob[dynsym_off:dynsym_off + len(dynsym)] = dynsym
    blob[shstr_off:shstr_off + len(shstr)] = shstr
    data = bytes(blob)
    if pad_high_entropy:
        import os
        data = data + os.urandom(4096)
    return data


def test_native_inventory_across_splits(env):
    src, _ = env
    jni_elf = _elf64_le_with_jni(["Java_org_anzu_test_MainActivity_stringFromJNI", "JNI_OnLoad"])
    plain = _elf64_le_with_jni(["not_jni_helper"])
    with zipfile.ZipFile(src / "base.apk", "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        z.writestr("classes.dex", b"dex\n035\x00synthetic")
        z.writestr("lib/arm64-v8a/libengine.so", jni_elf)
        z.writestr("lib/armeabi-v7a/libengine.so", plain)
    with zipfile.ZipFile(src / "config.arm64_v8a.apk", "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        z.writestr("lib/arm64-v8a/libsplit.so", plain)
    out = src / "bundle.xapk"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("manifest.json", json.dumps({"package_name": "org.anzu.test", "split_apks": [
            {"file": "base.apk", "id": "base"}, {"file": "config.arm64_v8a.apk", "id": "config.arm64_v8a"}]}))
        z.write(src / "base.apk", "base.apk")
        z.write(src / "config.arm64_v8a.apk", "config.arm64_v8a.apk")
    row = prepare(out)
    inv = apk_sidecar.apk_inventory_native(row["id"])
    assert inv["library_count"] == 3
    assert inv["abis"] == ["arm64-v8a", "armeabi-v7a"]
    paths = {lib["path"] for lib in inv["libraries"]}
    assert paths == {
        "lib/arm64-v8a/libengine.so",
        "lib/armeabi-v7a/libengine.so",
        "lib/arm64-v8a/libsplit.so",
    }
    arm64_engine = next(lib for lib in inv["libraries"] if lib["path"] == "lib/arm64-v8a/libengine.so")
    assert arm64_engine["elf"]["parseable"] is True
    assert arm64_engine["elf"]["elf_class"] == 64
    assert arm64_engine["elf"]["endian"] == "little"
    assert arm64_engine["elf"]["machine"] == "AArch64"
    assert "Java_org_anzu_test_MainActivity_stringFromJNI" in arm64_engine["jni_exports"]
    assert "JNI_OnLoad" in arm64_engine["jni_exports"]
    assert inv["evidence_id"].startswith("E")
    meta = apk_sidecar.metadata(row["id"], "native")
    assert meta["library_count"] == 3
    e = evidence(store.load(row["id"]), inv["evidence_id"])
    assert e["operation"] == "apk_native_libs" and e["success"] is True
    assert e["result"]["library_count"] == 3
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody.get("native_inventoried_at")
    assert any(ev.get("event") == "apk_native_inventoried" for ev in custody["events"])
    filtered = apk_sidecar.apk_inventory_native(row["id"], abi="armeabi-v7a")
    assert filtered["library_count"] == 1 and filtered["libraries"][0]["abi"] == "armeabi-v7a"
    client = TestClient(app)
    res = client.get(f"/api/investigations/{row['id']}/apk/native")
    assert res.status_code == 200 and res.json()["library_count"] >= 1


def test_native_jni_symbol_extraction(env):
    src, _ = env
    elf = _elf64_le_with_jni([
        "Java_org_anzu_test_Native_foo",
        "JNI_OnLoad",
        "JNI_OnUnload",
        "ordinary_export",
    ])
    apk = src / "jni.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        z.writestr("classes.dex", b"dex\n035\x00synthetic")
        z.writestr("lib/arm64-v8a/libjni.so", elf)
    row = prepare(apk)
    inv = apk_sidecar.apk_inventory_native(row["id"])
    lib = inv["libraries"][0]
    assert set(lib["jni_exports"]) == {
        "Java_org_anzu_test_Native_foo",
        "JNI_OnLoad",
        "JNI_OnUnload",
    }
    assert "ordinary_export" not in lib["jni_exports"]


def test_native_high_entropy_packer_hint(env):
    src, _ = env
    packed = _elf64_le_with_jni(["JNI_OnLoad"], pad_high_entropy=True)
    apk = src / "packed.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        z.writestr("classes.dex", b"dex\n035\x00synthetic")
        z.writestr("lib/arm64-v8a/libsecexe.so", packed)
    row = prepare(apk)
    inv = apk_sidecar.apk_inventory_native(row["id"])
    lib = inv["libraries"][0]
    assert lib["name"] == "libsecexe.so"
    assert lib["entropy"]["high_entropy"] is True
    kinds = {h["kind"] for h in lib["hints"]}
    assert "packer_signature" in kinds and "high_entropy" in kinds
    assert "Bangcle" in inv["packers_detected"]
    assert any("Bangcle" in u for u in inv["unknowns"])
    assert any("high entropy" in u for u in inv["unknowns"])
    junk = src / "junk.apk"
    with zipfile.ZipFile(junk, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        z.writestr("lib/x86_64/libbroken.so", b"not-an-elf-at-all")
    row2 = prepare(junk)
    inv2 = apk_sidecar.apk_inventory_native(row2["id"])
    broken = inv2["libraries"][0]
    assert broken["elf"]["parseable"] is False
    assert len(broken["sha256"]) == 64 and broken["bytes"] == len(b"not-an-elf-at-all")


@pytest.mark.asyncio
async def test_runtime_catalog_exposes_apk_inventory_native(env, monkeypatch):
    from types import SimpleNamespace
    from app.reverse_engineering.runtime import Investigations
    src, _ = env
    elf = _elf64_le_with_jni(["JNI_OnLoad"])
    apk = src / "a.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        z.writestr("lib/arm64-v8a/libx.so", elf)
    row = prepare(apk)
    service = Investigations()

    async def actor(ident):
        return SimpleNamespace(tools={})
    monkeypatch.setattr(service, "actor", actor)
    monkeypatch.setattr("app.policy.action_gate.gate_side_effect",
                        lambda *a, **k: SimpleNamespace(allowed=True, requires_approval=False, pending_approval_id=None, reason=""))
    catalog = await service.catalog(row["id"], None)
    names = {t["name"] for t in catalog["operations"]}
    assert "apk_inventory_native" in names
    out = await service.call(row["id"], "apk_inventory_native", {}, None)
    assert out["status"] == "evidence" and out["native"]["library_count"] == 1
