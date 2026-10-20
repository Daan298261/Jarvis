"""RFC-0207 APK sidecar: readiness, intake (file/device/FFS), decompile, manifest, native, endpoints, crypto, API.

Fixtures are synthetic ZIPs built in tmp_path; WSL, apktool and jadx are mocked at the
subprocess.run boundary so no real toolchain or device is needed. ADB is mocked at the
apk_sidecar._ADB_RUN / _adb_bin boundary; FFS origins use a synthetic kind=ffs investigation
with index/files.ndjson.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
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
        self.present = {apk_sidecar.JDK, apk_sidecar.JADX, apk_sidecar.APKTOOL_JAR, apk_sidecar.READELF}
        self.sha = APKTOOL_SHA
        self.calls: list[tuple[list[str], int]] = []
        self.jadx_mode = "ok"
        self.apktool_mode = "ok"
        self.manifest = MANIFEST
        self.readelf_text: str | None = None
        self.readelf_calls: list[list[str]] = []
        self.java_files = {"org/anzu/test/MainActivity.java": "class MainActivity {}"}
        self.apktool_files: dict[str, str] = {}
        self.smali_files = {
            "smali/org/anzu/test/MainActivity.smali":
            ".class public Lorg/anzu/test/MainActivity;\n.super Ljava/lang/Object;\n",
        }

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
        if argv[0] == apk_sidecar.READELF:
            self.readelf_calls.append(argv)
            if self.readelf_text is None:
                return done(127, err=b"readelf: command not found")
            return done(out=self.readelf_text.encode())
        if argv[0] == "/opt/anzu/bin/rea":
            return done(out=b"{}")
        assert argv[0] == "timeout" and argv[1] == "--kill-after=10s"
        if apk_sidecar.APKTOOL_JAR in argv:
            out = Path(argv[argv.index("-o") + 1])
            if self.apktool_mode != "ok":
                return done(1, err=b"brut.androlib.AndrolibException: ERROR decoding")
            out.mkdir(parents=True, exist_ok=True)
            # Phase A uses --no-src (resources only); smali fallback uses --no-res (smali only).
            if "--no-res" not in argv:
                (out / "AndroidManifest.xml").write_text(self.manifest, encoding="utf-8")
                (out / "apktool.yml").write_text(APKTOOL_YML, encoding="utf-8")
                for rel, body in self.apktool_files.items():
                    (out / rel).parent.mkdir(parents=True, exist_ok=True)
                    (out / rel).write_text(body, encoding="utf-8")
            if "--no-src" not in argv:
                for rel, body in self.smali_files.items():
                    (out / rel).parent.mkdir(parents=True, exist_ok=True)
                    (out / rel).write_text(body, encoding="utf-8")
            return done(out=b"I: Decoding AndroidManifest.xml")
        if apk_sidecar.JADX in argv:
            sources = Path(argv[argv.index("-d") + 1]) / "sources"
            if self.jadx_mode != "empty":
                for rel, body in self.java_files.items():
                    (sources / rel).parent.mkdir(parents=True, exist_ok=True)
                    (sources / rel).write_text(body, encoding="utf-8")
            if self.jadx_mode == "timeout":
                return done(124, err=b"")
            if self.jadx_mode == "oom":
                return done(1, err=b"java.lang.OutOfMemoryError: Java heap space")
            if self.jadx_mode == "fail":
                return done(1, err=b"ERROR - Failed to process class org.anzu.test.Broken\nERROR - done with errors")
            if self.jadx_mode == "empty":
                return done(out=b"INFO  - done")
            return done(out=b"INFO  - done")
        raise AssertionError(f"unexpected argv {argv}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(store, "data_dir", lambda: data)
    monkeypatch.setattr(store, "resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    # allowed=[] with a stubbed allow-list: stub the shared gate too (covered in test_re_prepare_allowlist.py).
    monkeypatch.setattr(store, "admit_allowed_target", lambda target, allowed: None)
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
REAL_READELF = os.environ.get("ANZU_TEST_READELF") or shutil.which("readelf")


def _real_host_wsl():
    """A _wsl stand-in that runs the real JDK/apktool/jadx on the host instead of in ANZU-REA."""
    real_run = REAL_RUN
    mapping = {apk_sidecar.JDK: REAL_JAVA, apk_sidecar.APKTOOL_JAR: REAL_APKTOOL, apk_sidecar.JADX: REAL_JADX,
               apk_sidecar.READELF: REAL_READELF or REAL_JAVA}  # readelf is checked by readiness, not run here

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
    return host_wsl


@pytest.mark.skipif(not (REAL_JAVA and REAL_APKTOOL and REAL_JADX and Path(REAL_APKTOOL).is_file() and Path(REAL_JADX).is_file()),
                    reason="real toolchain not available; set ANZU_TEST_JAVA, ANZU_TEST_APKTOOL_JAR and ANZU_TEST_JADX")
def test_real_toolchain_decompiles_fixture(env, monkeypatch):
    """Runs the real apktool and jadx on minimal_valid.apk through the sidecar's orchestration, on the host."""
    src, _ = env
    copy = src / "minimal_valid.apk"
    copy.write_bytes((FIXTURES / "minimal_valid.apk").read_bytes())
    row = prepare(copy)
    monkeypatch.setattr(apk_sidecar, "_wsl", _real_host_wsl())
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


# --- RFC-0207 slice 2 (review fixes): real NDK fixtures, hardening, fallback, caps, claims --

NDK64 = (FIXTURES / "libtestnative_arm64.so").read_bytes()
NDK32 = (FIXTURES / "libtestnative_armv7.so").read_bytes()


