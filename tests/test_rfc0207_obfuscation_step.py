"""RFC-0207 slice 8 integration: apk_assess_obfuscation wired through claim, evidence, custody,
metadata, summary, report synthesis, catalog and REST. Uses the slice 1-7 FakeWSL harness."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reverse_engineering import apk_sidecar, store
from test_rfc0207_apk_sidecar import env, evidence, make_apk, prepare  # noqa: F401  (env is a fixture)
from test_rfc0207_obfuscation import make_dex

RENAMED = [f"Lo/{chr(97 + i)};" for i in range(25)]
NAMED = [f"Lorg/anzu/test/Screen{i};" for i in range(5)]
STUB = "Lcom/tencent/StubShell/TxAppEntry;"
HEAVY = f"DEX code exhibits heavy identifier renaming (ProGuard/R8); {round(25 / 31 * 100)}% of class names are obfuscated."
LEGU = ("DEX contains the Tencent Legu protector stub com.tencent.StubShell.TxAppEntry; the real bytecode is likely "
        "encrypted and loaded at runtime, so static coverage is incomplete.")
MARKERS = ("jadx emitted 1 JADX WARNING and 0 JADX ERROR marker(s) and 1 incorrectly decompiled method(s) across "
           "1 Java file(s); those methods are partial pseudo-code.")


def _obfuscated_apk(src, name="obf.apk"):
    return make_apk(src / name, dex=False, extra={"classes.dex": make_dex(RENAMED + NAMED),
                                                  "classes2.dex": make_dex([STUB])})


def _decompiled(src, fake, name="obf.apk"):
    fake.java_files = {"o/a.java": "class a {\n    /* JADX WARNING: Code restructure failed */\n"
                                   "    /* Code decompiled incorrectly, please refer to instructions dump. */\n}\n"}
    row = prepare(_obfuscated_apk(src, name))
    apk_sidecar.call(row["id"], "apk_decompile", {})
    return store.load(row["id"])


def test_obfuscation_step_records_evidence_custody_metadata_and_unknowns(env):
    src, fake = env
    row = _decompiled(src, fake)
    before = len(row["evidence"])
    out = apk_sidecar.apk_assess_obfuscation(row["id"])
    eid = f"E{before + 1:05d}"
    assert out["evidence_id"] == eid and out["investigation_status"] == "partial"
    assert out["state"] == "assessed" and out["top_level_classes"] == 31 and out["obfuscated_classes"] == 25
    assert out["heavily_obfuscated"] is True
    assert out["protectors"] == [{"protector": "Tencent Legu", "class": "com.tencent.StubShell.TxAppEntry"}]
    assert out["jadx_markers"]["scanned"] is True and out["jadx_markers"]["bad_code_methods"] == 1
    saved = store.load(row["id"])
    assert saved["status"] == "partial" and saved["evidence"][-1] == {
        "id": eid, "operation": "apk_obfuscation", "success": True}
    for unknown in (HEAVY, LEGU, MARKERS):
        assert unknown in saved["unknowns"]
    record = evidence(saved, eid)
    assert record["result"]["metadata"] == "apk/metadata/obfuscation.json"
    assert record["result"]["obfuscated_ratio"] == round(25 / 31, 4)
    meta = json.loads((store.directory(row["id"]) / "apk" / "metadata" / "obfuscation.json").read_text(encoding="utf-8"))
    assert meta["investigation_id"] == row["id"] and meta["obfuscated_classes"] == 25
    assert apk_sidecar.metadata(row["id"], "obfuscation") == meta
    events = [c["event"] for c in saved["chain_of_custody"]]
    assert events[-1] == "apk_obfuscation_assessed"
    custody = json.loads((store.directory(row["id"]) / "custody.json").read_text(encoding="utf-8"))
    assert custody["obfuscation_assessed_at"]
    summary = apk_sidecar.summary(row["id"])["obfuscation"]
    assert summary == {"state": "assessed", "top_level_classes": 31, "obfuscated_ratio": round(25 / 31, 4),
                       "heavily_obfuscated": True, "protectors": ["Tencent Legu"], "jadx_markers": 2}


def test_obfuscation_finding_cites_evidence_in_report(env):
    src, fake = env
    row = _decompiled(src, fake)
    decompile_eid = next(e["id"] for e in row["evidence"] if e["operation"] == "apk_decompile")
    eid = apk_sidecar.apk_assess_obfuscation(row["id"])["evidence_id"]
    reported = apk_sidecar.apk_synthesize_report(row["id"])
    assert reported["status"] == "partial"
    finding = next(f for f in reported["findings"] if f["claim"].startswith("Obfuscation and decompile coverage"))
    assert finding["evidence_ids"] == [decompile_eid, eid]
    assert finding["claim"] == (
        f"Obfuscation and decompile coverage: {round(25 / 31 * 100)}% of 31 top-level DEX class name(s) look renamed "
        "(ProGuard/R8 style); heavy identifier renaming; protector stub(s): Tencent Legu "
        "(com.tencent.StubShell.TxAppEntry); jadx markers: 1 warning(s), 0 error(s), 1 incorrectly decompiled "
        "method(s) in 1 of 1 Java file(s).")
    for unknown in (HEAVY, LEGU, MARKERS):
        assert unknown in reported["unknowns"]


def test_obfuscation_without_decompile_cites_only_its_evidence(env):
    src, _ = env
    row = prepare(_obfuscated_apk(src))
    out = apk_sidecar.apk_assess_obfuscation(row["id"])
    assert out["jadx_markers"]["scanned"] is False
    assert MARKERS not in store.load(row["id"])["unknowns"]
    reported = apk_sidecar.apk_synthesize_report(row["id"])
    finding = next(f for f in reported["findings"] if f["claim"].startswith("Obfuscation and decompile coverage"))
    assert finding["evidence_ids"] == [out["evidence_id"]]
    assert "jadx markers" not in finding["claim"]


def test_obfuscation_step_takes_the_investigation_claim(env):
    src, _ = env
    row = prepare(_obfuscated_apk(src))
    claim = apk_sidecar._claim(row["id"], "native inventory")
    with pytest.raises(ValueError, match="cannot start obfuscation assessment"):
        apk_sidecar.apk_assess_obfuscation(row["id"])
    apk_sidecar.release(row["id"], claim["_claim_token"])
    stored = store.load(row["id"])
    stored["status"] = "prepared"
    store.save(stored)
    apk_sidecar._CLAIMS[row["id"]] = "other"
    claim = {**store.load(row["id"]), "_claim_token": "mine"}
    with pytest.raises(RuntimeError, match="claim was lost"):
        apk_sidecar.apk_assess_obfuscation(row["id"], claimed=claim)
    assert not (store.directory(row["id"]) / "apk" / "metadata" / "obfuscation.json").exists()
    apk_sidecar._CLAIMS.pop(row["id"], None)
    apk_sidecar._CANCEL.pop(row["id"], None)


def test_obfuscation_metadata_rolled_back_when_save_fails(env, monkeypatch):
    src, _ = env
    row = prepare(_obfuscated_apk(src))
    path = store.directory(row["id"]) / "apk" / "metadata" / "obfuscation.json"
    real_save = store.save

    def failing_save(r):
        if any(c.get("event") == "apk_obfuscation_assessed" for c in r.get("chain_of_custody", [])):
            assert path.is_file()
            raise OSError("disk full")
        return real_save(r)
    monkeypatch.setattr(store, "save", failing_save)
    with pytest.raises(OSError, match="disk full"):
        apk_sidecar.apk_assess_obfuscation(row["id"])
    assert not path.exists() and store.load(row["id"])["status"] == "interrupted"


def test_obfuscation_cancel_marks_cancelled(env, monkeypatch):
    src, _ = env
    row = prepare(_obfuscated_apk(src))
    claim = apk_sidecar._claim(row["id"], "obfuscation assessment")
    apk_sidecar._CANCEL[row["id"]].set()
    with pytest.raises(apk_sidecar.DecompileCancelled):
        apk_sidecar.apk_assess_obfuscation(row["id"], claimed=claim)
    saved = store.load(row["id"])
    assert saved["status"] == "cancelled"
    assert saved["chain_of_custody"][-1]["event"] == "obfuscation_assessment_cancelled"


def test_obfuscation_catalog_and_rest(env):
    src, fake = env
    assert "apk_assess_obfuscation" in apk_sidecar.CATALOG
    assert apk_sidecar.CATALOG["apk_assess_obfuscation"]["inputSchema"]["additionalProperties"] is False
    row = _decompiled(src, fake)
    client = TestClient(app)
    assert client.get(f"/api/investigations/{row['id']}/apk/obfuscation").status_code == 404
    out = apk_sidecar.call(row["id"], "apk_assess_obfuscation", {})
    assert out["status"] == "evidence" and out["obfuscation"]["evidence_id"] == out["evidence_id"]
    assert out["investigation_status"] == "partial"
    res = client.get(f"/api/investigations/{row['id']}/apk/obfuscation")
    assert res.status_code == 200 and res.json()["heavily_obfuscated"] is True
    assert client.get(f"/api/investigations/{row['id']}/apk/smali").status_code == 200
    summary = client.get(f"/api/investigations/{row['id']}/apk/summary").json()
    assert summary["obfuscation"]["protectors"] == ["Tencent Legu"]


def test_class_table_of_real_d8_fixture(tmp_path):
    """The class_defs walk works on a real d8-built DEX (tests/fixtures/apk/dex_endpoints.apk)."""
    import zipfile
    from pathlib import Path

    from app.reverse_engineering import apk_obfuscation

    fixture = Path(__file__).parent / "fixtures" / "apk" / "dex_endpoints.apk"
    with zipfile.ZipFile(fixture) as z:
        descriptors = apk_obfuscation.dex_class_descriptors(z.read("classes.dex"))
    assert "Lorg/anzu/fixture/Main;" in descriptors
    result = apk_obfuscation.assess(tmp_path, [{"name": "dex_endpoints.apk", "path": str(fixture),
                                                "dex": ["classes.dex"]}])
    assert result["state"] == "assessed" and result["class_count"] == len(descriptors)
    assert result["heavily_obfuscated"] is False and result["protectors"] == []
    assert result["unknowns"] == [] and result["jadx_markers"]["scanned"] is False


def test_summary_with_partial_obfuscation_metadata(env):
    src, fake = env
    row = _decompiled(src, fake)
    apk_sidecar.apk_assess_obfuscation(row["id"])
    meta = store.directory(row["id"]) / "apk" / "metadata" / "obfuscation.json"
    doc = json.loads(meta.read_text(encoding="utf-8"))
    for key in ("top_level_classes", "jadx_markers"):
        doc.pop(key)
    doc["protectors"] = [{"class": "x"}]
    store.atomic_json(meta, doc)
    res = TestClient(app).get(f"/api/investigations/{row['id']}/apk/summary")
    assert res.status_code == 200
    view = res.json()["obfuscation"]
    assert view["state"] == "assessed" and view["heavily_obfuscated"] is True
    assert view["top_level_classes"] is None and view["jadx_markers"] is None and view["protectors"] == []
    unknowns = res.json()["unknowns"]
    for field in ("top_level_classes", "jadx_markers", "protectors[].protector"):
        assert any(f"malformed '{field}'" in u for u in unknowns)

    store.atomic_json(meta, ["not", "an", "object"])
    res = TestClient(app).get(f"/api/investigations/{row['id']}/apk/summary")
    assert res.status_code == 200 and res.json()["obfuscation"]["state"] is None
