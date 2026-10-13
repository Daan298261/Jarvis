"""RFC-0207 slice 8 unit tests: DEX class tables, ProGuard/R8 renaming, protector stubs, jadx markers.

DEX files are built in-memory with real string_ids/type_ids/class_defs tables (no toolchain needed).
"""
from __future__ import annotations

import struct
import threading
import zipfile
from pathlib import Path

import pytest

from app.reverse_engineering import apk_obfuscation as obf
from app.reverse_engineering.apk_sidecar import DecompileCancelled


def make_dex(classes: list[str], extra_strings: tuple[str, ...] = ()) -> bytes:
    strings = list(dict.fromkeys([*classes, *extra_strings]))
    types = list(classes)
    class_defs = list(range(len(classes)))

    header = bytearray(0x70)
    header[0:8] = b"dex\n035\x00"
    string_ids_off = 0x70
    type_ids_off = string_ids_off + 4 * len(strings)
    class_defs_off = type_ids_off + 4 * len(types)

    struct.pack_into("<II", header, 0x38, len(strings), string_ids_off)
    struct.pack_into("<II", header, 0x40, len(types), type_ids_off)
    struct.pack_into("<II", header, 0x60, len(class_defs), class_defs_off)

    data = b""
    data_offsets = []
    data_off = class_defs_off + 32 * len(class_defs)
    for s in strings:
        assert s.isascii() and len(s) < 128
        data_offsets.append(data_off + len(data))
        data += bytes([len(s)]) + s.encode("ascii") + b"\x00"

    out = bytes(header)
    out += b"".join(struct.pack("<I", off) for off in data_offsets)
    out += b"".join(struct.pack("<I", strings.index(t)) for t in types)
    out += b"".join(struct.pack("<I", c) + b"\x00" * 28 for c in class_defs)
    out += data
    assert len(out) == data_off + len(data)
    return out


