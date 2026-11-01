"""Synthetic, dump-free known-plaintext recovery and ingest acceptance checks."""
import hashlib
import io
import json
from pathlib import Path
import random

import pytest

from app.reverse_engineering import ffs_ingest, store
from app.reverse_engineering.tab_analyzer import parse_tab_header
from app.reverse_engineering.tab_recovery import (
    MODELS, TableRecovery, candidate_pair, derive_mapping, mapping_status,
)


def table(body, key=None):
    header = bytearray(16 if key is None else 64)
    header[:4] = b"AT\0\2"
    header[6:10] = bytes([6, int(key is not None), 0, 2])
    header[12:16] = (91).to_bytes(4, "big")
    if key is not None:
        header[16:23] = b"0\0EX" + bytes([key]) + b"\0\1"
    return bytes(header) + body


def profile(path, raw, **extra):
    return dict(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                container=parse_tab_header(raw[:64], len(raw)), **extra)


def recover(tmp_path, files):
    profiles = [profile(path, data) for path, data in files.items()]
    def entries():
        for path, raw in files.items():
            yield path, len(raw), 0, lambda raw=raw: io.BytesIO(raw)
    return TableRecovery(profiles).run(entries, tmp_path / "decoded")


def test_pair_matching_requires_body_size_and_schema():
    a = profile("make/en_text.tab", table(b"x" * 100, 12))
    b = profile("PubTab/en_text.tab", table(b"y" * 100))
    assert candidate_pair(a, b)
    b["container"]["record_count"] += 1
    assert not candidate_pair(a, b)
    b = profile("else/en_text.tab", b"x" * 100, xor_key=45)
    assert candidate_pair(a, b)
    b["path"] = "else/nl_text.tab"
    assert not candidate_pair(a, b)
    a["container"]["anomalies"] = ["bad descriptor"]
    assert not candidate_pair(a, b)


def test_observed_bijection_and_reject_conflicts():
    plain = bytes(range(256)) * 2
    cipher = bytes(b ^ 45 for b in plain)
    result = derive_mapping(cipher, plain)
    assert mapping_status(result) == dict(observed_inputs=256, distinct_outputs=256, bijection=True)
    assert not mapping_status(derive_mapping(cipher[:100], plain[:100]))["bijection"]
    assert derive_mapping(b"aa", b"ab") is None
    assert not mapping_status(derive_mapping(bytes(range(256)), b"a" * 256))["bijection"]
    assert derive_mapping(b"a", b"ab") is None
    assert derive_mapping(b"", b"") is None
    with pytest.raises(ValueError):
        derive_mapping(cipher, plain, "invalid")


@pytest.mark.parametrize("model", MODELS)
def test_models_decode_complete_body_and_report_unverified_files(tmp_path, model):
    # Repeated symbols in differing positions distinguish offset from fixed maps.
    plain = random.Random(10).randbytes(8192)
    encoded = []
    for i, b in enumerate(plain):
        if model == "plain-xor-offset":
            b ^= i & 255
        c = (b * 197 + 37) & 255
        if model == "cipher-xor-offset":
            c ^= i & 255
        elif model == "cipher-minus-offset":
            c = (c + i) & 255
        encoded.append(c)
    files = {"PubTab/en_text.tab": table(plain), "make/en_text.tab": table(bytes(encoded), 42)}
    r = recover(tmp_path, files)
    g = r["key_ids"][0]
    assert g["solved"] and g["decoded_files"] == 1
    assert g["model"] == model
    assert (tmp_path / "decoded" / r["decoded"][0]["derivative"]).read_bytes() == plain
    assert g["independently_matched_files"] == 1


def test_bit_permutation_plus_xor_is_substitution(tmp_path):
    plain = bytes(range(256)) * 2
    cipher = bytes(int(f"{b:08b}"[::-1], 2) ^ 73 for b in plain)
    r = recover(tmp_path, {"a.tab": table(plain), "b.tab": table(cipher, 7)})
    assert r["key_ids"][0]["solved"]
    assert r["key_ids"][0]["bit_permutation_xor"] == {
        "xor": int(f"{73:08b}"[::-1], 2), "input_to_output_bits": list(reversed(range(8)))}


def test_partial_mapping_does_not_decode(tmp_path):
    p = bytes(range(80)) * 4
    r = recover(tmp_path, {"a.tab": table(p), "b.tab": table(bytes(b ^ 37 for b in p), 7)})
    assert r["pairs"] and r["key_ids"][0]["observed_inputs"] == 80
    assert not r["key_ids"][0]["solved"] and not r["decoded"]


def test_metadata_collision_records_negative_evidence(tmp_path):
    plain = random.Random(11).randbytes(1024)
    r = recover(tmp_path, {"a.tab": table(plain), "b.tab": table(b"x" * len(plain), 7)})
    assert r["candidate_pairs_tested"] == 1 and not r["pairs"]
    assert r["rejected_pairs"][0]["models_rejected"] == list(MODELS)
    assert r["key_ids"][0]["files_without_plaintext_verification"] == 1