def _apk_with_libs(path: Path, libs: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        for name, data in libs.items():
            z.writestr(name, data)
    return path


# --- RFC-0207 slice 3: strings, endpoints and crypto hints --------------------------------

def make_plain_apk(path: Path, entries: dict[str, bytes]) -> Path:
    """APK with the placeholder binary manifest plus exactly the given entries (no defaults)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def _strip_section_headers(data: bytes) -> bytes:
    import struct
    buf = bytearray(data)
    struct.pack_into("<Q", buf, 40, 0)        # e_shoff
    struct.pack_into("<HHH", buf, 58, 0, 0, 0)  # e_shentsize, e_shnum, e_shstrndx
    return bytes(buf)


def test_real_ndk_libraries_full_elf_inventory(env):
    src, fake = env
    row = prepare(_apk_with_libs(src / "ndk.apk", {"lib/arm64-v8a/libtestnative.so": NDK64,
                                                    "lib/armeabi-v7a/libtestnative.so": NDK32}))
    inv = apk_sidecar.apk_inventory_native(row["id"])
    libs = {lib["abi"]: lib for lib in inv["libraries"]}
    a64, a32 = libs["arm64-v8a"], libs["armeabi-v7a"]
    assert a64["elf"]["elf_class"] == 64 and a64["elf"]["machine"] == "AArch64" and a64["elf"]["note"] is None
    assert a32["elf"]["elf_class"] == 32 and a32["elf"]["machine"] == "ARM"
    for lib in (a64, a32):
        assert lib["soname"] == "libtestnative.so"
        assert lib["needed"] == ["liblog.so", "libdl.so", "libc.so"]
        assert set(lib["jni_exports"]) == {"JNI_OnLoad", "Java_org_anzu_test_MainActivity_stringFromJNI"}
        assert lib["hardening"]["executable_stack"] is False
        assert lib["entropy"]["scope"] == "executable segments" and lib["entropy"]["blocks"] >= 1
        assert lib["sha256"] == hashlib.sha256(NDK64 if lib is a64 else NDK32).hexdigest()
        assert (store.directory(row["id"]) / lib["derived_copy"]["path"]).read_bytes() == (NDK64 if lib is a64 else NDK32)
    assert a64["hardening"] == {"relro": "full", "stack_canary": True, "executable_stack": False}
    assert a32["hardening"] == {"relro": "partial", "stack_canary": False, "executable_stack": False}
    assert {h["kind"] for h in a32["hints"]} == {"relro", "no_stack_canary"}
    assert a64["hints"] == [] and fake.readelf_calls == []
    assert inv["unknowns"] == [] and inv["investigation_status"] == "investigating"


def test_readelf_fallback_fills_stripped_section_headers(env):
    src, fake = env
    fake.readelf_text = (FIXTURES / "libtestnative_arm64.readelf.txt").read_text(encoding="ascii")
    row = prepare(_apk_with_libs(src / "stripped.apk", {"lib/arm64-v8a/libtestnative.so": _strip_section_headers(NDK64)}))
    lib = apk_sidecar.apk_inventory_native(row["id"])["libraries"][0]
    assert fake.readelf_calls and fake.readelf_calls[0][:5] == [apk_sidecar.READELF, "-W", "--dynamic", "--dyn-syms", "--program-headers"]
    assert lib["readelf_fallback"] is True and lib["soname"] == "libtestnative.so"
    assert lib["needed"] == ["liblog.so", "libdl.so", "libc.so"]
    assert "Java_org_anzu_test_MainActivity_stringFromJNI" in lib["jni_exports"]
    assert lib["hardening"] == {"relro": "full", "stack_canary": True, "executable_stack": False}


def test_readelf_fallback_failure_is_recorded(env, caplog):
    src, fake = env
    row = prepare(_apk_with_libs(src / "stripped.apk", {"lib/arm64-v8a/libtestnative.so": _strip_section_headers(NDK64)}))
    with caplog.at_level("WARNING"):
        inv = apk_sidecar.apk_inventory_native(row["id"])
    assert any("readelf fallback failed" in u for u in inv["unknowns"])
    assert inv["investigation_status"] == "partial" and "readelf fallback failed" in caplog.text


def test_malformed_elf_variants():
    import struct
    be32 = bytearray(64)
    be32[:6] = b"\x7fELF\x01\x02"
    struct.pack_into(">HH", be32, 16, 3, 40)
    out = apk_sidecar._parse_elf(bytes(be32))
    assert out["parseable"] and out["elf_class"] == 32 and out["endian"] == "big" and out["machine"] == "ARM"
    assert "no section headers" in out["note"]

    bad_sh = bytearray(NDK64)
    struct.pack_into("<H", bad_sh, 60, 4000)  # e_shnum far past the file
    assert "section table truncated" in apk_sidecar._parse_elf(bytes(bad_sh))["note"]

    import zipfile as _z  # locate .dynsym in the real fixture and point it past EOF
    data = bytearray(NDK64)
    shoff = struct.unpack_from("<Q", data, 40)[0]
    shnum = struct.unpack_from("<H", data, 60)[0]
    for i in range(shnum):
        o = shoff + i * 64
        if struct.unpack_from("<I", data, o + 4)[0] == 11:
            struct.pack_into("<Q", data, o + 32, 10 ** 9)  # sh_size
    out = apk_sidecar._parse_elf(bytes(data))
    assert "dynsym/strtab truncated" in out["note"] and out["jni_exports"] == []

    bad_ph = bytearray(NDK32)
    struct.pack_into("<H", bad_ph, 44, 5000)  # e_phnum
    assert "program header table truncated" in apk_sidecar._parse_elf(bytes(bad_ph))["note"]
    assert apk_sidecar._parse_elf(b"\x7fELF\x03\x01" + b"\0" * 60)["note"] == "unsupported ELF class/endian"
    assert apk_sidecar._parse_elf(NDK64[:40])["parseable"] is False


def test_entropy_scores_short_tail_and_is_bounded(monkeypatch):
    import os as _os
    data = b"\0" * 4096 + _os.urandom(1000)
    ent = apk_sidecar._entropy_hints(data)
    assert ent["blocks"] == 2 and ent["tail_bytes"] == 1000 and ent["high_entropy"] is True
    monkeypatch.setattr(apk_sidecar, "MAX_ENTROPY_BYTES", 4096)
    ent = apk_sidecar._entropy_hints(data)
    assert ent["truncated"] is True and ent["scanned_bytes"] == 4096 and ent["high_entropy"] is False
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(apk_sidecar.DecompileCancelled):
        apk_sidecar._entropy_hints(data, None, cancel)


def test_native_caps_abi_filter_and_missing_libs_are_recorded(env, monkeypatch, caplog):
    src, _ = env
    row = prepare(_apk_with_libs(src / "caps.apk", {"lib/arm64-v8a/libbig.so": NDK64,
                                                     "lib/armeabi-v7a/libtestnative.so": NDK32}))
    reads = []
    real_read = apk_sidecar._read_native

    def spy(ident, cand, cancel):
        reads.append(cand["path"])
        return real_read(ident, cand, cancel)
    monkeypatch.setattr(apk_sidecar, "_read_native", spy)
    inv = apk_sidecar.apk_inventory_native(row["id"], abi="armeabi-v7a")
    assert reads == ["lib/armeabi-v7a/libtestnative.so"]  # filter applied before any bytes are read
    monkeypatch.setattr(apk_sidecar, "MAX_NATIVE_BYTES", len(NDK64) - 1)
    reads.clear()
    inv = apk_sidecar.apk_inventory_native(row["id"])
    assert "lib/arm64-v8a/libbig.so" not in reads
    assert any("libbig.so" in u and "over the" in u for u in inv["unknowns"]) and inv["investigation_status"] == "partial"
    # A library recorded at intake but gone from the part is an explicit unknown.
    stored = store.load(row["id"])
    stored["apk"]["parts"][0]["native_libs"].append("lib/x86/libgone.so")
    store.save(stored)
    monkeypatch.setattr(apk_sidecar, "MAX_NATIVE_BYTES", 10 ** 9)

    def broken(ident, cand, cancel):
        raise ValueError("Unsafe native library path")
    monkeypatch.setattr(apk_sidecar, "_read_native", broken)
    with caplog.at_level("WARNING"):
        inv = apk_sidecar.apk_inventory_native(row["id"])
    assert any("libgone.so" in u and "missing" in u for u in inv["unknowns"])
    assert any("could not be read: Unsafe native library path" in u for u in inv["unknowns"])
    assert "could not be read" in caplog.text and inv["library_count"] == 0


def test_native_inventory_takes_claim_and_reloads_row(env):
    src, _ = env
    row = prepare(_apk_with_libs(src / "a.apk", {"lib/arm64-v8a/libtestnative.so": NDK64}))
    claim = apk_sidecar.preflight(row["id"])
    with pytest.raises(ValueError, match="analyzing; cannot start native inventory"):
        apk_sidecar.apk_inventory_native(row["id"])
    apk_sidecar.release(row["id"], claim["_claim_token"])
    # Evidence written by someone else between claim and save is preserved, ids continue after it.
    stored = store.load(row["id"])
    stored["unknowns"] = ["Earlier decompile left a question open."]
    stored["status"] = "investigating"
    store.save(stored)
    inv = apk_sidecar.apk_inventory_native(row["id"])
    after = store.load(row["id"])
    assert inv["evidence_id"] == "E00002" and [e["id"] for e in after["evidence"]] == ["E00001", "E00002"]
    assert after["status"] == "partial"  # merged unknowns, not just this call's
    assert after["chain_of_custody"][-1]["event"] == "apk_native_inventoried"
    assert row["id"] not in apk_sidecar._CLAIMS and row["id"] not in apk_sidecar._CANCEL
    assert "_claim_token" not in json.dumps(after)


def test_native_inventory_cancel_marks_cancelled(env, monkeypatch):
    src, _ = env
    row = prepare(_apk_with_libs(src / "a.apk", {"lib/arm64-v8a/libtestnative.so": NDK64}))
    real = apk_sidecar._entropy_hints

    def cancel_then_score(data, ranges=None, cancel=None):
        apk_sidecar.cancel(row["id"])
        return real(data, ranges, cancel)
    monkeypatch.setattr(apk_sidecar, "_entropy_hints", cancel_then_score)
    with pytest.raises(apk_sidecar.DecompileCancelled):
        apk_sidecar.apk_inventory_native(row["id"])
    after = store.load(row["id"])
    assert after["status"] == "cancelled" and row["id"] not in apk_sidecar._CLAIMS


def test_late_release_cannot_interrupt_newer_claim(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk"))
    first = apk_sidecar.preflight(row["id"])
    apk_sidecar.release(row["id"], first["_claim_token"])
    second = apk_sidecar.preflight(row["id"])
    apk_sidecar.release(row["id"], first["_claim_token"])  # late, stale token
    assert store.load(row["id"])["status"] == "analyzing"
    apk_sidecar.release(row["id"], second["_claim_token"])
    assert store.load(row["id"])["status"] == "interrupted"


def test_cancel_logs_bad_pid_file_and_failed_kill(env, monkeypatch, caplog, tmp_path):
    ident = "f" * 32
    good, bad, gone = tmp_path / "good.pid", tmp_path / "bad.pid", tmp_path / "gone.pid"
    good.write_text("4242", encoding="ascii")
    bad.write_text("not-a-pid", encoding="ascii")
    monkeypatch.setitem(apk_sidecar._CANCEL, ident, threading.Event())
    monkeypatch.setitem(apk_sidecar._RUNNING, ident, [good, bad, gone])
    monkeypatch.setattr(apk_sidecar, "KILL_GRACE", 0)
    monkeypatch.setattr(apk_sidecar, "_wsl", lambda argv, timeout: subprocess.CompletedProcess(argv, 1, b"", b"No such process"))
    with caplog.at_level("WARNING"):
        apk_sidecar.cancel(ident)
    assert "unreadable" in caplog.text and "not a PID" in caplog.text and "exited 1" in caplog.text


# --- RFC-0207 slice 2 (second review): packers, reported rows, native.json ordering, readelf --

def test_dexguard_and_dasho_native_packer_signatures(env):
    assert apk_sidecar._packer_for("libdexguard.so") == "DexGuard"
    assert apk_sidecar._packer_for("libDexGuard_rt.so") == "DexGuard"
    assert apk_sidecar._packer_for("libdgrt.so") == "DexGuard"
    assert apk_sidecar._packer_for("libdasho.so") == "DashO"
    assert apk_sidecar._packer_for("libjiagu.so") == "Qihoo 360"
    assert apk_sidecar._packer_for("libtestnative.so") is None
    src, _ = env
    row = prepare(_apk_with_libs(src / "dg.apk", {"lib/arm64-v8a/libdexguard.so": NDK64,
                                                   "lib/arm64-v8a/libdasho_rt.so": NDK64}))
    inv = apk_sidecar.apk_inventory_native(row["id"])
    assert inv["packers_detected"] == ["DashO", "DexGuard"]
    assert "Native code is protected by DexGuard; static symbols are obscured." in inv["unknowns"]


def test_reported_investigation_is_never_reopened(env):
    src, _ = env
    row = prepare(_apk_with_libs(src / "r.apk", {"lib/arm64-v8a/libtestnative.so": NDK64}))
    stored = store.load(row["id"])
    stored["status"] = "reported"
    store.save(stored)
    with pytest.raises(ValueError, match="reported; cannot start native inventory"):
        apk_sidecar.apk_inventory_native(row["id"])
    with pytest.raises(ValueError, match="reported; cannot start decompilation"):
        apk_sidecar.preflight(row["id"])
    after = store.load(row["id"])
    assert after["status"] == "reported" and len(after["evidence"]) == 1 and row["id"] not in apk_sidecar._CLAIMS


def test_native_json_only_written_after_evidence_is_recorded(env, monkeypatch):
    src, _ = env
    row = prepare(_apk_with_libs(src / "n.apk", {"lib/arm64-v8a/libtestnative.so": NDK64}))
    native_json = store.directory(row["id"]) / "apk" / "metadata" / "native.json"
    # Claim lost before recording: nothing is written.
    claim = apk_sidecar._claim(row["id"], "native inventory")
    apk_sidecar._CLAIMS[row["id"]] = "stale"
    with pytest.raises(RuntimeError, match="claim was lost"):
        apk_sidecar.apk_inventory_native(row["id"], claimed=claim)
    assert not native_json.exists()
    apk_sidecar._CLAIMS.pop(row["id"], None)
    apk_sidecar._CANCEL.pop(row["id"], None)
    stored = store.load(row["id"])
    stored["status"] = "investigating"
    store.save(stored)
    # Save fails after the evidence was recorded: native.json is removed again.
    real_save = store.save

    def failing_save(r):
        if any(c.get("event") == "apk_native_inventoried" for c in r.get("chain_of_custody", [])):
            assert native_json.is_file()
            raise OSError("disk full")
        return real_save(r)
    monkeypatch.setattr(store, "save", failing_save)
    with pytest.raises(OSError, match="disk full"):
        apk_sidecar.apk_inventory_native(row["id"])
    assert not native_json.exists() and store.load(row["id"])["status"] == "interrupted"
    monkeypatch.setattr(store, "save", real_save)
    stored = store.load(row["id"])
    stored["status"] = "investigating"
    store.save(stored)
    inv = apk_sidecar.apk_inventory_native(row["id"])
    assert json.loads(native_json.read_text(encoding="utf-8"))["library_count"] == inv["library_count"] == 1


def test_readiness_requires_readelf(env):
    _, fake = env
    fake.present.discard(apk_sidecar.READELF)
    out = apk_sidecar.readiness_static()
    assert out["status"] == "needs_repair" and out["error"] == "Missing: readelf (binutils); run setup to install"


def test_provision_installs_binutils():
    from app.reverse_engineering import provision
    src = Path(provision.__file__).read_text(encoding="utf-8")
    assert "binutils" in src and "test -x /usr/bin/readelf" in src


@pytest.mark.skipif(not (REAL_READELF and Path(REAL_READELF).is_file()),
                    reason="readelf not available; set ANZU_TEST_READELF or put binutils readelf on PATH")
def test_real_readelf_fallback_on_ndk_fixture(monkeypatch):
    def host_wsl(argv, timeout):
        if argv[0] == "wslpath":
            return subprocess.CompletedProcess(argv, 0, (argv[-1] + "\n").encode(), b"")
        assert argv[0] == apk_sidecar.READELF
        return REAL_RUN([REAL_READELF, *argv[1:]], capture_output=True, timeout=timeout)
    monkeypatch.setattr(apk_sidecar, "_wsl", host_wsl)
    out = apk_sidecar._readelf_fallback("0" * 32, FIXTURES / "libtestnative_arm64.so")
    assert out["soname"] == "libtestnative.so"
    assert out["needed"] == ["liblog.so", "libdl.so", "libc.so"]
    assert set(out["jni_exports"]) == {"JNI_OnLoad", "Java_org_anzu_test_MainActivity_stringFromJNI"}
    assert out["relro"] == "full" and out["stack_canary"] is True and out["executable_stack"] is False


# --- RFC-0207 slice 2 follow-ups: ABI allow-list, e_shstrndx, evidence source, summary counts --

def test_abi_filter_must_be_a_known_android_abi(env):
    src, _ = env
    row = prepare(_apk_with_libs(src / "a.apk", {"lib/arm64-v8a/libtestnative.so": NDK64}))
    for bad in ("arm65", "ARM64-V8A", "x86_64 ", "lib", ""):
        with pytest.raises(ValueError, match="abi must be one of"):
            apk_sidecar.apk_inventory_native(row["id"], abi=bad)
        with pytest.raises(ValueError, match="abi must be one of"):
            apk_sidecar.call(row["id"], "apk_inventory_native", {"abi": bad})
    assert store.load(row["id"])["status"] != "analyzing" and row["id"] not in apk_sidecar._CLAIMS
    schema = apk_sidecar.CATALOG["apk_inventory_native"]["inputSchema"]["properties"]["abi"]
    assert schema["enum"] == list(apk_sidecar.KNOWN_ABIS) and "riscv64" in schema["enum"]
    assert apk_sidecar.apk_inventory_native(row["id"], abi="x86")["library_count"] == 0


def test_section_name_index_is_not_used():
    import struct
    for value in (0, 0xFFFF, 1):
        buf = bytearray(NDK64)
        struct.pack_into("<H", buf, 62, value)  # e_shstrndx
        out = apk_sidecar._parse_elf(bytes(buf))
        assert out["soname"] == "libtestnative.so" and out["note"] is None
        assert "Java_org_anzu_test_MainActivity_stringFromJNI" in out["jni_exports"]


def test_evidence_distinguishes_apk_entry_from_derived_copy(env):
    src, _ = env
    row = prepare(_apk_with_libs(src / "a.apk", {"lib/arm64-v8a/libtestnative.so": NDK64}))
    inv = apk_sidecar.apk_inventory_native(row["id"])
    ev = json.loads((store.directory(row["id"]) / "evidence" / f"{inv['evidence_id']}.json").read_text(encoding="utf-8"))
    lib = ev["result"]["libraries"][0]
    assert lib["source"] == {"kind": "apk_entry", "part": inv["libraries"][0]["part"],
                             "entry": "lib/arm64-v8a/libtestnative.so"}
    assert lib["derived_copy"]["kind"] == "derived_copy" and lib["derived_copy"]["path"].startswith("apk/native/")
    assert lib["derived_copy"]["sha256"] == lib["sha256"] == hashlib.sha256(NDK64).hexdigest()
    copy = store.directory(row["id"]) / lib["derived_copy"]["path"]
    assert copy.read_bytes() == NDK64 and lib["source"]["entry"] != lib["derived_copy"]["path"]


def test_summary_reports_native_counts(env):
    src, _ = env
    row = prepare(_apk_with_libs(src / "a.apk", {"lib/arm64-v8a/libtestnative.so": NDK64,
                                                  "lib/armeabi-v7a/libjiagu.so": NDK32}))
    assert apk_sidecar.summary(row["id"])["native_inventory"] is None
    apk_sidecar.apk_inventory_native(row["id"])
    counts = TestClient(app).get(f"/api/investigations/{row['id']}/apk/summary").json()["native_inventory"]
    assert counts == {"libraries": 2, "abis": ["arm64-v8a", "armeabi-v7a"], "jni_exports": 4,
                      "packers_detected": ["Qihoo 360"], "high_entropy": 0, "partial_or_no_relro": 1,
                      "no_stack_canary": 1, "executable_stack": 0, "unknowns": 1}


def test_readelf_symbol_names_versioned_and_unversioned():
    text = """Symbol table '.dynsym' contains 4 entries:
   Num:    Value          Size Type    Bind   Vis      Ndx Name
     0: 0000000000000000     0 NOTYPE  LOCAL  DEFAULT  UND 
     1: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND __stack_chk_fail@LIBC (2)
     2: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND __android_log_print@LIBLOG
     3: 0000000000000720    48 FUNC    GLOBAL DEFAULT   12 Java_org_anzu_test_MainActivity_stringFromJNI
     4: 0000000000000750    16 FUNC    GLOBAL DEFAULT   12 JNI_OnLoad@@VERS_1.0
"""
    assert apk_sidecar._readelf_symbols(text) == {
        "__stack_chk_fail", "__android_log_print", "Java_org_anzu_test_MainActivity_stringFromJNI", "JNI_OnLoad"}


def test_readelf_gnu_stack_flags_binutils_and_llvm_layouts():
    head = "  GNU_STACK      0x000000 0x0000000000000000 0x0000000000000000 0x000000 0x000000 "
    assert apk_sidecar._readelf_stack_flags(head + "RW  0\n") == "RW"      # binutils
    assert apk_sidecar._readelf_stack_flags(head + "RWE 0x10\n") == "RWE"  # llvm-readelf
    assert apk_sidecar._readelf_stack_flags("no program headers\n") is None


def make_dex(strings: list[str]) -> bytes:
    """Minimal DEX: 0x70-byte header with string_ids_size/off at 0x38/0x3C and MUTF-8 string data."""
    import struct
    header = bytearray(0x70)
    header[:8] = b"dex\n035\x00"
    ids_off = 0x70
    data_off = ids_off + 4 * len(strings)
    data = bytearray()
    offsets = []
    for value in strings:
        offsets.append(data_off + len(data))
        n, uleb = len(value.encode("utf-16-le")) // 2, bytearray()
        while True:
            byte, n = n & 0x7F, n >> 7
            uleb.append(byte | (0x80 if n else 0))
            if not n:
                break
        data += uleb + value.encode("utf-8").replace(b"\x00", b"\xc0\x80") + b"\x00"
    struct.pack_into("<II", header, 0x38, len(strings), ids_off)
    return bytes(header) + b"".join(struct.pack("<I", o) for o in offsets) + bytes(data)


def _string_pool(strings: list[str]) -> bytes:
    import struct
    body = bytearray()
    offsets = []
    for value in strings:
        enc = value.encode("utf-8")
        assert len(value) < 128 and len(enc) < 128
        offsets.append(len(body))
        body += bytes([len(value), len(enc)]) + enc + b"\x00"
    while len(body) % 4:
        body += b"\x00"
    start = 28 + 4 * len(strings)
    head = struct.pack("<HHIIIIII", 0x0001, 28, start + len(body), len(strings), 0, 0x100, start, 0)
    return head + b"".join(struct.pack("<I", o) for o in offsets) + bytes(body)


def make_arsc(strings: list[str]) -> bytes:
    import struct
    pool = _string_pool(strings)
    return struct.pack("<HHII", 0x0002, 12, 12 + len(pool), 0) + pool


def make_binary_nsc() -> bytes:
    """Binary AXML <network-security-config><domain-config cleartextTrafficPermitted=true>
    <domain>legacy.anzu-test.example.com</domain></domain-config></network-security-config>."""
    import struct
    strings = ["network-security-config", "domain-config", "cleartextTrafficPermitted", "domain",
               "legacy.anzu-test.example.com"]
    pool = _string_pool(strings)

    def start(name, attrs=()):
        ext = struct.pack("<iiHHHHHH", -1, name, 20, 20, len(attrs), 0, 0, 0)
        body = b"".join(struct.pack("<iiiHBBI", -1, a, -1, 8, 0, 0x12, 0xFFFFFFFF) for a in attrs)
        return struct.pack("<HHIIi", 0x0102, 16, 16 + len(ext) + len(body), 1, -1) + ext + body

    def end(name):
        return struct.pack("<HHIIi", 0x0103, 16, 24, 1, -1) + struct.pack("<ii", -1, name)

    def text(index):
        return struct.pack("<HHIIi", 0x0104, 16, 28, 1, -1) + struct.pack("<iHBBI", index, 8, 0, 0x03, index)

    chunks = pool + start(0) + start(1, (2,)) + start(3) + text(4) + end(3) + end(1) + end(0)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(chunks)) + chunks


ENDPOINT_DEX_STRINGS = [
    "https://api.anzu-test.example.com/v1/login?x=1",
    "http://schemas.android.com/apk/res/android",
    "http://www.w3.org/2001/XMLSchema-instance",
    "wss://push.anzu-test.example.com:8443/socket",
    "anzu://open/profile",
    "android-resource://org.anzu.test/raw/beep",
    "file:///sdcard/Download/x.bin",
    "content://android.media/external/images",
    "content://org.anzu.test.data/items",
    "10.20.30.40", "8.8.8.8", "127.0.0.1", "0.0.0.0", "255.255.255.255", "169.254.1.1",
    "2001:db8:85a3::8a2e:370:7334", "::1", "fe80::1ff:fe23:4567:890a",
    "https://anzu-test-db.firebaseio.com",
    "my-bucket.s3.amazonaws.com",
    "https://abc123.supabase.co/rest/v1",
    "Lorg/anzu/test/MainActivity;",
    "1.2.3",
]


def _endpoint_apk(path: Path) -> Path:
    strings_xml = ("<resources>\n<string name=\"cdn\">https://cdn.anzu-test.example.com/a?x=1&amp;y=2</string>\n"
                   "<string name=\"ns\">http://apache.org/xml/features/validation</string>\n"
                   "<string name=\"xslt\">http://xml.apache.org/xslt</string>\n</resources>\n")
    return make_plain_apk(path, {
        "classes.dex": make_dex(ENDPOINT_DEX_STRINGS),
        "res/values/strings.xml": strings_xml.encode(),
        "resources.arsc": make_arsc(["https://arsc.anzu-test.example.com/config", "app_name"]),
        "assets/config.json": b'{\n  "live": "ws://10.0.2.2:9000/live"\n}\n',
        "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00https://hidden.example.com",
    })


def test_string_and_endpoint_extraction(env):
    src, _ = env
    row = prepare(_endpoint_apk(src / "a.apk"))
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    by = {(r["category"], r["endpoint"]): r for r in out["endpoints"]}
    values = {c: {e for (cat, e) in by if cat == c} for c in apk_strings_categories()}
    assert {"https://api.anzu-test.example.com/v1/login?x=1", "https://cdn.anzu-test.example.com/a?x=1&y=2",
            "https://arsc.anzu-test.example.com/config", "https://anzu-test-db.firebaseio.com",
            "https://abc123.supabase.co/rest/v1"} <= values["url"]
    assert not any("schemas.android.com" in u or "w3.org" in u or "apache.org" in u for u in values["url"])
    assert not any("hidden.example.com" in u for u in values["url"])  # binary asset is not text-scanned
    assert values["websocket"] == {"wss://push.anzu-test.example.com:8443/socket", "ws://10.0.2.2:9000/live"}
    assert {"anzu://open/profile", "content://org.anzu.test.data/items"} <= values["custom_scheme"]
    assert not any(v.startswith(("android-resource://", "file://", "content://android.", "http", "ws"))
                   for v in values["custom_scheme"])
    assert values["ipv4"] == {"10.20.30.40", "8.8.8.8", "10.0.2.2"}
    assert by[("ipv4", "8.8.8.8")]["scope"] == "public" and by[("ipv4", "10.20.30.40")]["scope"] == "private"
    assert values["ipv6"] == {"2001:db8:85a3::8a2e:370:7334"}
    cloud = out["cloud_services"]
    assert cloud["firebase"] == ["anzu-test-db.firebaseio.com"]
    assert cloud["aws"] == ["my-bucket.s3.amazonaws.com"] and cloud["supabase"] == ["abc123.supabase.co"]
    assert out["filtered"]["xml_namespace"] >= 4 and out["filtered"]["loopback"] >= 1
    assert {"unspecified", "broadcast", "link_local", "platform_scheme"} <= set(out["filtered"])
    api = by[("url", "https://api.anzu-test.example.com/v1/login?x=1")]
    assert api["occurrences"] == 1 and api["references"] == ["a.apk!classes.dex"] and api["sources"] == ["dex"]
    assert by[("url", "https://cdn.anzu-test.example.com/a?x=1&y=2")]["references"] == ["a.apk!res/values/strings.xml:2"]
    assert by[("websocket", "ws://10.0.2.2:9000/live")]["references"] == ["a.apk!assets/config.json:2"]
    assert out["counts"]["url"] == len(values["url"]) and out["endpoint_count"] == len(out["endpoints"])
    assert out["coverage"]["sources"]["dex"] == 1 and out["coverage"]["dex_strings"] == len(ENDPOINT_DEX_STRINGS)
    assert out["coverage"]["java_sources"] is False and any("apk_decompile" in x for x in out["limitations"])
    assert out["unknowns"] == [] and out["investigation_status"] == "investigating"

    assert apk_sidecar.metadata(row["id"], "endpoints")["endpoint_count"] == out["endpoint_count"]
    strings = apk_sidecar.metadata(row["id"], "strings")
    assert "Lorg/anzu/test/MainActivity;" in strings["strings"] and "app_name" in strings["strings"]
    assert strings["unique_strings_stored"] == len(strings["strings"])
    e = evidence(store.load(row["id"]), out["evidence_id"])
    assert e["operation"] == "apk_endpoints" and e["success"] is True
    assert e["result"]["endpoint_count"] == out["endpoint_count"] and e["result"]["counts"]["ipv4"] == 3
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["endpoints_extracted_at"]
    assert custody["events"][-1]["event"] == "apk_endpoints_extracted"

    narrowed = apk_sidecar.apk_extract_endpoints(row["id"], category="ipv4", limit=2)
    assert narrowed["returned"] == 2 and {r["category"] for r in narrowed["endpoints"]} == {"ipv4"}
    assert narrowed["endpoint_count"] == out["endpoint_count"]  # stored document stays complete
    with pytest.raises(ValueError, match="category must be one of"):
        apk_sidecar.apk_extract_endpoints(row["id"], category="smtp")
    with pytest.raises(ValueError, match="limit must be"):
        apk_sidecar.apk_extract_endpoints(row["id"], limit=0)


def apk_strings_categories():
    from app.reverse_engineering import apk_strings
    return apk_strings.ENDPOINT_CATEGORIES


VAULT_JAVA = """package org.anzu.test.crypto;
public class Vault {
    private static final String API_KEY = "AIzaSyD-x9SampleKeyForTestingPurpose123";
    private static final String AWS = "AKIAIOSFODNN7EXAMPLE";
    private static final String client_secret = "Zx8Qp2Lr9Tm4Vn6Bc1Kd7Hs3Jw5Fg0Ae";
    // see https://comment.anzu-test.example.org/ignored
    byte[] enc(byte[] data) throws Exception {
        Cipher c = Cipher.getInstance("AES/ECB/PKCS5Padding");
        Cipher d = Cipher.getInstance("DES");
        Cipher ok = Cipher.getInstance("AES/GCM/NoPadding");
        SecretKeySpec key = new SecretKeySpec("0123456789ABCDEF".getBytes(), "AES");
        IvParameterSpec iv = new IvParameterSpec(new byte[16]);
        c.init(1, key);
        return c.doFinal(data);
    }
    static final String PEM = "-----BEGIN RSA PRIVATE KEY-----\\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu";
}
"""
HASH_JAVA = "\n".join(["package org.anzu.test.crypto;", "public class Hashes {"] + ["    // filler"] * 30 + [
    "    String hashPassword(String password) throws Exception {",
    "        MessageDigest md = MessageDigest.getInstance(\"MD5\");",
    "        return new String(md.digest(password.getBytes()));",
    "    }"] + ["    // filler"] * 30 + [
    "    String cacheKey(byte[] blob) throws Exception {",
    "        return hex(MessageDigest.getInstance(\"SHA-1\").digest(blob));",
    "    }", "}", ""])
KEYSTORE_JAVA = """package org.anzu.test.crypto;
class Keys {
    void load() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
    }
}
"""
NETWORK_JAVA = """package org.anzu.test.net;
public class NetworkClient {
    private static final String BASE = "https://api.anzu-test.example.com/v2";
    // https://comment.anzu-test.example.org/not-a-literal
    String socket() { return "wss://push.anzu-test.example.com/ws"; }
}
"""
NSC_XML = """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="true">
    <trust-anchors>
      <certificates src="system"/>
      <certificates src="user"/>
    </trust-anchors>
  </base-config>
  <domain-config>
    <domain includeSubdomains="true">api.anzu-test.example.com</domain>
    <pin-set expiration="2020-01-01">
      <pin digest="SHA-256">7HIpactkIAq2Y49orFOOQKurWxmmSFZhBCoQYcRhJ3Y=</pin>
    </pin-set>
    <trust-anchors><certificates src="@raw/corp_ca" overridePins="true"/></trust-anchors>
  </domain-config>
  <debug-overrides><trust-anchors><certificates src="user"/></trust-anchors></debug-overrides>