def make_apk(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_dex_class_descriptors_round_trip():
    descs = ["Lorg/anzu/test/MainActivity;", "La/b;", "Lorg/anzu/test/R$string;"]
    assert obf.dex_class_descriptors(make_dex(descs, ("extra",))) == descs


def test_dex_class_descriptors_rejects_malformed(monkeypatch):
    with pytest.raises(ValueError):
        obf.dex_class_descriptors(b"dex\n035\x00synthetic")

    buf = bytearray(make_dex(["La;"]))
    class_defs_off = struct.unpack_from("<I", buf, 0x64)[0]
    struct.pack_into("<I", buf, class_defs_off, 5)
    with pytest.raises(ValueError, match="outside type_ids"):
        obf.dex_class_descriptors(bytes(buf))

    buf = bytearray(make_dex(["La;"]))
    struct.pack_into("<I", buf, 0x44, len(buf))
    with pytest.raises(ValueError, match="type_ids table"):
        obf.dex_class_descriptors(bytes(buf))

    monkeypatch.setattr(obf, "MAX_DEX_CLASSES", 1)
    with pytest.raises(ValueError, match="cap"):
        obf.dex_class_descriptors(make_dex(["La;", "Lb;"]))


def test_is_obfuscated_name():
    assert obf.is_obfuscated_name("a")
    assert obf.is_obfuscated_name("b")
    assert obf.is_obfuscated_name("aa")
    assert obf.is_obfuscated_name("Ab")
    assert obf.is_obfuscated_name("a0")
    assert obf.is_obfuscated_name("ab12")
    assert not obf.is_obfuscated_name("R")
    assert not obf.is_obfuscated_name("BR")
    assert not obf.is_obfuscated_name("BuildConfig")
    assert not obf.is_obfuscated_name("MainActivity")
    assert not obf.is_obfuscated_name("abc")
    assert not obf.is_obfuscated_name("a123")


def test_classify_descriptor():
    info = obf.classify_descriptor("La/b/c;")
    assert info == {
        "name": "a.b.c",
        "package": "a.b",
        "inner": False,
        "generated": False,
        "obfuscated": True,
        "obfuscated_package": True,
    }

    info = obf.classify_descriptor("Lorg/anzu/test/MainActivity;")
    assert info["obfuscated"] is False
    assert info["obfuscated_package"] is False

    info = obf.classify_descriptor("Lorg/anzu/test/R$string;")
    assert info["inner"] is True
    assert info["generated"] is True

    info = obf.classify_descriptor("La;")
    assert info["package"] == ""
    assert info["obfuscated_package"] is False

    assert obf.classify_descriptor("[I") is None
    assert obf.classify_descriptor("I") is None
    assert obf.classify_descriptor("L;") is None


def test_assess_descriptors_ratio_samples_and_protectors():
    descs = [f"Lo/{chr(97 + i % 26)}{i // 26 or ''};" for i in range(30)]
    descs += [f"Lorg/anzu/app/Screen{i};" for i in range(10)]
    descs += [
        "Lorg/anzu/app/R;",
        "Lorg/anzu/app/R$id;",
        "Lorg/anzu/app/Screen0$Inner;",
        "Lcom/stub/StubApp;",
        "Lcom/secneo/apkwrapper/ApplicationWrapper;",
        "Lcom/secneo/apkwrapper/Helper;",
        "Lcom/stub/StubAppX;",
    ]

    result = obf.assess_descriptors(descs)

    top_level = 30 + 10 + 4
    assert result["top_level_classes"] == top_level
    assert result["obfuscated_classes"] == 30
    assert result["obfuscated_ratio"] == round(30 / top_level, 4)
    assert len(result["samples"]) == obf.MAX_SAMPLES
    assert result["samples"][0] == "o.a"
    assert result["protectors"] == [
        {"protector": "Qihoo 360 Jiagu", "class": "com.stub.StubApp"},
        {"protector": "SecNeo/Bangcle", "class": "com.secneo.apkwrapper.ApplicationWrapper"},
    ]
    assert result["obfuscated_packages"] == 1

    empty = obf.assess_descriptors([])
    assert empty["obfuscated_ratio"] == 0.0
    assert empty["class_count"] == 0


def test_scan_jadx_markers(tmp_path):
    (tmp_path / "sources" / "a").mkdir(parents=True)
    (tmp_path / "sources" / "a" / "A.java").write_text(
        "class A {\n    /* JADX WARNING: Code restructure failed */\n    /* JADX ERROR: x */ /* JADX WARNING: y */\n}\n"
    )
    (tmp_path / "sources" / "b").mkdir(parents=True)
    (tmp_path / "sources" / "b" / "B.java").write_text(
        "/* Code decompiled incorrectly, please refer to instructions dump. */\n"
    )
    (tmp_path / "sources" / "b" / "C.java").write_text("class C {}\n")

    result = obf.scan_jadx_markers(tmp_path / "sources")
    assert result["scanned"] is True
    assert result["java_files"] == 3
    assert result["files_with_markers"] == 2
    assert result["warnings"] == 2
    assert result["errors"] == 1
    assert result["bad_code_methods"] == 1
    assert {"ref": "sources/a/A.java:2", "marker": "JADX WARNING"} in result["samples"]

    missing = obf.scan_jadx_markers(tmp_path / "missing")
    assert missing["scanned"] is False
    assert missing["java_files"] == 0


def test_scan_jadx_markers_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(obf, "MAX_TEXT_FILE_BYTES", 10)
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "A.java").write_text("x" * 50)

    result = obf.scan_jadx_markers(tmp_path / "sources")
    assert result["oversized"] == ["A.java"]
    assert result["java_files"] == 0