def test_merge_partial_pairs_and_apply_to_unpaired_file(tmp_path):
    first, second = bytes(range(128)) * 2, bytes(range(128, 256)) * 3
    extra = b"unpaired content with a different size"
    files = {"a.tab": table(first), "b.tab": table(second),
             "c.tab": table(bytes(b ^ 37 for b in first), 7),
             "d.tab": table(bytes(b ^ 37 for b in second), 7),
             "e.tab": table(bytes(b ^ 37 for b in extra), 7)}
    r = recover(tmp_path, files)
    g = r["key_ids"][0]
    assert g["solved"] and g["decoded_files"] == 3
    assert g["files_without_plaintext_verification"] == 1
    d = next(d for d in r["decoded"] if d["path"] == "e.tab")
    assert (tmp_path / "decoded" / d["derivative"]).read_bytes() == extra


def test_decode_cancellation_removes_partial_derivative(tmp_path):
    plain = random.Random(5).randbytes(1024)
    raw = table(bytes(b ^ 37 for b in plain), 7)
    group = {"model": "substitution", "cipher_to_plain": [b ^ 37 for b in range(256)]}
    def check():
        raise ffs_ingest.IngestCancelled()
    with pytest.raises(ffs_ingest.IngestCancelled):
        TableRecovery._decode(lambda: io.BytesIO(raw), profile("a.tab", raw), group, tmp_path / "out.body", check)
    assert not list(tmp_path.iterdir())


def test_conflicting_same_key_across_files_cannot_decode(tmp_path):
    p = bytes(range(256)) * 2
    r = recover(tmp_path, {"a.tab": table(p), "b.tab": table(bytes(b ^ 37 for b in p), 7),
                           "c.tab": table(bytes(b ^ 38 for b in p), 7)})
    assert r["key_ids"][0]["conflicting_pairs"]
    assert not r["key_ids"][0]["solved"] and not r["decoded"]


def test_tsv_reference_requires_structure_and_source_hash(tmp_path):
    plain = (b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ\t123\n" * 10)
    cipher = bytes(b ^ 37 for b in plain)
    raw = bytes(b ^ 73 for b in plain)
    files = {"ref/en_text.tab": raw, "make/en_text.tab": table(cipher, 7)}
    profiles = [profile(path, data, xor_key=73 if path.startswith("ref") else None) for path, data in files.items()]
    def entries():
        for path, data in files.items():
            yield path, len(data), 0, lambda data=data: io.BytesIO(data)
    assert TableRecovery(profiles).run(entries, tmp_path)["pairs"]
    profiles[0]["sha256"] = "0" * 64
    r = TableRecovery(profiles).run(entries, tmp_path)
    assert not r["pairs"] and r["gaps"]["reference_changed_or_unreadable"] == 1


def test_reference_budget_and_cancel(tmp_path, monkeypatch):
    from app.reverse_engineering import tab_recovery
    monkeypatch.setattr(tab_recovery, "MAX_PAIR_BYTES", 32)
    r = recover(tmp_path, {"a.tab": table(b"a" * 100), "b.tab": table(b"b" * 100, 7)})
    assert r["gaps"]["reference_budget"] == 1
    def check():
        raise RuntimeError("cancel")
    with pytest.raises(RuntimeError, match="cancel"):
        TableRecovery([]).run(lambda: [("a", 1, 0, None)], tmp_path, check)


def test_ingest_wires_citable_recovery_and_safe_derivatives(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(store, "resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    folder = tmp_path / "input"
    folder.mkdir()
    plain = bytes(range(256)) * 2
    (folder / "plain.tab").write_bytes(table(plain))
    (folder / "keyed.tab").write_bytes(table(bytes(b ^ 37 for b in plain), 7))
    row = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)]).run_sync()
    assert row["status"] == "completed", row.get("last_error")
    evidence = [e for e in row["evidence"] if e["operation"] == "ffs_tab_recovery"]
    assert len(evidence) == 1
    directory = store.directory(row["id"])
    report = json.loads((directory / "index/tab_recovery.json").read_text())
    assert report["key_ids"][0]["solved"]
    summary = json.loads((directory / "index/tab_profile.json").read_text())["summary"]
    assert summary["known_plaintext_recovery"]["decoded_files"] == 1
    derivative = directory / "index/decoded_tables" / report["decoded"][0]["derivative"]
    assert derivative.read_bytes() == plain
    ev = json.loads((directory / "evidence" / (evidence[0]["id"] + ".json")).read_text())
    assert ev["result"]["key_ids"][0]["cipher_to_plain"] == [b ^ 37 for b in range(256)]
    assert ev["result"]["report_sha256"] == hashlib.sha256((directory / "index/tab_recovery.json").read_bytes()).hexdigest()