</network-security-config>
"""


def _decompiled_fixture(src: Path, fake) -> dict:
    fake.java_files = {"org/anzu/test/crypto/Vault.java": VAULT_JAVA,
                       "org/anzu/test/crypto/Hashes.java": HASH_JAVA,
                       "org/anzu/test/crypto/Keys.java": KEYSTORE_JAVA,
                       "org/anzu/test/net/NetworkClient.java": NETWORK_JAVA}
    fake.apktool_files = {
        "res/values/strings.xml": "<resources>\n  <string name=\"backend_url\">https://cdn.anzu-test.example.com/</string>\n"
                                  "  <string name=\"maps_api_key\">Qw3rTy8UiOp2AsDfGh5JkLzXcVbNm1</string>\n</resources>\n",
        "res/xml/network_security_config.xml": NSC_XML}
    apk = make_apk(src / "crypto_vulnerable.apk", dex=False, extra={
        "classes.dex": make_dex(["https://api.anzu-test.example.com/v2", "AndroidKeyStore", "Ljavax/crypto/Cipher;"])})
    row = prepare(apk)
    apk_sidecar.decompile(row["id"])
    return row


def test_endpoints_from_decompiled_sources_and_deep_links(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    by = {(r["category"], r["endpoint"]): r for r in out["endpoints"]}
    api = by[("url", "https://api.anzu-test.example.com/v2")]
    assert api["occurrences"] == 2 and set(api["sources"]) == {"dex", "java"}
    assert "sources/org/anzu/test/net/NetworkClient.java:3" in api["references"]
    assert "crypto_vulnerable.apk!classes.dex" in api["references"]
    assert ("websocket", "wss://push.anzu-test.example.com/ws") in by
    assert not any("comment.anzu-test" in e for _, e in by)  # Java comments are not literals
    assert by[("url", "https://cdn.anzu-test.example.com/")]["references"] == ["res/values/strings.xml:2"]
    deep = by[("custom_scheme", "anzu://open")]
    assert deep["deep_link"] is True and deep["component"] == "org.anzu.test.MainActivity"
    assert deep["references"] == ["AndroidManifest.xml (org.anzu.test.MainActivity)"]
    assert not any(e.startswith("http://schemas.android.com") for _, e in by)
    assert out["coverage"]["java_sources"] is True and out["coverage"]["decoded_resources"] is True
    assert out["unknowns"] == [] and out["investigation_status"] == "investigating"


def test_crypto_hints_and_network_security(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    out = apk_sidecar.apk_crypto_hints(row["id"])
    rules: dict[str, list[dict]] = {}
    for f in out["findings"]:
        rules.setdefault(f["rule"], []).append(f)
    google = rules["google_api_key"][0]
    assert google["value"] == "AIzaSyD-x9SampleKeyForTestingPurpose123" and google["masked"] == "AIza…e123"
    assert google["references"] == ["sources/org/anzu/test/crypto/Vault.java:3"]
    assert rules["aws_access_key_id"][0]["value"] == "AKIAIOSFODNN7EXAMPLE"
    assert rules["aws_access_key_id"][0]["severity"] == "critical"
    generic = {f["value"]: f for f in rules["generic_secret"]}
    assert set(generic) == {"Zx8Qp2Lr9Tm4Vn6Bc1Kd7Hs3Jw5Fg0Ae", "Qw3rTy8UiOp2AsDfGh5JkLzXcVbNm1"}  # AIza not duplicated
    assert generic["Qw3rTy8UiOp2AsDfGh5JkLzXcVbNm1"]["references"] == ["res/values/strings.xml:3"]
    pem = rules["private_key_pem"][0]
    assert pem["severity"] == "critical" and pem["value"] == "-----BEGIN RSA PRIVATE KEY-----"
    assert "MIIB" not in json.dumps(out)  # key material is never copied
    ecb = {f["value"] for f in rules["ecb_mode"]}
    assert ecb == {"AES/ECB/PKCS5Padding", "DES"} and "AES/GCM/NoPadding" not in json.dumps(rules.get("ecb_mode"))
    assert {f["value"] for f in rules["weak_cipher"]} == {"DES"}
    assert rules["static_key"][0]["value"] == "0123456789ABCDEF"
    assert rules["static_iv"][0]["detail"].startswith("IV is a zero-filled byte[16]")
    hashes = {f["value"]: f for f in rules["weak_hash"]}
    assert hashes["MD5"]["severity"] == "warning" and hashes["MD5"]["context"] == "password_or_signature"
    assert hashes["SHA-1"]["severity"] == "info" and hashes["SHA-1"]["context"] == "general"
    assert hashes["MD5"]["references"] == ["sources/org/anzu/test/crypto/Hashes.java:34"]

    user = rules["nsc_user_trust_anchor"]
    assert user[0]["severity"] == "high" and user[0]["scope"] == "base-config"
    assert rules["nsc_debug_user_trust_anchor"][0]["severity"] == "high"  # manifest is debuggable
    assert rules["nsc_cleartext_permitted"][0]["scope"] == "base-config"
    pinning = rules["nsc_certificate_pinning"][0]
    assert pinning["domains"] == ["api.anzu-test.example.com"] and pinning["pins"] == 1
    assert rules["nsc_pin_set_expired"][0]["expiration"] == "2020-01-01"
    assert rules["nsc_override_pins"][0]["scope"] == "domain-config"
    nsc = out["network_security_config"]
    assert nsc["present"] is True and nsc["referenced_by_manifest"] is True
    assert nsc["source"] == "res/xml/network_security_config.xml"
    assert nsc["base_config"]["trust_anchors"] == [{"src": "system", "override_pins": False},
                                                    {"src": "user", "override_pins": False}]
    assert out["key_storage"]["posture"] == "android_keystore"
    assert out["key_storage"]["indicators"]["android_keystore"]["occurrences"] == 2  # Java literal + DEX string
    assert "software_only_keys" not in rules
    assert out["by_severity"]["critical"] == 2 and out["alert_count"] == sum(
        1 for f in out["findings"] if f["severity"] in {"critical", "high", "warning"})
    order = [apk_sidecar_severity(f["severity"]) for f in out["findings"]]
    assert order == sorted(order)

    stored = apk_sidecar.metadata(row["id"], "crypto")
    assert stored["finding_count"] == out["finding_count"]
    e = evidence(store.load(row["id"]), out["evidence_id"])
    assert e["operation"] == "apk_crypto_hints" and e["result"]["alert_count"] == out["alert_count"]
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["crypto_hints_extracted_at"]
    assert custody["events"][-1]["event"] == "apk_crypto_hints_extracted"


def apk_sidecar_severity(severity: str) -> int:
    from app.reverse_engineering.apk_strings import SEVERITY_ORDER
    return SEVERITY_ORDER[severity]


def test_crypto_hints_from_dex_strings_and_binary_nsc(env):
    src, _ = env
    apk = make_plain_apk(src / "dexonly.apk", {
        "classes.dex": make_dex(["AES/ECB/PKCS5Padding", "AES/GCM/NoPadding", "RSA/ECB/NoPadding",
                                 "RSA/ECB/OAEPWithSHA-256AndMGF1Padding", "Ljavax/crypto/Cipher;",
                                 "Ljavax/crypto/spec/SecretKeySpec;", "AES", "DES"]),
        "res/xml/network_security_config.xml": make_binary_nsc()})
    row = prepare(apk)
    out = apk_sidecar.apk_crypto_hints(row["id"])
    rules = {(f["rule"], f.get("value")): f for f in out["findings"]}
    ecb = rules[("ecb_mode", "AES/ECB/PKCS5Padding")]
    assert ecb["confidence"] == "medium" and ecb["references"] == ["dexonly.apk!classes.dex"]
    assert ("rsa_no_padding", "RSA/ECB/NoPadding") in rules
    assert not any(v in {"AES/GCM/NoPadding", "RSA/ECB/OAEPWithSHA-256AndMGF1Padding", "AES", "DES"}
                   for _, v in rules)  # safe modes and bare names in pools are not flagged
    assert ("ecb_mode", "RSA/ECB/NoPadding") not in rules  # ECB is meaningless for RSA
    assert out["key_storage"]["posture"] == "software_only"
    assert rules[("software_only_keys", None)]["confidence"] == "medium"
    nsc = out["network_security_config"]
    assert nsc["present"] is True and nsc["referenced_by_manifest"] is None
    assert nsc["source"] == "dexonly.apk!res/xml/network_security_config.xml"
    assert nsc["domain_configs"][0]["domains"] == [{"name": "legacy.anzu-test.example.com", "include_subdomains": False}]
    cleartext = next(f for f in out["findings"] if f["rule"] == "nsc_cleartext_permitted")
    assert cleartext["domains"] == ["legacy.anzu-test.example.com"] and cleartext["severity"] == "warning"
    assert any("apk_decompile" in x for x in out["limitations"])
    assert any("No decoded manifest" in x for x in out["limitations"])


def test_dex_and_arsc_string_pool_parsers():
    from app.reverse_engineering import apk_strings
    values = ["plain", "nul\x00inside", "caf\u00e9", "emoji \U0001F600"]
    dex = bytearray(make_dex(values[:3]))
    assert apk_strings.dex_strings(bytes(dex)) == values[:3]
    with pytest.raises(ValueError, match="not a DEX"):
        apk_strings.dex_strings(b"dex\n035\x00short")
    import struct
    struct.pack_into("<I", dex, 0x3C, len(dex))  # string_ids_off beyond EOF
    with pytest.raises(ValueError, match="outside the file"):
        apk_strings.dex_strings(bytes(dex))
    cesu = chr(0xD83D).encode("utf-8", "surrogatepass") + chr(0xDE00).encode("utf-8", "surrogatepass")
    assert apk_strings._mutf8(cesu) == "\U0001F600"  # DEX encodes supplementary chars as surrogate pairs
    assert apk_strings.arsc_strings(make_arsc(["https://x.example.com", "b"])) == ["https://x.example.com", "b"]
    with pytest.raises(ValueError):
        apk_strings.arsc_strings(b"\x01\x00\x0c\x00" + b"\x00" * 40)
    with pytest.raises(ValueError, match="DTD"):
        apk_strings.parse_nsc('<!DOCTYPE x [<!ENTITY a "b">]><network-security-config/>')


def test_custody_and_evidence_e00001_to_e00006(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    apk_sidecar.apk_inventory_native(row["id"])
    endpoints = apk_sidecar.apk_extract_endpoints(row["id"])
    crypto = apk_sidecar.apk_crypto_hints(row["id"])
    assert (endpoints["evidence_id"], crypto["evidence_id"]) == ("E00005", "E00006")
    final = store.load(row["id"])
    assert [e["operation"] for e in final["evidence"]] == [
        "apk_unpack", "apk_manifest", "apk_decompile", "apk_native_libs", "apk_endpoints", "apk_crypto_hints"]
    for i in range(1, 7):
        assert (store.directory(row["id"]) / "evidence" / f"E{i:05d}.json").is_file()
    reported = apk_sidecar.apk_synthesize_report(row["id"])
    cited = {eid for finding in reported["findings"] for eid in finding["evidence_ids"]}
    assert cited >= {"E00001", "E00002", "E00003", "E00004", "E00005", "E00006"}
    assert all(f["kind"] == "observation" and f.get("claim") for f in reported["findings"])
    # The synthetic libtestnative.so is not an ELF, which is a declared unknown -> partial.
    assert reported["status"] == "partial"
    assert reported["unknowns"] == ["lib/arm64-v8a/libtestnative.so is not a parseable ELF (not ELF or truncated); only size and SHA-256 were recorded."]
    assert (store.directory(row["id"]) / "report.json").is_file()
    assert (store.directory(row["id"]) / "report.md").is_file()
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert any(e.get("event") == "apk_report_synthesized" for e in custody.get("events", []))


def test_report_synthesis_cites_e00001_to_e00006(env):
    """RFC-0207 §9.4: synthesis produces findings citing each recorded evidence ID."""
    src, fake = env
    row = _decompiled_fixture(src, fake)
    apk_sidecar.apk_inventory_native(row["id"])
    apk_sidecar.apk_extract_endpoints(row["id"])
    apk_sidecar.apk_crypto_hints(row["id"])
    out = apk_sidecar.call(row["id"], "apk_synthesize_report", {})
    assert out["investigation_status"] == "partial"
    findings = out["findings"]
    cited = {eid for finding in findings for eid in finding["evidence_ids"]}
    assert cited == {"E00001", "E00002", "E00003", "E00004", "E00005", "E00006"}
    sha = store.load(row["id"])["sha256"]
    assert [(f["evidence_ids"], f["claim"]) for f in findings] == [
        (["E00001"], f"Admitted apk package with 1 APK part(s); container SHA-256 {sha} (origin=local_path)."),
        (["E00002"], "Manifest attack surface: package org.anzu.test; version 1.0 (1); 4 exported component(s); "
                     "3 exported without a required permission; 2 high-risk permission(s) requested; "
                     "manifest alerts: debuggable, allow_backup, uses_cleartext_traffic."),
        (["E00003"], "Decompile pipeline: apktool=ok, jadx=ok (4 Java source file(s))."),
        (["E00004"], "Native inventory: 1 native library; ABIs arm64-v8a."),
        (["E00005"], "Extracted 4 static network endpoint(s) (1 custom_scheme, 2 url, 1 websocket)."),
        (["E00005", "E00006"], "Cryptographic hints: 16 alert(s) (2 critical, 8 high, 2 info, 6 warning); notable: "
                               "AWS access key ID (AKIA…MPLE); Embedded private key (PEM block); Hardcoded API key "
                               "or secret assignment (Qw3r…bNm1); Hardcoded API key or secret assignment (Zx8Q…g0Ae); "
                               "Block cipher in ECB mode."),
    ]
    for finding in findings:
        assert finding["kind"] == "observation"
        assert finding["claim"]
        assert finding["evidence_ids"]
        assert "limitations" in finding
    # Secrets must not be pasted into report claims (masked forms from crypto are allowed).
    blob = " ".join(f["claim"] for f in findings)
    assert "AKIAIOSFODNN7EXAMPLE" not in blob
    assert "AIzaSyD-x9SampleKeyForTestingPurpose123" not in blob
    # Refuse double-finalize when status is already reported (no unknowns).
    assert store.load(row["id"])["status"] == "partial"
    # REST surface
    client = TestClient(app)
    # Re-prepare a second investigation for the POST route (first may be reported).
    rest_dir = src / "rest"
    rest_dir.mkdir(exist_ok=True)
    row2 = _decompiled_fixture(rest_dir, fake)
    apk_sidecar.apk_inventory_native(row2["id"])
    apk_sidecar.apk_extract_endpoints(row2["id"])
    apk_sidecar.apk_crypto_hints(row2["id"])
    resp = client.post(f"/api/investigations/{row2['id']}/apk/report")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cited2 = {eid for finding in body["findings"] for eid in finding["evidence_ids"]}
    assert cited2 == {"E00001", "E00002", "E00003", "E00004", "E00005", "E00006"}
    assert body["status"] == "partial"


def test_report_synthesis_partial_when_unknowns(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    # Inject a declared unknown before synthesis (honest partial status).
    stored = store.load(row["id"])
    stored["unknowns"] = ["Synthetic fixture: native symbols unresolved for packed payload."]
    store.save(stored)
    reported = apk_sidecar.apk_synthesize_report(row["id"])
    assert reported["status"] == "partial"
    assert "Synthetic fixture: native symbols unresolved for packed payload." in reported["unknowns"]
    cited = {eid for finding in reported["findings"] for eid in finding["evidence_ids"]}
    assert cited >= {"E00001", "E00002", "E00003"}


def test_report_synthesis_refuses_while_analyzing(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk"))
    claimed = apk_sidecar._claim(row["id"], "decompilation")
    with pytest.raises(ValueError, match="analyzing"):
        apk_sidecar.apk_synthesize_report(row["id"])
    apk_sidecar.release(row["id"], claimed["_claim_token"])


def test_report_synthesis_requires_evidence(env):
    src, _ = env
    # Minimal prepared row without going through prepare() file intake: empty evidence.
    # prepare() always records E00001; clear evidence to force the fail-closed path.
    row = prepare(make_apk(src / "empty_report.apk"))
    stored = store.load(row["id"])
    stored["evidence"] = []
    stored["unknowns"] = []
    store.save(stored)
    with pytest.raises(ValueError, match="No APK evidence"):
        apk_sidecar.apk_synthesize_report(row["id"])


def test_static_steps_never_overlap_decompile(env):
    src, _ = env
    row = prepare(_endpoint_apk(src / "a.apk"))
    step = apk_sidecar._claim(row["id"], "endpoint extraction")  # a static step holding the claim
    with pytest.raises(ValueError, match="analyzing; cannot start decompilation"):
        apk_sidecar.preflight(row["id"])
    with pytest.raises(ValueError, match="analyzing; cannot start endpoint extraction"):
        apk_sidecar.apk_extract_endpoints(row["id"])
    apk_sidecar.release(row["id"], step["_claim_token"])
    claimed = apk_sidecar.preflight(row["id"])
    assert claimed["status"] == "analyzing"
    with pytest.raises(ValueError, match="analyzing; cannot start crypto hints"):
        apk_sidecar.apk_crypto_hints(row["id"])
    apk_sidecar.release(row["id"], claimed["_claim_token"])
    stored = store.load(row["id"])
    stored["status"] = "investigating"
    store.save(stored)
    out = apk_sidecar.apk_crypto_hints(row["id"])
    after = store.load(row["id"])
    assert out["evidence_id"] == after["evidence"][-1]["id"] and row["id"] not in apk_sidecar._CLAIMS
    assert after["status"] == ("partial" if after["unknowns"] else "investigating")


def test_static_step_failure_marks_interrupted_and_frees_claim(env, monkeypatch):
    from app.reverse_engineering import apk_strings
    src, _ = env
    row = prepare(_endpoint_apk(src / "a.apk"))

    def boom(*a, **kw):
        raise OSError("disk went away")
    monkeypatch.setattr(apk_strings, "extract_endpoints", boom)
    with pytest.raises(OSError):
        apk_sidecar.apk_extract_endpoints(row["id"])
    after = store.load(row["id"])
    assert after["status"] == "interrupted" and "disk went away" in after["last_error"]
    assert after["chain_of_custody"][-1]["event"] == "endpoint_extraction_interrupted"
    assert row["id"] not in apk_sidecar._CLAIMS and row["id"] not in apk_sidecar._CANCEL


def test_endpoint_and_crypto_rest_routes(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    client = TestClient(app)
    ident = row["id"]
    assert client.get(f"/api/investigations/{ident}/apk/endpoints").status_code == 404
    assert client.get(f"/api/investigations/{ident}/apk/crypto").status_code == 404
    assert client.get(f"/api/investigations/{ident}/apk/summary").json()["crypto_alerts"] is None
    apk_sidecar.apk_extract_endpoints(ident)
    apk_sidecar.apk_crypto_hints(ident)
    endpoints = client.get(f"/api/investigations/{ident}/apk/endpoints")
    assert endpoints.status_code == 200 and endpoints.json()["counts"]["url"] >= 2
    crypto = client.get(f"/api/investigations/{ident}/apk/crypto")
    assert crypto.status_code == 200 and crypto.json()["network_security_config"]["present"] is True
    summary = client.get(f"/api/investigations/{ident}/apk/summary").json()
    assert summary["urls"] == endpoints.json()["counts"]["url"]
    assert summary["crypto_alerts"] == crypto.json()["alert_count"] > 0
    assert client.get(f"/api/investigations/{ident}/apk/strings").status_code == 422


@pytest.mark.asyncio
async def test_runtime_catalog_exposes_endpoint_and_crypto_operations(env, monkeypatch):
    from types import SimpleNamespace
    from jsonschema import ValidationError
    from app.reverse_engineering.runtime import Investigations
    src, _ = env
    row = prepare(_endpoint_apk(src / "a.apk"))
    service = Investigations()

    async def actor(ident):
        return SimpleNamespace(tools={})
    monkeypatch.setattr(service, "actor", actor)
    monkeypatch.setattr("app.policy.action_gate.gate_side_effect",
                        lambda *a, **k: SimpleNamespace(allowed=True, requires_approval=False, pending_approval_id=None, reason=""))
    catalog = await service.catalog(row["id"], None)
    names = {t["name"] for t in catalog["operations"]}
    assert {"apk_extract_endpoints", "apk_crypto_hints"} <= names
    schema = await service.catalog(row["id"], None, "apk_extract_endpoints")
    assert schema["inputSchema"]["properties"]["category"]["enum"] == list(apk_strings_categories())
    out = await service.call(row["id"], "apk_extract_endpoints", {"category": "websocket", "limit": 1}, None)
    assert out["status"] == "evidence" and out["endpoints"]["returned"] == 1
    assert out["endpoints"]["endpoints"][0]["category"] == "websocket"
    with pytest.raises(ValidationError):
        await service.call(row["id"], "apk_extract_endpoints", {"category": "smtp"}, None)
    crypto = await service.call(row["id"], "apk_crypto_hints", {}, None)
    assert crypto["status"] == "evidence" and crypto["crypto"]["evidence_id"] == crypto["evidence_id"]
    with pytest.raises(ValidationError):
        await service.call(row["id"], "apk_crypto_hints", {"unexpected": True}, None)


def test_real_aapt2_apk_string_scan(env):
    """The aapt2-linked fixture exercises the real resources.arsc pool and binary manifest decoding."""
    src, _ = env
    copy = src / "minimal_valid.apk"
    copy.write_bytes((FIXTURES / "minimal_valid.apk").read_bytes())
    row = prepare(copy)
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    assert out["unknowns"] == []
    assert out["coverage"]["sources"]["resource"] == 1 and out["coverage"]["sources"]["manifest"] == 1
    assert out["filtered"]["xml_namespace"] >= 1  # xmlns:android in the decoded manifest
    assert "ANZU Test" in apk_sidecar.metadata(row["id"], "strings")["strings"]
    crypto = apk_sidecar.apk_crypto_hints(row["id"])
    assert crypto["unknowns"] == [] and crypto["network_security_config"]["present"] is False
    assert crypto["key_storage"]["posture"] == "no_crypto_api_observed"


# --- RFC-0207 slice 3 (review fixes): metadata under the claim, corrupt metadata, soft-fails,
# cancellation, a real d8/aapt2 DEX fixture and a real-tool endpoints/crypto run --------------

from datetime import date as _date

from app.reverse_engineering import apk_strings

DEX_FIXTURE = FIXTURES / "dex_endpoints.apk"


def _dex_fixture(src: Path) -> dict:
    copy = src / "dex_endpoints.apk"
    copy.write_bytes(DEX_FIXTURE.read_bytes())
    return prepare(copy)


def _meta(row: dict) -> Path:
    return store.directory(row["id"]) / "apk" / "metadata"


def test_dex_fixture_is_a_real_d8_aapt2_build():
    with zipfile.ZipFile(DEX_FIXTURE) as z:
        dex = z.read("classes.dex")
        assert z.read("AndroidManifest.xml")[:4] == b"\x03\x00\x08\x00"
        assert z.read("res/xml/network_security_config.xml")[:4] == b"\x03\x00\x08\x00"
        assert "resources.arsc" in z.namelist()
    assert dex[:5] == b"dex\n0" and dex[7] == 0  # d8 --min-api 26 emits DEX 038
    strings = apk_strings.dex_strings(dex)
    assert "Lorg/anzu/fixture/Main;" in strings and "AES/ECB/PKCS5Padding" in strings


def test_endpoints_over_real_dex_fixture(env):
    src, _ = env
    row = _dex_fixture(src)
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    by = {(r["category"], r["endpoint"]): r for r in out["endpoints"]}
    ref = "dex_endpoints.apk!classes.dex"
    assert by[("url", "https://api.fixture.anzu-test.example.com/v1/login")]["references"] == [ref]
    assert by[("websocket", "wss://push.fixture.anzu-test.example.com/socket")]["sources"] == ["dex"]
    assert by[("cloud_service", "anzu-fixture.s3.amazonaws.com")]["provider"]
    assert by[("url", "https://cdn.fixture.anzu-test.example.com/assets")]["sources"] == ["resource"]
    assert out["coverage"]["sources"]["dex"] == 1 and out["coverage"]["dex_strings"] > 20
    assert out["unknowns"] == [] and out["investigation_status"] == "investigating"
    saved = apk_sidecar.metadata(row["id"], "endpoints")
    assert saved["endpoint_count"] == out["endpoint_count"]
    assert "https://api.fixture.anzu-test.example.com/v1/login" in apk_sidecar.metadata(row["id"], "strings")["strings"]


def test_crypto_hints_over_real_dex_fixture(env):
    src, _ = env
    row = _dex_fixture(src)
    out = apk_sidecar.apk_crypto_hints(row["id"])
    rules = {f["rule"]: f for f in out["findings"]}
    assert rules["aws_access_key_id"]["value"] == "AKIAFIXTUREANZU12345"
    assert rules["google_api_key"]["value"] == "AIzaSyFixtureKeyForAnzuTesting012345678"
    assert rules["ecb_mode"]["value"] == "AES/ECB/PKCS5Padding" and rules["ecb_mode"]["confidence"] == "medium"
    assert rules["nsc_user_trust_anchor"]["severity"] == "high"
    assert rules["nsc_cleartext_permitted"]["scope"] == "base-config"
    assert rules["nsc_pin_set_expired"]["expiration"] == "2020-01-01"
    nsc = out["network_security_config"]
    assert nsc["state"] == "present" and nsc["source"] == "dex_endpoints.apk!res/xml/network_security_config.xml"
    assert out["unknowns"] == []


# 1. Metadata is written under the claim lock, after evidence is recorded, with rollback.

def test_endpoint_metadata_not_written_when_claim_lost(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    real = apk_strings.extract_endpoints

    def lose_claim(*a, **kw):
        out = real(*a, **kw)
        apk_sidecar._CLAIMS[row["id"]] = "someone-else"
        return out
    monkeypatch.setattr(apk_strings, "extract_endpoints", lose_claim)
    with pytest.raises(RuntimeError, match="claim was lost"):
        apk_sidecar.apk_extract_endpoints(row["id"])
    apk_sidecar._CLAIMS.pop(row["id"], None)
    assert not (_meta(row) / "endpoints.json").exists() and not (_meta(row) / "strings.json").exists()
    assert not any(e["operation"] == "apk_endpoints" for e in store.load(row["id"])["evidence"])


def test_crypto_metadata_not_written_when_claim_lost(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    real = apk_strings.crypto_hints

    def lose_claim(*a, **kw):
        out = real(*a, **kw)
        apk_sidecar._CLAIMS[row["id"]] = "someone-else"
        return out
    monkeypatch.setattr(apk_strings, "crypto_hints", lose_claim)
    with pytest.raises(RuntimeError, match="claim was lost"):
        apk_sidecar.apk_crypto_hints(row["id"])
    apk_sidecar._CLAIMS.pop(row["id"], None)
    assert not (_meta(row) / "crypto_hints.json").exists()


def test_step_metadata_rolled_back_when_save_fails(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    apk_sidecar.apk_extract_endpoints(row["id"])
    apk_sidecar.apk_crypto_hints(row["id"])
    names = ("endpoints.json", "strings.json", "crypto_hints.json")
    before = {n: (_meta(row) / n).read_bytes() for n in names}
    seen: dict[str, bytes] = {}
    real_save = store.save

    def failing_save(r):
        last = r["evidence"][-1]["operation"] if r["evidence"] else None
        if r["status"] != "analyzing" and last in {"apk_endpoints", "apk_crypto_hints"} and \
                len(r["evidence"]) > len(store.load(r["id"])["evidence"]):
            for n in names:
                seen[n] = (_meta(row) / n).read_bytes()
            raise OSError("disk full")
        return real_save(r)
    monkeypatch.setattr(store, "save", failing_save)
    monkeypatch.setattr(apk_strings, "extract_endpoints", _with_extra_endpoint)
    with pytest.raises(OSError, match="disk full"):
        apk_sidecar.apk_extract_endpoints(row["id"])
    assert seen["endpoints.json"] != before["endpoints.json"]  # the new document was written before the save
    for n in ("endpoints.json", "strings.json"):
        assert (_meta(row) / n).read_bytes() == before[n]
    with pytest.raises(OSError, match="disk full"):
        apk_sidecar.apk_crypto_hints(row["id"])
    assert (_meta(row) / "crypto_hints.json").read_bytes() == before["crypto_hints.json"]


_REAL_EXTRACT = apk_strings.extract_endpoints


def _with_extra_endpoint(*a, **kw):
    out = _REAL_EXTRACT(*a, **kw)
    out["unknowns"] = out["unknowns"] + ["changed run"]
    return out


def test_new_step_metadata_removed_when_first_save_fails(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    real_save = store.save

    def failing_save(r):
        if r["evidence"] and r["evidence"][-1]["operation"] == "apk_endpoints":
            assert (_meta(row) / "endpoints.json").is_file()  # written under the lock before the save
            raise OSError("disk full")
        return real_save(r)
    monkeypatch.setattr(store, "save", failing_save)
    with pytest.raises(OSError):
        apk_sidecar.apk_extract_endpoints(row["id"])
    assert not (_meta(row) / "endpoints.json").exists() and not (_meta(row) / "strings.json").exists()


# 2. Corrupt metadata is never silently treated as missing.

def test_corrupt_components_recorded_as_unknown(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    (_meta(row) / "components.json").write_text("{not json", encoding="utf-8")
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    assert any("components.json is corrupt" in u for u in out["unknowns"])
    assert "Deep links from components.json were not extracted." in out["unknowns"]
    assert not any(r.get("deep_link") for r in out["endpoints"])
    assert out["investigation_status"] == "partial"
    with pytest.raises(ValueError, match="components.json is corrupt"):
        apk_sidecar._optional_metadata(row["id"], "components")
    assert apk_sidecar._optional_metadata(row["id"], "native") is None  # missing is still a plain None


def test_corrupt_manifest_recorded_as_unknown_for_crypto(env):
    src, fake = env
    row = _decompiled_fixture(src, fake)
    (_meta(row) / "manifest.json").write_bytes(b"\xff\xfe garbage")
    out = apk_sidecar.apk_crypto_hints(row["id"])
    assert any("manifest.json is corrupt" in u for u in out["unknowns"])
    assert any("could not be evaluated" in u for u in out["unknowns"])
    assert out["investigation_status"] == "partial"


def test_summary_reports_corrupt_endpoint_metadata(env):
    src, _ = env
    row = _dex_fixture(src)
    apk_sidecar.apk_extract_endpoints(row["id"])
    (_meta(row) / "endpoints.json").write_text("[", encoding="utf-8")
    summary = apk_sidecar.summary(row["id"])
    assert summary["endpoints"] is None and any("endpoints.json is corrupt" in u for u in summary["unknowns"])


# 3. apk_strings soft-fails are reported, not silently resolved.

def _nsc_doc(expiration: str) -> dict:
    return apk_strings.parse_nsc(
        '<network-security-config><domain-config><domain>pin.example.com</domain>'
        f'<pin-set expiration="{expiration}"><pin digest="SHA-256">AAAA</pin></pin-set>'
        '</domain-config></network-security-config>')


def test_bad_pin_set_expiration_is_unknown_not_unexpired():
    unknowns: list[str] = []
    nsc = _nsc_doc("2020-13-45")
    findings = apk_strings._nsc_findings(nsc, "res/xml/nsc.xml", True, False, 34, _date(2026, 1, 1), unknowns)
    assert not any(f["rule"] == "nsc_pin_set_expired" for f in findings)
    assert nsc["domain_configs"][0]["pin_set"]["expired"] is None
    assert unknowns and "2020-13-45" in unknowns[0] and "unknown" in unknowns[0]
    ok: list[str] = []
    nsc = _nsc_doc("2020-01-01")
    findings = apk_strings._nsc_findings(nsc, "r", True, False, 34, _date(2026, 1, 1), ok)
    assert ok == [] and nsc["domain_configs"][0]["pin_set"]["expired"] is True
    assert any(f["rule"] == "nsc_pin_set_expired" for f in findings)


def test_oversized_nsc_reported_unreadable_not_absent(tmp_path, monkeypatch):
    res = tmp_path / "apktool" / "res" / "xml"
    res.mkdir(parents=True)
    (res / "network_security_config.xml").write_text("<network-security-config/>" + " " * 64, encoding="utf-8")
    monkeypatch.setattr(apk_strings, "MAX_TEXT_FILE_BYTES", 16)
    manifest = {"target_sdk": "34", "application": {"network_security_config": "@xml/network_security_config"}}
    doc, findings, unknowns = apk_strings.network_security(tmp_path, [], manifest)
    assert doc["present"] is False and doc["state"] == "unreadable" and doc["unreadable"]
    assert any("Network security config unreadable" in u and "over the 16-byte cap" in u for u in unknowns)
    assert not any("was not found" in u for u in unknowns)
    assert findings == []  # no platform-default findings inferred from a config that exists


def test_unopenable_part_reported_unreadable(tmp_path):
    bad = tmp_path / "base.apk"
    bad.write_bytes(b"not a zip")
    doc, findings, unknowns = apk_strings.network_security(
        tmp_path, [{"name": "base.apk", "path": str(bad), "role": "base"}],
        {"target_sdk": "23", "application": {"network_security_config": "@xml/network_security_config"}})
    assert doc["state"] == "unreadable" and any("could not be opened" in u for u in unknowns)
    assert findings == []


def test_absent_nsc_still_uses_platform_defaults(tmp_path):
    doc, findings, unknowns = apk_strings.network_security(tmp_path, [], {"target_sdk": "23", "application": {}})
    assert doc["state"] == "absent" and unknowns == []
    assert {f["rule"] for f in findings} == {"default_cleartext", "default_user_trust"}


def test_malformed_target_sdk_recorded(tmp_path):
    doc, findings, unknowns = apk_strings.network_security(tmp_path, [], {"target_sdk": "thirty", "application": {}})
    assert doc["target_sdk_malformed"] is True
    assert any("'thirty' is malformed" in u for u in unknowns)
    assert findings == []


# 4. Cancellation of the string scan.

def test_cancel_inside_dex_loop_raises():
    with zipfile.ZipFile(DEX_FIXTURE) as z:
        dex = z.read("classes.dex")
    ev = threading.Event()
    ev.set()
    with pytest.raises(apk_sidecar.DecompileCancelled, match="DEX"):
        apk_strings.dex_strings(dex, ev)


def test_cancel_between_sources_and_inside_java_loop(tmp_path):
    java = tmp_path / "jadx" / "sources" / "a"
    java.mkdir(parents=True)
    for i in range(3):
        (java / f"C{i}.java").write_text('class C { String u = "https://x.example.com"; }', encoding="utf-8")
    ev = threading.Event()
    stats = apk_strings.ScanStats()
    it = apk_strings.iter_sources(tmp_path, [], stats, ev)
    assert next(it).kind == "java"
    ev.set()
    with pytest.raises(apk_sidecar.DecompileCancelled, match="Java"):
        next(it)
    ev2 = threading.Event()
    ev2.set()
    with pytest.raises(apk_sidecar.DecompileCancelled):
        next(apk_strings.iter_sources(tmp_path, [], apk_strings.ScanStats(), ev2))


def test_cancelled_endpoint_scan_records_nothing(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    real = apk_strings.dex_strings

    def cancel_mid_scan(buf, cancel=None):
        apk_sidecar._CANCEL[row["id"]].set()
        return real(buf, cancel)
    monkeypatch.setattr(apk_strings, "dex_strings", cancel_mid_scan)
    with pytest.raises(apk_sidecar.DecompileCancelled):
        apk_sidecar.apk_extract_endpoints(row["id"])
    saved = store.load(row["id"])
    assert saved["status"] == "cancelled"
    assert not (_meta(row) / "endpoints.json").exists()
    assert not any(e["operation"] == "apk_endpoints" for e in saved["evidence"])


def test_cancelled_crypto_scan_records_nothing(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    real = apk_strings.dex_strings

    def cancel_mid_scan(buf, cancel=None):
        apk_sidecar._CANCEL[row["id"]].set()
        return real(buf, cancel)
    monkeypatch.setattr(apk_strings, "dex_strings", cancel_mid_scan)
    with pytest.raises(apk_sidecar.DecompileCancelled):
        apk_sidecar.apk_crypto_hints(row["id"])
    assert store.load(row["id"])["status"] == "cancelled"
    assert not (_meta(row) / "crypto_hints.json").exists()


# 6. Real apktool + jadx on the DEX fixture, then endpoints and crypto over the recovered layers.

@pytest.mark.skipif(not (REAL_JAVA and REAL_APKTOOL and REAL_JADX and Path(REAL_APKTOOL).is_file() and Path(REAL_JADX).is_file()),
                    reason="real toolchain not available; set ANZU_TEST_JAVA, ANZU_TEST_APKTOOL_JAR and ANZU_TEST_JADX")
def test_real_toolchain_endpoints_and_crypto_on_dex_fixture(env, monkeypatch):
    src, _ = env
    row = _dex_fixture(src)
    monkeypatch.setattr(apk_sidecar, "_wsl", _real_host_wsl())
    out = apk_sidecar.decompile(row["id"])
    assert evidence(out, "E00003")["result"]["apktool"]["state"] == "ok"
    assert evidence(out, "E00003")["result"]["jadx"]["state"] == "ok"
    manifest = apk_sidecar.metadata(row["id"], "manifest")
    assert manifest["package"] == "org.anzu.fixture" and manifest["target_sdk"] == "34"
    main_java = "sources/org/anzu/fixture/Main.java"

    ends = apk_sidecar.apk_extract_endpoints(row["id"])
    assert ends["coverage"]["java_sources"] is True and ends["coverage"]["decoded_resources"] is True
    by = {(r["category"], r["endpoint"]): r for r in ends["endpoints"]}
    api = by[("url", "https://api.fixture.anzu-test.example.com/v1/login")]
    assert set(api["sources"]) >= {"dex", "java"} and any(r.startswith(main_java + ":") for r in api["references"])
    assert ("websocket", "wss://push.fixture.anzu-test.example.com/socket") in by
    assert by[("url", "https://cdn.fixture.anzu-test.example.com/assets")]["references"][0].startswith("res/values/strings.xml:")
    deep = by[("custom_scheme", "anzufixture://open")]
    assert deep["deep_link"] is True and deep["component"] == "org.anzu.fixture.Main"

    crypto = apk_sidecar.apk_crypto_hints(row["id"])
    rules: dict[str, list[dict]] = {}
    for f in crypto["findings"]:
        rules.setdefault(f["rule"], []).append(f)
    assert any(any(r.startswith(main_java) for r in f["references"]) for f in rules["google_api_key"])
    assert rules["aws_access_key_id"][0]["value"] == "AKIAFIXTUREANZU12345"
    assert any(f["confidence"] == "high" for f in rules["ecb_mode"])
    assert rules["static_key"][0]["value"] == "0123456789ABCDEF"
    assert rules["weak_hash"][0]["value"] == "MD5"
    nsc = crypto["network_security_config"]
    assert nsc["state"] == "present" and nsc["referenced_by_manifest"] is True
    assert rules["nsc_user_trust_anchor"][0]["severity"] == "high"
    assert rules["nsc_pin_set_expired"][0]["expiration"] == "2020-01-01"


# --- Slice 4: device (ADB) + FFS origins -------------------------------------------------

class FakeADB:
    """Deterministic adb stand-in: pm path lists remotes; pull copies fixture bytes to dest."""

    def __init__(self, mapping: dict[str, bytes]):
        # remote device path -> APK bytes
        self.mapping = dict(mapping)
        self.calls: list[list[str]] = []
        self.pm_path_rc = 0
        self.pm_path_stdout = ""
        self.pull_rc = 0
        self.missing = False
        self.sizes: dict[str, int] = {}  # remote -> size reported by `stat -c %s` (defaults to real length)

    def __call__(self, argv: list[str], timeout: int = 120):
        self.calls.append(list(argv))
        # argv: [adb, (-s serial)?, ...]
        args = list(argv)
        assert args and (args[0].endswith("adb") or args[0].endswith("adb.exe"))
        args = args[1:]
        serial = None
        if args[:1] == ["-s"]:
            serial = args[1]
            args = args[2:]
            assert serial
        if self.missing:
            raise FileNotFoundError("ADB is unavailable")
        if args[:2] == ["shell", "pm"] and args[2:3] == ["path"]:
            out = self.pm_path_stdout
            if not out:
                pkg = args[3]
                # default: emit package: lines for every mapped remote whose key contains pkg hint
                lines = [f"package:{remote}" for remote in self.mapping]
                out = "\n".join(lines) + ("\n" if lines else "")
            return subprocess.CompletedProcess(argv, self.pm_path_rc, out, "")
        if args[:4] == ["shell", "stat", "-c", "%s"]:
            import shlex
            remote = shlex.split(args[4])[0]
            if remote in self.sizes:
                return subprocess.CompletedProcess(argv, 0, f"{self.sizes[remote]}\n", "")
            if remote not in self.mapping:
                return subprocess.CompletedProcess(argv, 1, "", f"stat: {remote}: No such file or directory")
            return subprocess.CompletedProcess(argv, 0, f"{len(self.mapping[remote])}\n", "")
        if args[:1] == ["pull"]:
            remote, dest = args[1], Path(args[2])
            if self.pull_rc != 0:
                return subprocess.CompletedProcess(argv, self.pull_rc, "", "pull failed")
            if remote not in self.mapping:
                return subprocess.CompletedProcess(argv, 1, "", f"remote not found: {remote}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.mapping[remote])
            return subprocess.CompletedProcess(argv, 0, f"{remote}: 1 file pulled\n", "")
        raise AssertionError(f"unexpected adb argv {argv}")


def _install_fake_adb(monkeypatch, fake: FakeADB, tmp_path: Path):
    adb_bin = tmp_path / "fake-adb" / "adb.exe"
    adb_bin.parent.mkdir(parents=True, exist_ok=True)
    adb_bin.write_bytes(b"fake")
    monkeypatch.setattr(apk_sidecar, "_adb_bin", lambda: adb_bin)
    monkeypatch.setattr(apk_sidecar, "_ADB_RUN", fake)


def test_prepare_from_device_pulls_base_and_split(env, monkeypatch):
    src, _ = env
    base = make_apk(src / "base.apk", libs=())
    split = make_apk(src / "split.apk", dex=False, libs=("arm64-v8a/libsplit.so",))
    remotes = {
        "/data/app/~~x/base.apk": base.read_bytes(),
        "/data/app/~~x/split_config.arm64_v8a.apk": split.read_bytes(),
    }
    fake = FakeADB(remotes)
    fake.pm_path_stdout = "\n".join(f"package:{r}" for r in remotes) + "\n"
    _install_fake_adb(monkeypatch, fake, src)
    row = apk_sidecar.prepare_apk(
        None, "Device pull analysis", [], "task-dev",
        source_type="device", device_serial="emulator-5584", package_name="org.anzu.test",
    )
    assert row["source_kind"] == "device_pull"
    assert row["source_uri"] == "device://emulator-5584/org.anzu.test"
    assert row["package_name"] == "org.anzu.test"
    assert row["device_serial"] == "emulator-5584"
    assert row["apk"]["format"] == "split_set"
    assert len(row["apk"]["parts"]) == 2
    assert {p["role"] for p in row["apk"]["parts"]} == {"base", "split"}
    staged = Path(row["apk"]["staged"])
    assert (staged / "base.apk").is_file() and (staged / "split_config.arm64_v8a.apk").is_file()
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["source_kind"] == "device_pull"
    assert custody["package_name"] == "org.anzu.test"
    assert evidence(row, "E00001")["result"]["source_kind"] == "device_pull"
    # adb was invoked with -s serial for pm path and both pulls
    assert any(c[1:3] == ["-s", "emulator-5584"] and "pm" in c for c in fake.calls)


def test_prepare_from_device_fails_closed_when_adb_missing(env, monkeypatch):
    src, _ = env
    fake = FakeADB({})
    fake.missing = True
    _install_fake_adb(monkeypatch, fake, src)
    with pytest.raises(ValueError, match="ADB is unavailable"):
        apk_sidecar.prepare_apk(
            None, "q", [], None, source_type="device", package_name="org.anzu.test",
        )
    assert list(store.root().iterdir()) == [] or all(
        not (p / "investigation.json").exists() for p in store.root().iterdir()
    )


def test_prepare_from_device_no_invented_paths_when_package_missing(env, monkeypatch):
    src, _ = env
    fake = FakeADB({})
    fake.pm_path_stdout = "\n"
    _install_fake_adb(monkeypatch, fake, src)
    with pytest.raises(ValueError, match="not installed|no package"):
        apk_sidecar.prepare_apk(
            None, "q", [], None, source_type="device", package_name="org.missing.app",
        )


def test_prepare_from_device_rejects_bad_package_name(env, monkeypatch):
    src, _ = env
    _install_fake_adb(monkeypatch, FakeADB({}), src)
    with pytest.raises(ValueError, match="Invalid Android package name"):
        apk_sidecar.prepare_apk(
            None, "q", [], None, source_type="device", package_name="../evil",
        )


def _make_ffs_investigation(dump: Path, apk_rel: str, apk_bytes: bytes, *, bad_hash: str | None = None) -> str:
    dump.mkdir(parents=True, exist_ok=True)
    apk_path = dump.joinpath(*apk_rel.replace('\\', '/').split('/'))
    apk_path.parent.mkdir(parents=True, exist_ok=True)
    apk_path.write_bytes(apk_bytes)
    digest = hashlib.sha256(apk_bytes).hexdigest()
    ident = "a" * 32
    # Use a real blank row id from store
    from app.reverse_engineering.privacy import private_directory
    import uuid
    ident = uuid.uuid4().hex
    workspace = store.directory(ident)
    workspace.mkdir(mode=0o700, exist_ok=True)
    private_directory(workspace)
    index_dir = workspace / "index"
    index_dir.mkdir(mode=0o700)
    entry = {
        "path": apk_rel.replace("\\", "/"),
        "bytes": len(apk_bytes),
        "sha256": bad_hash or digest,
        "mtime": 0,
        "magic_hex": apk_bytes[:16].hex(),
        "type": "apk",
    }
    (index_dir / "files.ndjson").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    row = {
        "id": ident, "task_id": "ffs-1", "target": str(dump.resolve()),
        "question": "FFS dump", "kind": "ffs", "status": "completed",
        "evidence": [], "findings": [], "unknowns": [], "chain_of_custody": [],
        "created_at": "2026-10-13T00:00:00+00:00",
    }
    store.save(row)
    return ident


def test_prepare_from_ffs_copies_and_verifies_sha256(env):
    src, _ = env
    dump = src / "ffs_dump"
    apk_rel = "apps/org.anzu.test/base.apk"
    apk_bytes = make_apk(src / "seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, apk_rel, apk_bytes)
    row = apk_sidecar.prepare_apk(
        apk_rel, "FFS APK analysis", [], "task-ffs",
        source_type="ffs", ffs_investigation_id=ffs_id,
    )
    assert row["source_kind"] == "ffs_reference"
    assert row["ffs_investigation_id"] == ffs_id
    assert row["apk"]["format"] == "apk"
    assert row["apk"]["association"] == "ffs index/files.ndjson"
    assert row["sha256"] == hashlib.sha256(apk_bytes).hexdigest()
    assert Path(row["snapshot"]).is_file()
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["source_kind"] == "ffs_reference"
    assert custody["ffs_investigation_id"] == ffs_id
    assert evidence(row, "E00001")["result"]["ffs_investigation_id"] == ffs_id
    # Source dump bytes untouched
    assert (dump / "apps" / "org.anzu.test" / "base.apk").read_bytes() == apk_bytes


def test_prepare_from_ffs_rejects_hash_mismatch(env):
    src, _ = env
    dump = src / "ffs_dump2"
    apk_bytes = make_apk(src / "seed2.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "payload.apk", apk_bytes, bad_hash="0" * 64)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        apk_sidecar.prepare_apk(
            "payload.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id,
        )


def test_prepare_from_ffs_requires_kind_ffs(env):
    src, _ = env
    dump = src / "ffs_dump3"
    apk_bytes = make_apk(src / "seed3.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "payload.apk", apk_bytes)
    row = store.load(ffs_id)
    row["kind"] = "forensic"
    store.save(row)
    with pytest.raises(ValueError, match="kind == 'ffs'"):
        apk_sidecar.prepare_apk(
            "payload.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id,
        )


def test_prepare_from_ffs_rejects_path_escape(env):
    src, _ = env
    dump = src / "ffs_dump4"
    dump.mkdir()
    import uuid
    from app.reverse_engineering.privacy import private_directory
    ident = uuid.uuid4().hex
    workspace = store.directory(ident)
    workspace.mkdir(mode=0o700)
    private_directory(workspace)
    (workspace / "index").mkdir()
    entry = {"path": "../outside.apk", "bytes": 1, "sha256": "a" * 64, "mtime": 0, "magic_hex": "", "type": "apk"}
    (workspace / "index" / "files.ndjson").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    store.save({"id": ident, "target": str(dump.resolve()), "kind": "ffs", "status": "completed",
                "question": "q", "evidence": [], "findings": [], "unknowns": [], "chain_of_custody": [],
                "created_at": "2026-10-13T00:00:00+00:00"})
    with pytest.raises(ValueError, match="Unsafe FFS entry path"):
        apk_sidecar.prepare_apk(
            "../outside.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ident,
        )


def test_apk_api_device_and_ffs_prepare(env, monkeypatch):
    src, _ = env
    client = TestClient(app)
    # device
    base = make_apk(src / "api_base.apk")
    remotes = {"/data/app/base.apk": base.read_bytes()}
    fake = FakeADB(remotes)
    fake.pm_path_stdout = "package:/data/app/base.apk\n"
    _install_fake_adb(monkeypatch, fake, src)
    res = client.post("/api/investigations/apk/prepare", json={
        "source_type": "device", "package_name": "org.anzu.test", "device_serial": "serial-1",
        "question": "API device prepare", "task_id": "t-dev",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_kind"] == "device_pull" and body["status"] == "prepared"
    # ffs
    dump = src / "api_ffs"
    apk_bytes = make_apk(src / "api_ffs_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "app.apk", apk_bytes)
    res2 = client.post("/api/investigations/apk/prepare", json={
        "source_type": "ffs", "target": "app.apk", "ffs_investigation_id": ffs_id,
        "question": "API FFS prepare", "task_id": "t-ffs",
    })
    assert res2.status_code == 200, res2.text
    assert res2.json()["source_kind"] == "ffs_reference"
    # file path still works
    res3 = client.post("/api/investigations/apk/prepare", json={
        "source_type": "file", "target": str(make_apk(src / "still.apk")), "task_id": "t-file",
    })
    assert res3.status_code == 200, res3.text
    assert res3.json()["source_kind"] == "local_path"
    assert res3.json()["status"] == "prepared"


# --- RFC-0207 slice 4 (review fixes): link walk, streamed index caps, pull size caps, end-to-end --

def _pulls(fake: FakeADB) -> list[list[str]]:
    return [c for c in fake.calls if "pull" in c]


def test_ffs_rejects_symlinked_apk_inside_dump(env):
    src, _ = env
    dump = src / "ffs_link"
    apk_bytes = make_apk(src / "link_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "apps/real.apk", apk_bytes)
    (dump / "apps" / "linked.apk").symlink_to(dump / "apps" / "real.apk")
    index = store.directory(ffs_id) / "index" / "files.ndjson"
    index.write_text(json.dumps({"path": "apps/linked.apk", "bytes": len(apk_bytes),
                                 "sha256": hashlib.sha256(apk_bytes).hexdigest()}) + "\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="apps/linked.apk"):
        apk_sidecar.prepare_apk("apps/linked.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id)


def test_ffs_rejects_symlinked_directory_inside_dump(env):
    src, _ = env
    dump = src / "ffs_dirlink"
    outside = src / "outside_apps"
    outside.mkdir()
    apk_bytes = make_apk(outside / "x.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "keep/x.apk", apk_bytes)
    (dump / "apps").symlink_to(outside, target_is_directory=True)
    index = store.directory(ffs_id) / "index" / "files.ndjson"
    index.write_text(json.dumps({"path": "apps/x.apk", "bytes": len(apk_bytes),
                                 "sha256": hashlib.sha256(apk_bytes).hexdigest()}) + "\n", encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        apk_sidecar.prepare_apk("apps/x.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id)


def test_reject_links_walks_without_resolving(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.apk").write_bytes(b"x")
    (tmp_path / "l").symlink_to(tmp_path / "a", target_is_directory=True)
    assert apk_sidecar._reject_links_under(tmp_path, "a/f.apk") == tmp_path / "a" / "f.apk"
    with pytest.raises(PermissionError, match="'l'"):
        apk_sidecar._reject_links_under(tmp_path, "l/f.apk")


def test_ffs_index_streams_and_matches_in_one_pass(env, monkeypatch):
    src, _ = env
    dump = src / "ffs_stream"
    apk_bytes = make_apk(src / "stream_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "apps/target.apk", apk_bytes)
    index = store.directory(ffs_id) / "index" / "files.ndjson"
    target_line = index.read_text(encoding="utf-8")
    filler = "".join(json.dumps({"path": f"data/f{i}.bin", "sha256": "0" * 64}) + "\n" for i in range(2000))
    index.write_text(filler + target_line + "\n", encoding="utf-8")
    exact, by_name = apk_sidecar._scan_ffs_ndjson(index, "apps/target.apk")
    assert [e["path"] for e in exact] == ["apps/target.apk"] and by_name == []
    row = apk_sidecar.prepare_apk("apps/target.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id)
    assert row["sha256"] == hashlib.sha256(apk_bytes).hexdigest()


def test_ffs_index_line_cap_fails_closed(env, monkeypatch):
    src, _ = env
    dump = src / "ffs_line"
    apk_bytes = make_apk(src / "line_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "a.apk", apk_bytes)
    index = store.directory(ffs_id) / "index" / "files.ndjson"
    index.write_text(json.dumps({"path": "x" * 500, "sha256": "0" * 64}) + "\n" + index.read_text(), encoding="utf-8")
    monkeypatch.setattr(apk_sidecar, "MAX_FFS_INDEX_LINE", 256)
    with pytest.raises(ValueError, match="line 1 exceeds"):
        apk_sidecar.prepare_apk("a.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id)


def test_ffs_index_size_cap_fails_closed(env, monkeypatch):
    src, _ = env
    dump = src / "ffs_size"
    apk_bytes = make_apk(src / "size_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "a.apk", apk_bytes)
    monkeypatch.setattr(apk_sidecar, "MAX_FFS_INDEX_BYTES", 16)
    with pytest.raises(ValueError, match="over the 16-byte cap"):
        apk_sidecar.prepare_apk("a.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id)


def test_ffs_index_corrupt_line_fails_closed(env):
    src, _ = env
    dump = src / "ffs_corrupt"
    apk_bytes = make_apk(src / "corrupt_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "a.apk", apk_bytes)
    index = store.directory(ffs_id) / "index" / "files.ndjson"
    index.write_text(index.read_text() + "{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt FFS NDJSON at line 2"):
        apk_sidecar.prepare_apk("a.apk", "q", [], None, source_type="ffs", ffs_investigation_id=ffs_id)


def test_device_pull_refuses_part_over_per_file_cap(env, monkeypatch):
    src, _ = env
    base = make_apk(src / "cap_base.apk")
    fake = FakeADB({"/data/app/base.apk": base.read_bytes()})
    fake.pm_path_stdout = "package:/data/app/base.apk\n"
    fake.sizes["/data/app/base.apk"] = apk_sidecar.MAX_DEVICE_APK_BYTES + 1
    _install_fake_adb(monkeypatch, fake, src)
    with pytest.raises(ValueError, match="per-file cap"):
        apk_sidecar.prepare_apk(None, "q", [], None, source_type="device", package_name="org.anzu.test")
    assert _pulls(fake) == []  # refused before any bytes left the device
    assert any(c[-4:-1] == ["stat", "-c", "%s"] for c in fake.calls)


def test_device_pull_enforces_cumulative_cap(env, monkeypatch):
    src, _ = env
    base = make_apk(src / "cum_base.apk")
    split = make_apk(src / "cum_split.apk", dex=False)
    remotes = {"/data/app/base.apk": base.read_bytes(), "/data/app/split_a.apk": split.read_bytes()}
    fake = FakeADB(remotes)
    fake.pm_path_stdout = "".join(f"package:{r}\n" for r in remotes)
    _install_fake_adb(monkeypatch, fake, src)
    monkeypatch.setattr(apk_sidecar, "MAX_BYTES", len(remotes["/data/app/base.apk"]) + 1)
    with pytest.raises(ValueError, match="total cap"):
        apk_sidecar.prepare_apk(None, "q", [], None, source_type="device", package_name="org.anzu.test")
    assert [c[c.index("pull") + 1] for c in _pulls(fake)] == ["/data/app/base.apk"]


def test_device_pull_fails_closed_when_size_unreadable(env, monkeypatch):
    src, _ = env
    fake = FakeADB({})
    fake.pm_path_stdout = "package:/data/app/gone.apk\n"
    _install_fake_adb(monkeypatch, fake, src)
    with pytest.raises(ValueError, match="Could not read the size"):
        apk_sidecar.prepare_apk(None, "q", [], None, source_type="device", package_name="org.anzu.test")
    assert _pulls(fake) == []


def test_device_pull_rejects_size_mismatch(env, monkeypatch):
    src, _ = env
    base = make_apk(src / "mm_base.apk")
    fake = FakeADB({"/data/app/base.apk": base.read_bytes()})
    fake.pm_path_stdout = "package:/data/app/base.apk\n"
    fake.sizes["/data/app/base.apk"] = 10
    _install_fake_adb(monkeypatch, fake, src)
    with pytest.raises(ValueError, match="device reported 10"):
        apk_sidecar.prepare_apk(None, "q", [], None, source_type="device", package_name="org.anzu.test")


def _decompile_uses_staged(row: dict, fake) -> dict:
    claimed = apk_sidecar.preflight(row["id"])
    out = apk_sidecar.decompile(row["id"], claimed=claimed)
    staged = Path(row["apk"]["staged"]).resolve()
    tool_inputs = [a for argv, _ in fake.calls if argv and argv[0] == "timeout" for a in argv]
    assert any(str(staged) in a or staged.as_posix() in a for a in tool_inputs), "decompile did not read apk/staged"
    for part in out["apk"]["parts"]:
        assert Path(part["path"]).resolve().is_relative_to(staged)
    assert evidence(out, "E00003")["result"]["apktool"]["state"] == "ok"
    assert out["status"] == "investigating"
    return out


def test_device_origin_end_to_end_decompile(env, monkeypatch):
    src, fake_wsl = env
    base = make_apk(src / "e2e_base.apk")
    split = make_apk(src / "e2e_split.apk", dex=False, libs=("arm64-v8a/libsplit.so",))
    remotes = {"/data/app/~~e/base.apk": base.read_bytes(),
               "/data/app/~~e/split_config.arm64_v8a.apk": split.read_bytes()}
    fake = FakeADB(remotes)
    fake.pm_path_stdout = "".join(f"package:{r}\n" for r in remotes)
    _install_fake_adb(monkeypatch, fake, src)
    row = apk_sidecar.prepare_apk(None, "Device e2e", [], "t", source_type="device", package_name="org.anzu.test")
    assert row["source_kind"] == "device_pull"
    out = _decompile_uses_staged(row, fake_wsl)
    assert evidence(out, "E00002")["operation"] == "apk_manifest"


def test_ffs_origin_end_to_end_decompile(env):
    src, fake_wsl = env
    dump = src / "ffs_e2e"
    apk_bytes = make_apk(src / "ffs_e2e_seed.apk").read_bytes()
    ffs_id = _make_ffs_investigation(dump, "apps/org.anzu.test/base.apk", apk_bytes)
    row = apk_sidecar.prepare_apk("apps/org.anzu.test/base.apk", "FFS e2e", [], "t",
                                  source_type="ffs", ffs_investigation_id=ffs_id)
    assert row["source_kind"] == "ffs_reference"
    out = _decompile_uses_staged(row, fake_wsl)
    assert (dump / "apps" / "org.anzu.test" / "base.apk").read_bytes() == apk_bytes  # dump untouched


# --- RFC-0207 slice 5: smali fallback when jadx fails ------------------------------------


def _apktool_calls(fake):
    return [argv for argv, _ in fake.calls if argv and argv[0] == "timeout" and apk_sidecar.APKTOOL_JAR in argv]


def test_smali_fallback_on_jadx_timeout(env):
    src, fake = env
    row = prepare(make_apk(src / "a.apk"))
    fake.jadx_mode = "timeout"
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert any("timed out after 600 s" in u for u in out["unknowns"])
    calls = _apktool_calls(fake)
    assert len(calls) == 2
    assert "--no-src" in calls[0] and "--no-res" not in calls[0]
    assert "--no-src" not in calls[1] and "--no-res" in calls[1]
    smali_meta = apk_sidecar.metadata(row["id"], "smali")
    assert smali_meta["ran"] is True and smali_meta["reason"] == "jadx_timeout"
    assert smali_meta["state"] == "ok" and smali_meta["smali_files"] == 1
    dec = evidence(out, "E00003")["result"]
    assert dec["smali_fallback"]["state"] == "ok"
    assert dec["smali_fallback"]["smali_files"] == 1
    part_dir = apk_sidecar._part_dir_name(row["apk"]["base"]["name"])
    assert (store.directory(row["id"]) / "apk" / "smali" / part_dir / "smali" / "org" / "anzu" / "test" / "MainActivity.smali").is_file()
    assert smali_meta["smali_classes"] == 1 and smali_meta["parts"][0]["part"] == row["apk"]["base"]["name"]
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody.get("smali_fallback_at")
    assert any(e["event"] == "smali_fallback_completed" for e in custody["events"])
    summary = apk_sidecar.summary(row["id"])
    assert summary["smali_fallback"]["ran"] is True and summary["smali_fallback"]["smali_files"] == 1
    # Manifest/resources from Phase A remain valid despite jadx timeout.
    assert apk_sidecar.metadata(row["id"], "manifest")["package"] == "org.anzu.test"


def test_smali_fallback_on_jadx_oom_and_fail(env):
    src, fake = env
    row = prepare(make_apk(src / "oom.apk"))
    fake.jadx_mode = "oom"
    out = apk_sidecar.decompile(row["id"])
    assert any("4 GiB heap" in u for u in out["unknowns"])
    assert apk_sidecar.metadata(row["id"], "smali")["reason"] == "jadx_out_of_memory"
    assert evidence(out, "E00003")["result"]["smali_fallback"]["smali_files"] == 1

    row2 = prepare(make_apk(src / "fail.apk"))
    fake.jadx_mode = "fail"
    fake.calls.clear()
    out2 = apk_sidecar.decompile(row2["id"])
    assert any("exited 1" in u for u in out2["unknowns"])
    smali = apk_sidecar.metadata(row2["id"], "smali")
    assert smali["reason"] == "jadx_failed" and smali["smali_files"] == 1
    assert evidence(out2, "E00003")["result"]["jadx"]["failed_classes"] == ["org.anzu.test.Broken"]


def test_smali_fallback_on_no_useful_java(env):
    src, fake = env
    row = prepare(make_apk(src / "empty.apk"))
    fake.jadx_mode = "empty"
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert "jadx produced no Java; smali recovered." in out["unknowns"]
    assert evidence(out, "E00003")["result"]["jadx"]["state"] == "ok"
    smali = apk_sidecar.metadata(row["id"], "smali")
    assert smali["ran"] is True and smali["reason"] == "no_useful_java" and smali["smali_files"] == 1
    assert evidence(out, "E00003")["result"]["jadx"]["java_files"] == 0


def test_smali_fallback_skipped_when_jadx_ok(env):
    src, fake = env
    row = prepare(make_apk(src / "ok.apk"))
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "investigating" and out["unknowns"] == []
    assert len(_apktool_calls(fake)) == 1 and "--no-src" in _apktool_calls(fake)[0]
    smali = apk_sidecar.metadata(row["id"], "smali")
    assert smali["ran"] is False and smali["reason"] == "jadx_ok" and smali["state"] == "skipped"
    assert evidence(out, "E00003")["result"]["smali_fallback"] is None
    assert apk_sidecar.summary(row["id"])["smali_fallback"]["ran"] is False


def test_smali_fallback_on_skip_jadx_and_disabled(env):
    src, fake = env
    row = prepare(make_apk(src / "skip.apk"))
    out = apk_sidecar.decompile(row["id"], skip_jadx=True)
    assert out["status"] == "investigating"
    assert len(_apktool_calls(fake)) == 2
    assert apk_sidecar.metadata(row["id"], "smali")["reason"] == "jadx_skipped"
    assert evidence(out, "E00003")["result"]["smali_fallback"]["smali_files"] == 1

    row2 = prepare(make_apk(src / "off.apk"))
    fake.calls.clear()
    fake.jadx_mode = "timeout"
    out2 = apk_sidecar.decompile(row2["id"], decompile_smali_fallback=False)
    assert any("timed out" in u for u in out2["unknowns"])
    assert len(_apktool_calls(fake)) == 1
    smali = apk_sidecar.metadata(row2["id"], "smali")
    assert smali["ran"] is False and smali["reason"] == "disabled"
    assert evidence(out2, "E00003")["result"]["smali_fallback"] is None


def test_smali_fallback_not_run_without_dex(env):
    src, fake = env
    row = prepare(make_apk(src / "nodex.apk", dex=False))
    out = apk_sidecar.decompile(row["id"])
    assert evidence(out, "E00003")["result"]["jadx"]["state"] == "skipped"
    assert len(_apktool_calls(fake)) == 1
    assert apk_sidecar.metadata(row["id"], "smali")["reason"] == "no_dex"


def test_smali_fallback_failure_recorded(env):
    src, fake = env
    row = prepare(make_apk(src / "both.apk"))
    fake.apktool_mode = "fail"
    fake.jadx_mode = "oom"
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert any("smali fallback" in u and "unavailable" in u for u in out["unknowns"])
    smali = apk_sidecar.metadata(row["id"], "smali")
    assert smali["ran"] is True and smali["state"] == "failed"


def test_smali_fallback_api_and_catalog(env):
    src, fake = env
    client = TestClient(app)
    res = client.post("/api/investigations/apk/prepare", json={
        "source_type": "file", "target": str(make_apk(src / "api_s5.apk")), "task_id": "t-s5"})
    assert res.status_code == 200, res.text
    ident = res.json()["id"]
    fake.jadx_mode = "timeout"
    dec = client.post(f"/api/investigations/{ident}/apk/decompile",
                      json={"decompile_smali_fallback": True})
    assert dec.status_code == 200, dec.text
    assert dec.json()["status"] == "partial"
    summary = client.get(f"/api/investigations/{ident}/apk/summary").json()
    assert summary["smali_fallback"]["ran"] is True and summary["smali_fallback"]["smali_files"] == 1
    assert "decompile_smali_fallback" in apk_sidecar.CATALOG["apk_decompile"]["inputSchema"]["properties"]


# --- RFC-0207 slice 5 (review fixes): per-part smali, descriptor parsing, class counts --------

def test_smali_fallback_runs_for_every_dex_part_of_a_split_set(env):
    src, fake = env
    split_dir = src / "split_set"
    split_dir.mkdir()
    make_apk(split_dir / "base.apk")
    make_apk(split_dir / "split_feature.apk", libs=())               # carries its own classes.dex
    make_apk(split_dir / "split_config.arm64_v8a.apk", dex=False)    # native only, no bytecode
    row = prepare(split_dir)
    assert len(row["apk"]["parts"]) == 3
    fake.jadx_mode = "timeout"
    out = apk_sidecar.decompile(row["id"])
    smali_calls = [c for c in _apktool_calls(fake) if "--no-res" in c]
    assert len(smali_calls) == 2  # one apktool pass per DEX-bearing part
    smali = apk_sidecar.metadata(row["id"], "smali")
    by_part = {p["part"]: p for p in smali["parts"]}
    dex_parts = [p["name"] for p in row["apk"]["parts"] if p["dex"]]
    assert set(dex_parts) == {n for n, p in by_part.items() if p["state"] == "ok"}
    no_dex = [n for n, p in by_part.items() if p["state"] == "skipped"]
    assert len(no_dex) == 1 and by_part[no_dex[0]]["reason"] == "no_dex"
    root = store.directory(row["id"]) / "apk" / "smali"
    for name in dex_parts:
        assert (root / apk_sidecar._part_dir_name(name) / "smali" / "org" / "anzu" / "test" / "MainActivity.smali").is_file()
    assert smali["smali_files"] == 2 and smali["smali_classes"] == 2
    assert out["status"] == "partial"


def test_smali_fallback_part_failure_is_an_unknown_per_part(env, monkeypatch):
    src, fake = env
    split_dir = src / "split_fail"
    split_dir.mkdir()
    make_apk(split_dir / "base.apk")
    make_apk(split_dir / "split_feature.apk", libs=())
    row = prepare(split_dir)
    fake.jadx_mode = "timeout"
    real = apk_sidecar._run_smali_fallback

    def flaky(ident, apk, out):
        result = real(ident, apk, out)
        if apk.name == "split_feature.apk":
            result.update(state="failed", exit_code=1, smali_files=0, smali_classes=0, smali_roots=[])
        return result
    monkeypatch.setattr(apk_sidecar, "_run_smali_fallback", flaky)
    out = apk_sidecar.decompile(row["id"])
    assert any("smali fallback failed for split_feature.apk" in u for u in out["unknowns"])
    smali = apk_sidecar.metadata(row["id"], "smali")
    assert smali["state"] == "failed" and smali["smali_files"] == 1


def test_jadx_failed_class_names_keep_leading_L():
    diag = ("ERROR - Failed to process class LoginActivity\n"
            "ERROR - Failed to decompile class Lcom/anzu/LegacyLoader;\n"
            "ERROR - Can't load class com.anzu.LocalStore\n")
    assert apk_sidecar._jadx_failed_classes(diag) == ["LoginActivity", "com.anzu.LegacyLoader", "com.anzu.LocalStore"]


def test_smali_classes_counts_class_directives(tmp_path):
    (tmp_path / "smali" / "a").mkdir(parents=True)
    (tmp_path / "smali" / "a" / "One.smali").write_text(".class public La/One;\n.super Ljava/lang/Object;\n")
    (tmp_path / "smali" / "a" / "Empty.smali").write_text("# no class directive\n")
    counts = apk_sidecar._count_smali(tmp_path)
    assert counts == {"smali_files": 2, "smali_classes": 1, "smali_roots": ["smali"], "unreadable": []}


def test_part_dir_name_is_a_single_safe_component():
    assert apk_sidecar._part_dir_name("split_config.arm64_v8a.apk") == "split_config.arm64_v8a.apk"
    assert "/" not in apk_sidecar._part_dir_name("../evil/x.apk")
    assert apk_sidecar._part_dir_name("..") == "_part"


# --- RFC-0207 slice 5 (review fixes 2): unreadable smali, no-Java wording, dedupe ----------------

def test_unreadable_smali_file_is_an_unknown(env, monkeypatch):
    src, fake = env
    row = prepare(make_apk(src / "unreadable.apk"))
    fake.jadx_mode = "timeout"
    real_read = Path.read_bytes

    def read_bytes(self):
        if self.suffix == ".smali":
            raise PermissionError(13, "Permission denied")
        return real_read(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    out = apk_sidecar.decompile(row["id"])
    bad = [u for u in out["unknowns"] if u.startswith("smali file ")]
    assert len(bad) == 1 and "smali/org/anzu/test/MainActivity.smali (Permission denied)" in bad[0]
    smali = apk_sidecar.metadata(row["id"], "smali")
    assert smali["smali_files"] == 1 and smali["smali_classes"] == 0


def test_no_java_with_smali_disabled_reports_no_disassembly(env):
    src, fake = env
    row = prepare(make_apk(src / "nojava_disabled.apk"))
    fake.jadx_mode = "empty"
    out = apk_sidecar.decompile(row["id"], decompile_smali_fallback=False)
    assert out["status"] == "partial"
    assert "jadx produced no Java; no bytecode disassembly available." in out["unknowns"]
    assert not any("smali recovered" in u for u in out["unknowns"])


def test_no_java_with_every_smali_pass_failed_reports_no_disassembly(env, monkeypatch):
    src, fake = env
    split_dir = src / "nojava_failed"
    split_dir.mkdir()
    make_apk(split_dir / "base.apk")
    make_apk(split_dir / "split_feature.apk", libs=())
    row = prepare(split_dir)
    fake.jadx_mode = "empty"
    real = apk_sidecar._run_smali_fallback

    def failing(ident, apk, out_dir):
        result = real(ident, apk, out_dir)
        result.update(state="failed", exit_code=1, smali_files=0, smali_classes=0, smali_roots=[], unreadable=[])
        return result
    monkeypatch.setattr(apk_sidecar, "_run_smali_fallback", failing)
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert "jadx produced no Java; no bytecode disassembly available." in out["unknowns"]
    assert sum(1 for u in out["unknowns"] if u.startswith("smali fallback failed for")) == 2
    assert apk_sidecar.metadata(row["id"], "smali")["smali_files"] == 0


def test_colliding_part_names_get_distinct_smali_dirs(env):
    src, fake = env
    split_dir = src / "collide"
    split_dir.mkdir()
    make_apk(split_dir / "base.apk")
    make_apk(split_dir / "split a.apk", libs=())
    make_apk(split_dir / "split_a.apk", libs=())  # "split a.apk" sanitises to the same name
    row = prepare(split_dir)
    names = [p["name"] for p in row["apk"]["parts"] if p["dex"]]
    assert len({apk_sidecar._part_dir_name(n) for n in names}) == 2  # one collision among three parts
    fake.jadx_mode = "timeout"
    apk_sidecar.decompile(row["id"])
    smali = apk_sidecar.metadata(row["id"], "smali")
    outs = [p["smali_output"] for p in smali["parts"]]
    assert len(outs) == 3 and len(set(outs)) == 3
    for o in outs:
        assert (Path(o) / "smali" / "org" / "anzu" / "test" / "MainActivity.smali").is_file()
    assert smali["smali_files"] == 3


# --- RFC-0207 slice 6 (review fixes): cloud hints, latest evidence, native hardening claim ------

def test_report_claims_cloud_services_from_real_dex_fixture(env):
    src, _ = env
    row = _dex_fixture(src)
    apk_sidecar.apk_extract_endpoints(row["id"])
    apk_sidecar.apk_crypto_hints(row["id"])
    out = apk_sidecar.apk_synthesize_report(row["id"])
    assert out["status"] == "reported" and out["unknowns"] == []
    claims = {tuple(f["evidence_ids"]): f["claim"] for f in out["findings"]}
    assert claims[("E00002",)] == ("Extracted 5 static network endpoint(s) (1 cloud_service, 3 url, 1 websocket); "
                                   "cloud service hint(s): aws anzu-fixture.s3.amazonaws.com.")
    assert claims[("E00002", "E00003")] == (
        "Cryptographic hints: 7 alert(s) (1 critical, 2 high, 1 info, 4 warning); notable: "
        "AWS access key ID (AKIA…2345); Block cipher in ECB mode; User-installed CAs trusted.")
    with pytest.raises(ValueError, match="reported"):
        apk_sidecar.apk_synthesize_report(row["id"])  # a reported investigation is final


def test_report_native_hardening_claim_from_real_ndk_library(env):
    src, _ = env
    apk = _apk_with_libs(src / "hardening.apk",
                         {"lib/armeabi-v7a/libtestnative.so": (FIXTURES / "libtestnative_armv7.so").read_bytes()})
    row = prepare(apk)
    apk_sidecar.apk_inventory_native(row["id"])
    out = apk_sidecar.apk_synthesize_report(row["id"])
    assert out["status"] == "reported"
    native = [f for f in out["findings"] if f["evidence_ids"] == ["E00002"]]
    assert [f["claim"] for f in native] == [
        "Native inventory: 1 native library; ABIs armeabi-v7a; 1 with partial/none RELRO; 1 without stack canary."]


def test_report_cites_latest_successful_rerun(env):
    src, _ = env
    row = _dex_fixture(src)
    first = apk_sidecar.apk_extract_endpoints(row["id"])
    second = apk_sidecar.apk_extract_endpoints(row["id"])
    assert (first["evidence_id"], second["evidence_id"]) == ("E00002", "E00003")
    assert apk_sidecar._evidence_id_by_operation(store.load(row["id"]))["apk_endpoints"] == "E00003"
    out = apk_sidecar.apk_synthesize_report(row["id"])
    cited = [f["evidence_ids"] for f in out["findings"] if f["claim"].startswith("Extracted ")]
    assert cited == [["E00003"]]


def test_report_ignores_failed_later_record(env):
    row = {"evidence": [{"id": "E00001", "operation": "apk_endpoints", "success": True},
                        {"id": "E00002", "operation": "apk_endpoints", "success": False}]}
    assert apk_sidecar._evidence_id_by_operation(row) == {"apk_endpoints": "E00001"}


# --- RFC-0207 slice 7: endpoint + crypto scanning of recovered smali --------------------

SMALI_NET = """\
.class public Lorg/anzu/test/net/Client;
.super Ljava/lang/Object;