def test_assess_end_to_end(tmp_path):
    obfuscated = [f"Lo/{chr(97 + i)};" for i in range(25)]
    normal = [f"Lorg/anzu/app/Screen{i};" for i in range(5)]
    base = make_apk(
        tmp_path / "base.apk",
        {
            "classes.dex": make_dex(obfuscated + normal),
            "classes2.dex": make_dex(["Lcom/tencent/StubShell/TxAppEntry;"]),
            "classes3.dex": b"dex\n035\x00broken",
        },
    )
    split = make_apk(tmp_path / "split.apk", {"lib/arm64-v8a/libx.so": b"x"})
    apk_root = tmp_path / "apk"
    (apk_root / "jadx" / "sources" / "o").mkdir(parents=True)
    (apk_root / "jadx" / "sources" / "o" / "a.java").write_text("/* JADX WARNING: bad */\n")

    parts = [
        {"name": "base.apk", "path": str(base), "dex": True},
        {"name": "split.apk", "path": str(split), "dex": False},
    ]

    result = obf.assess(apk_root, parts)

    assert result["state"] == "assessed"
    assert len(result["dex_files"]) == 2
    assert result["coverage"]["dex_parts"] == 1
    assert result["top_level_classes"] == 31
    assert result["obfuscated_classes"] == 25
    assert result["heavily_obfuscated"] is True
    assert result["protectors"][0]["protector"] == "Tencent Legu"

    expected_unknowns = [
        f"DEX code exhibits heavy identifier renaming (ProGuard/R8); {round(25 / 31 * 100)}% of class names are obfuscated.",
        "DEX contains the Tencent Legu protector stub com.tencent.StubShell.TxAppEntry; the real bytecode is likely encrypted and loaded at runtime, so static coverage is incomplete.",
        "jadx emitted 1 JADX WARNING and 0 JADX ERROR marker(s) and 0 incorrectly decompiled method(s) across 1 Java file(s); those methods are partial pseudo-code.",
    ]
    for u in expected_unknowns:
        assert u in result["unknowns"]

    assert any(u.startswith("base.apk!classes3.dex: DEX class table could not be parsed") for u in result["unknowns"])


def test_assess_below_min_classes_is_not_heavy(tmp_path):
    obfuscated = [f"Lo/{chr(97 + i)};" for i in range(5)]
    base = make_apk(tmp_path / "base.apk", {"classes.dex": make_dex(obfuscated)})
    apk_root = tmp_path / "apk"
    (apk_root / "jadx" / "sources").mkdir(parents=True)

    parts = [{"name": "base.apk", "path": str(base), "dex": True}]
    result = obf.assess(apk_root, parts)

    assert result["heavily_obfuscated"] is False
    assert not any("heavy identifier renaming" in u for u in result["unknowns"])


def test_assess_without_dex_parts(tmp_path):
    apk_root = tmp_path / "apk"  # never decompiled: no jadx/sources tree

    parts = [{"name": "no_dex.apk", "path": str(tmp_path / "no_dex.apk"), "dex": False}]
    result = obf.assess(apk_root, parts)

    assert result["state"] == "no_dex"
    assert result["unknowns"] == []
    assert result["jadx_markers"]["scanned"] is False


def test_assess_unassessed_when_all_dex_broken(tmp_path):
    base = make_apk(tmp_path / "base.apk", {"classes.dex": b"garbage"})
    apk_root = tmp_path / "apk"
    (apk_root / "jadx" / "sources").mkdir(parents=True)

    parts = [{"name": "base.apk", "path": str(base), "dex": True}]
    result = obf.assess(apk_root, parts)

    assert result["state"] == "unassessed"
    assert "No DEX class table could be assessed; identifier renaming and protector stubs are unknown." in result["unknowns"]


def test_assess_oversized_dex_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(obf, "MAX_DEX_BYTES", 8)
    base = make_apk(tmp_path / "base.apk", {"classes.dex": make_dex(["La;"])})
    apk_root = tmp_path / "apk"
    (apk_root / "jadx" / "sources").mkdir(parents=True)

    parts = [{"name": "base.apk", "path": str(base), "dex": True}]
    result = obf.assess(apk_root, parts)

    assert any("exceeds the" in u and "DEX cap" in u for u in result["unknowns"])
    assert result["dex_files"] == []


def test_assess_honours_cancel(tmp_path):
    base = make_apk(tmp_path / "base.apk", {"classes.dex": make_dex(["La;"])})
    apk_root = tmp_path / "apk"
    (apk_root / "jadx" / "sources").mkdir(parents=True)

    parts = [{"name": "base.apk", "path": str(base), "dex": True}]
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(DecompileCancelled):
        obf.assess(apk_root, parts, cancel)


def test_unopenable_part_is_unknown(tmp_path):
    bad = tmp_path / "bad.apk"
    bad.write_text("not a zip")
    apk_root = tmp_path / "apk"
    (apk_root / "jadx" / "sources").mkdir(parents=True)

    parts = [{"name": "bad.apk", "path": str(bad), "dex": True}]
    result = obf.assess(apk_root, parts)

    assert "APK part bad.apk could not be opened for class-table assessment." in result["unknowns"]