.method public endpoint()Ljava/lang/String;
    .locals 1
    const-string v0, "https://smali-api.anzu-test.example.com/v1/users"
    return-object v0
.end method

.method public push()Ljava/lang/String;
    .locals 1
    const-string/jumbo v0, "wss://smali-push.anzu-test.example.com/socket"
    return-object v0
.end method

.method public deep()Ljava/lang/String;
    .locals 1
    const-string v0, "anzu-smali://open/item"
    return-object v0
.end method
"""

SMALI_VAULT = """\
.class public Lorg/anzu/test/crypto/Vault;
.super Ljava/lang/Object;

.method public enc([B)[B
    .locals 4
    const-string v0, "AES/ECB/PKCS5Padding"
    invoke-static {v0}, Ljavax/crypto/Cipher;->getInstance(Ljava/lang/String;)Ljavax/crypto/Cipher;
    move-result-object v1
    const-string v2, "0123456789ABCDEF"
    invoke-virtual {v2}, Ljava/lang/String;->getBytes()[B
    move-result-object v2
    new-instance v3, Ljavax/crypto/spec/SecretKeySpec;
    invoke-direct {v3, v2, v0}, Ljavax/crypto/spec/SecretKeySpec;-><init>([BLjava/lang/String;)V
    const/16 v0, 0x10
    new-array v0, v0, [B
    new-instance v2, Ljavax/crypto/spec/IvParameterSpec;
    invoke-direct {v2, v0}, Ljavax/crypto/spec/IvParameterSpec;-><init>([B)V
    return-object v1
.end method

.method public key()V
    .locals 1
    const-string v0, "AIzaSyD-x9SampleKeyForSmaliPurpose12345"
    return-void
.end method
"""

SMALI_HASH = """\
.class public Lorg/anzu/test/crypto/Hashes;
.super Ljava/lang/Object;

.method public hashPassword(Ljava/lang/String;)Ljava/lang/String;
    .locals 2
    const-string v0, "MD5"
    invoke-static {v0}, Ljava/security/MessageDigest;->getInstance(Ljava/lang/String;)Ljava/security/MessageDigest;
    move-result-object v1
    return-object v0
.end method
"""

SMALI_CACHE = """\
.class public Lorg/anzu/test/crypto/Cache;
.super Ljava/lang/Object;

.method public cacheKey([B)Ljava/lang/String;
    .locals 1
    const-string v0, "SHA-1"
    invoke-static {v0}, Ljava/security/MessageDigest;->getInstance(Ljava/lang/String;)Ljava/security/MessageDigest;
    return-object v0
.end method
"""

SMALI_KEYSTORE = """\
.class public Lorg/anzu/test/crypto/Keys;
.super Ljava/lang/Object;

.method public load()V
    .locals 1
    const-string v0, "AndroidKeyStore"
    invoke-static {v0}, Ljava/security/KeyStore;->getInstance(Ljava/lang/String;)Ljava/security/KeyStore;
    return-void
.end method
"""


def _plant_smali(ident: str, files: dict[str, str], *, ran: bool = True, reason: str = "jadx_timeout") -> Path:
    """Write recovered smali + matching smali.json under an investigation (no real apktool)."""
    root = store.directory(ident) / "apk"
    smali_root = root / "smali" / "a.apk"
    for rel, body in files.items():
        path = smali_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    meta = root / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    store.atomic_json(meta / "smali.json", {
        "ran": ran, "reason": reason, "state": "ok" if ran else "skipped",
        "smali_files": len(files) if ran else 0, "smali_classes": len(files) if ran else 0,
        "smali_roots": ["smali"], "smali_output": str(root / "smali"),
        "parts": [{"part": "a.apk", "state": "ok", "smali_files": len(files), "smali_classes": len(files)}],
    })
    return smali_root


def test_smali_endpoint_extraction(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk", dex=True, libs=()))
    _plant_smali(row["id"], {
        "smali/org/anzu/test/net/Client.smali": SMALI_NET,
    })
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    by = {(r["category"], r["endpoint"]): r for r in out["endpoints"]}
    api = by[("url", "https://smali-api.anzu-test.example.com/v1/users")]
    assert api["sources"] == ["smali"]
    assert api["references"] == ["smali/a.apk/smali/org/anzu/test/net/Client.smali:6"]
    assert ("websocket", "wss://smali-push.anzu-test.example.com/socket") in by
    assert ("custom_scheme", "anzu-smali://open/item") in by
    assert out["coverage"]["smali_sources"] is True
    assert out["coverage"]["sources"]["smali"] == 1
    assert any("recovered smali" in x for x in out["limitations"])
    assert not any("smali" in u.lower() for u in out["unknowns"])
    assert out["investigation_status"] == "partial"


def test_smali_crypto_call_sites(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk", dex=True, libs=()))
    _plant_smali(row["id"], {
        "smali/org/anzu/test/crypto/Vault.smali": SMALI_VAULT,
        "smali/org/anzu/test/crypto/Hashes.smali": SMALI_HASH,
        "smali/org/anzu/test/crypto/Cache.smali": SMALI_CACHE,
        "smali/org/anzu/test/crypto/Keys.smali": SMALI_KEYSTORE,
    })
    out = apk_sidecar.apk_crypto_hints(row["id"])
    rules: dict[str, list[dict]] = {}
    for f in out["findings"]:
        rules.setdefault(f["rule"], []).append(f)
    google = rules["google_api_key"][0]
    assert google["value"] == "AIzaSyD-x9SampleKeyForSmaliPurpose12345"
    assert google["sources"] == ["smali"]
    assert "smali/a.apk/smali/org/anzu/test/crypto/Vault.smali:" in google["references"][0]
    ecb = {f["value"]: f for f in rules["ecb_mode"]}
    assert "AES/ECB/PKCS5Padding" in ecb and ecb["AES/ECB/PKCS5Padding"]["confidence"] == "high"
    assert ecb["AES/ECB/PKCS5Padding"]["sources"] == ["smali"]
    assert rules["static_key"][0]["value"] == "0123456789ABCDEF"
    assert rules["static_key"][0]["sources"] == ["smali"]
    assert rules["static_iv"][0]["detail"].startswith("IV is a zero-filled byte[16]")
    hashes = {f["value"]: f for f in rules["weak_hash"]}
    assert hashes["MD5"]["severity"] == "warning" and hashes["MD5"]["context"] == "password_or_signature"
    assert hashes["SHA-1"]["severity"] == "info" and hashes["SHA-1"]["context"] == "general"
    assert out["key_storage"]["posture"] == "android_keystore"
    assert out["coverage"]["smali_sources"] is True
    assert any("evaluated on recovered smali" in x for x in out["limitations"])
    assert not any("smali" in u.lower() for u in out["unknowns"])


def test_smali_missing_tree_is_unknown(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk", dex=True, libs=()))
    meta = store.directory(row["id"]) / "apk" / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    store.atomic_json(meta / "smali.json", {
        "ran": True, "reason": "jadx_timeout", "state": "ok",
        "smali_files": 3, "smali_classes": 3, "smali_roots": ["smali"],
        "smali_output": str(store.directory(row["id"]) / "apk" / "smali"),
    })
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    assert any("apk/smali/ is missing" in u for u in out["unknowns"])
    assert out["coverage"]["smali_sources"] is False
    crypto = apk_sidecar.apk_crypto_hints(row["id"])
    assert any("apk/smali/ is missing" in u for u in crypto["unknowns"])


def test_smali_partial_count_mismatch_is_unknown(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk", dex=True, libs=()))
    _plant_smali(row["id"], {"smali/org/anzu/test/One.smali": SMALI_NET})
    # Claim more files than were planted.
    meta = store.directory(row["id"]) / "apk" / "metadata" / "smali.json"
    doc = json.loads(meta.read_text(encoding="utf-8"))
    doc["smali_files"] = 5
    store.atomic_json(meta, doc)
    out = apk_sidecar.apk_crypto_hints(row["id"])
    assert any("only 1 were found" in u for u in out["unknowns"])
    assert out["coverage"]["smali_sources"] is True  # the one present file was still scanned


def test_smali_incomplete_marker_is_unknown(env):
    src, _ = env
    row = prepare(make_apk(src / "a.apk", dex=True, libs=()))
    root = _plant_smali(row["id"], {"smali/org/anzu/test/net/Client.smali": SMALI_NET})
    (root / ".incomplete").write_text("apktool-smali failed\n", encoding="utf-8")
    out = apk_sidecar.apk_extract_endpoints(row["id"])
    assert any("marked incomplete" in u for u in out["unknowns"])
    by = {(r["category"], r["endpoint"]) for r in out["endpoints"]}
    assert ("url", "https://smali-api.anzu-test.example.com/v1/users") in by


def test_smali_scan_after_fake_fallback_decompile(env):
    """End-to-end: FakeWSL smali fallback → endpoints + crypto see smali sources."""
    src, fake = env
    fake.jadx_mode = "timeout"
    fake.smali_files = {
        "smali/org/anzu/test/net/Client.smali": SMALI_NET,
        "smali/org/anzu/test/crypto/Vault.smali": SMALI_VAULT,
        "smali/org/anzu/test/crypto/Hashes.smali": SMALI_HASH,
        "smali/org/anzu/test/crypto/Cache.smali": SMALI_CACHE,
        "smali/org/anzu/test/crypto/Keys.smali": SMALI_KEYSTORE,
    }
    row = prepare(make_apk(src / "a.apk", libs=()))
    out = apk_sidecar.decompile(row["id"])
    assert out["status"] == "partial"
    assert apk_sidecar.metadata(row["id"], "smali")["smali_files"] == 5
    ends = apk_sidecar.apk_extract_endpoints(row["id"])
    assert ends["coverage"]["smali_sources"] is True
    assert any(r["endpoint"] == "https://smali-api.anzu-test.example.com/v1/users" for r in ends["endpoints"])
    crypto = apk_sidecar.apk_crypto_hints(row["id"])
    assert crypto["coverage"]["smali_sources"] is True
    assert any(f["rule"] == "ecb_mode" and f["sources"] == ["smali"] for f in crypto["findings"])
    assert crypto["key_storage"]["posture"] == "android_keystore"


def test_smali_unescape_and_literals():
    from app.reverse_engineering import apk_strings
    assert apk_strings._smali_unescape(r"hello\nworld") == "hello\nworld"
    assert apk_strings._smali_unescape(r"quote\"here") == 'quote"here'
    assert apk_strings._smali_unescape(r"\u0041\u0042") == "AB"
    src = apk_strings.Source("smali", "x.smali", [
        (1, '    const-string v0, "https://a.example.com"'),
        (2, '    const-string/jumbo v1, "wss://b.example.com/s"'),
        (3, "    return-object v0"),
    ])
    assert list(apk_strings._smali_literals(src)) == [
        (1, "https://a.example.com"), (2, "wss://b.example.com/s")]


def _smali_findings(body: str) -> dict[str, list[dict]]:
    from app.reverse_engineering import apk_strings
    lines = [(i + 1, t) for i, t in enumerate(body.splitlines())]
    scanner = apk_strings.CryptoScanner()
    scanner._smali(apk_strings.Source("smali", "x.smali", lines))
    rules: dict[str, list[dict]] = {}
    for f in scanner.findings():
        rules.setdefault(f["rule"], []).append(f)
    return rules


_SMALI_HDR = ".class public Lx/Y;\n.super Ljava/lang/Object;\n"
_CIPHER_CALL = "    invoke-static {v0}, Ljavax/crypto/Cipher;->getInstance(Ljava/lang/String;)Ljavax/crypto/Cipher;\n"


def test_smali_register_state_resets_per_method():
    body = _SMALI_HDR + (
        ".method public a()V\n    .locals 1\n    const-string v0, \"AES/ECB/PKCS5Padding\"\n    return-void\n.end method\n"
        ".method public b()V\n    .locals 1\n" + _CIPHER_CALL + "    return-void\n.end method\n")
    assert "ecb_mode" not in _smali_findings(body)


@pytest.mark.parametrize("clobber", [
    "sget-object v0, Lx/Y;->f:Ljava/lang/String;",
    "iget-object v0, p0, Lx/Y;->f:Ljava/lang/String;",
    "iget-wide v0, p0, Lx/Y;->w:J",
    "check-cast v0, Ljava/lang/String;",
    "aget-object v0, v1, v2",
    "aget-char v0, v1, v2",
    "add-int/lit8 v0, v1, 0x1",
    "move-wide v0, v2",
    "move-exception v0",
    "instance-of v0, v1, Ljava/lang/String;",
    "array-length v0, v1",
    "const-wide/16 v0, 0x0",
])
def test_smali_destination_clobbers(clobber):
    body = _SMALI_HDR + (
        ".method public a()V\n    .locals 3\n    const-string v0, \"AES/ECB/PKCS5Padding\"\n"
        f"    {clobber}\n" + _CIPHER_CALL + "    return-void\n.end method\n")
    assert "ecb_mode" not in _smali_findings(body)


def test_smali_wide_clobbers_next_register():
    body = _SMALI_HDR + (
        ".method public a()V\n    .locals 3\n    const-string v1, \"AES/ECB/PKCS5Padding\"\n"
        "    move-wide v0, v2\n"
        "    invoke-static {v1}, Ljavax/crypto/Cipher;->getInstance(Ljava/lang/String;)Ljavax/crypto/Cipher;\n"
        "    return-void\n.end method\n")
    assert "ecb_mode" not in _smali_findings(body)


def test_smali_read_only_operands_do_not_clobber():
    body = _SMALI_HDR + (
        ".method public a()V\n    .locals 3\n    const-string v0, \"AES/ECB/PKCS5Padding\"\n"
        "    if-eqz v0, :cond_0\n    iput-object v0, p0, Lx/Y;->f:Ljava/lang/String;\n"
        "    :cond_0\n" + _CIPHER_CALL + "    return-void\n.end method\n")
    assert "ecb_mode" in _smali_findings(body)


def _iv_body(middle: str, call_reg: str = "v0") -> str:
    return _SMALI_HDR + (
        ".method public a()V\n    .locals 4\n" + middle +
        "    new-instance v2, Ljavax/crypto/spec/IvParameterSpec;\n"
        f"    invoke-direct {{v2, {call_reg}}}, Ljavax/crypto/spec/IvParameterSpec;-><init>([B)V\n"
        "    return-void\n.end method\n")


def test_smali_iv_size_comes_from_new_array_size_register():
    body = _iv_body("    const/16 v1, 0xc\n    const/4 v3, 0x5\n    new-array v0, v1, [B\n")
    assert _smali_findings(body)["static_iv"][0]["detail"].startswith("IV is a zero-filled byte[12]")


def test_smali_iv_register_mismatch_is_not_flagged():
    body = _iv_body("    const/16 v1, 0x10\n    new-array v3, v1, [B\n    invoke-static {}, Lx/Y;->iv()[B\n"
                    "    move-result-object v0\n")
    assert "static_iv" not in _smali_findings(body)


@pytest.mark.parametrize("write", [
    "    const/4 v3, 0x1\n    aput-byte v3, v0, v3\n",
    "    new-instance v3, Ljava/security/SecureRandom;\n"
    "    invoke-virtual {v3, v0}, Ljava/security/SecureRandom;->nextBytes([B)V\n",
])
def test_smali_iv_written_before_call_is_not_zero_filled(write):
    body = _iv_body("    const/16 v1, 0x10\n    new-array v0, v1, [B\n" + write)
    assert "static_iv" not in _smali_findings(body)


def test_smali_iv_fill_array_data_is_inline_not_zero():
    body = _iv_body("    const/16 v1, 0x10\n    new-array v0, v1, [B\n    fill-array-data v0, :array_0\n")
    detail = _smali_findings(body)["static_iv"][0]["detail"]
    assert "zero-filled" not in detail and "fill-array-data" in detail


def test_smali_inline_key_requires_key_register():
    def body(key_reg: str, extra: str = "") -> str:
        return _SMALI_HDR + (
            ".method public a()V\n    .locals 4\n    const/16 v1, 0x10\n    new-array v0, v1, [B\n" + extra +
            "    invoke-static {}, Lx/Y;->k()[B\n    move-result-object v3\n"
            "    const-string v1, \"AES\"\n    new-instance v2, Ljavax/crypto/spec/SecretKeySpec;\n"
            f"    invoke-direct {{v2, {key_reg}, v1}}, Ljavax/crypto/spec/SecretKeySpec;-><init>([BLjava/lang/String;)V\n"
            "    return-void\n.end method\n")
    assert "static_key" not in _smali_findings(body("v3"))
    assert "static_key" not in _smali_findings(body("v0", "    aput-byte v1, v0, v1\n"))
    found = _smali_findings(body("v0"))["static_key"][0]
    assert "zero-filled byte[16]" in found["detail"] and found["confidence"] == "medium"


def test_smali_java_util_base64_decoder_feeds_secret_key():
    body = _SMALI_HDR + (
        ".method public a()V\n    .locals 4\n"
        "    invoke-static {}, Ljava/util/Base64;->getDecoder()Ljava/util/Base64$Decoder;\n"
        "    move-result-object v0\n"
        "    const-string v1, \"c2VjcmV0LWtleS0xMjM0NQ==\"\n"
        "    invoke-virtual {v0, v1}, Ljava/util/Base64$Decoder;->decode(Ljava/lang/String;)[B\n"
        "    move-result-object v2\n"
        "    const-string v1, \"AES\"\n    new-instance v3, Ljavax/crypto/spec/SecretKeySpec;\n"
        "    invoke-direct {v3, v2, v1}, Ljavax/crypto/spec/SecretKeySpec;-><init>([BLjava/lang/String;)V\n"
        "    return-void\n.end method\n")
    found = _smali_findings(body)["static_key"][0]
    assert found["value"] == "c2VjcmV0LWtleS0xMjM0NQ==" and found["confidence"] == "high"
