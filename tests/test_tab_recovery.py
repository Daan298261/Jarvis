"""Synthetic, dump-free known-plaintext recovery and ingest acceptance checks."""
import hashlib
import io
import json
from pathlib import Path
import random

import pytest

from app.reverse_engineering import ffs_ingest, store
from app.reverse_engineering.tab_analyzer import parse_tab_header
from app.reverse_engineering import tab_recovery
from app.reverse_engineering.tab_recovery import (
    MIN_BODY_BYTES, MIN_SYMBOLS, MODELS, MemberReadError, TableRecovery, candidate_pair, derive_mapping,
    mapping_status,
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


def entries_for(files):
    def entries():
        for path, raw in files.items():
            yield path, len(raw), 0, lambda raw=raw: io.BytesIO(raw)
    return entries


def recover(tmp_path, files, profiles=None, **kwargs):
    profiles = profiles or [profile(path, data) for path, data in files.items()]
    return TableRecovery(profiles).run(entries_for(files), tmp_path / "decoded", **kwargs)


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
    assert r["rejected_pairs"][0]["outcome"] == "rejected"
    assert {o["result"] for o in r["rejected_pairs"][0]["model_outcomes"].values()} == {"inconsistent"}
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
    assert not r["pairs"] and r["gaps"] == {"reference_changed": 1}
    assert r["integrity"] == {"changed": [{"path": "ref/en_text.tab", "stage": "reference"}], "unreadable": []}


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


# ----- review #672: key-less legacy profiles, minimums, verification, integrity, cleanup -----

KEY = [b ^ 37 for b in range(256)]


def keyed(body, key=7):
    return table(bytes(KEY[b] for b in body), key)


def legacy_profile(path, raw):
    """A profile from an index written before the container parser (16 header bytes kept)."""
    return dict(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                container=parse_tab_header(raw[:16], len(raw)))


def ingest_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(store, "resolve_allowed_path", lambda path, allowed: Path(path).resolve())
    folder = tmp_path / "input"
    folder.mkdir()
    return folder


def solvable_folder(folder, extra=(b"unpaired content of another size",)):
    plain = bytes(range(256)) * 2
    (folder / "a_plain.tab").write_bytes(table(plain))
    (folder / "b_keyed.tab").write_bytes(keyed(plain))
    for i, body in enumerate(extra):
        (folder / f"c_extra{i}.tab").write_bytes(keyed(body))
    return plain


def custody(ident):
    return json.loads((store.directory(ident) / "index" / ffs_ingest.CUSTODY_FILE).read_text())


def test_legacy_keyed_profiles_without_key_id_are_neither_paired_nor_decoded(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "b.tab": keyed(plain),
             "c.tab": table(bytes(b ^ 99 for b in b"different key id content" * 4), 9),
             "z/readme.txt": b"hello"}
    profiles = [legacy_profile(k, v) for k, v in files.items() if k.endswith(".tab")]
    assert all(p["container"].get("key_id") is None for p in profiles)
    assert candidate_pair(profile("b.tab", files["b.tab"]), profiles[0])  # pairs once the key id is known
    assert not candidate_pair(profiles[1], profiles[0])
    r = recover(tmp_path, files, profiles)
    assert r["candidate_pairs_tested"] == 0 and not r["pairs"] and not r["decoded"]
    assert r["key_ids"] == [] and r["gaps"] == {"keyed_without_key_id": 2}
    assert r["corpus"]["keyed_without_key_id"] == 2
    assert not (tmp_path / "decoded").exists()


def test_key_less_profile_is_excluded_next_to_a_solved_key(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "b.tab": keyed(plain), "c.tab": keyed(b"same transform, unknown key" * 3)}
    profiles = [profile(k, v) for k, v in files.items()]
    profiles[2] = legacy_profile("c.tab", files["c.tab"])
    r = recover(tmp_path, files, profiles)
    assert [g["key_id"] for g in r["key_ids"]] == [7] and r["key_ids"][0]["solved"]
    assert [d["path"] for d in r["decoded"]] == ["b.tab"]  # never the plain reference nor the key-less file
    assert r["gaps"] == {"keyed_without_key_id": 1}


def test_ingest_resumes_a_pre_container_index_and_completes(tmp_path, monkeypatch):
    folder = ingest_env(tmp_path, monkeypatch)
    plain = bytes(range(256)) * 2
    (folder / "a_plain.tab").write_bytes(table(plain))
    (folder / "b_keyed.tab").write_bytes(keyed(plain))
    (folder / "c_readme.txt").write_bytes(b"hello")
    first = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)], stop_after=2).run_sync()
    ident = first["id"]
    index = store.directory(ident) / "index" / ffs_ingest.INDEX_FILE
    lines = [json.loads(line) for line in index.read_text().splitlines()]
    for line in lines:
        line.pop("tab_header_hex", None)  # written by the pre-container tool version
    index.write_text("".join(json.dumps(line) + "\n" for line in lines))
    row = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)], investigation_id=ident).run_sync()
    assert row["status"] == "completed", row.get("last_error")
    assert row["ffs"]["coverage"] == "complete" and row["ffs"]["files_indexed"] == 3
    report = json.loads((store.directory(ident) / "index/tab_recovery.json").read_text())
    assert report["gaps"] == {"keyed_without_key_id": 1} and not report["decoded"]
    assert custody(ident)["sessions"][-1]["outcome"] == "completed"


@pytest.mark.parametrize("length, accepted", [(MIN_BODY_BYTES - 1, False), (MIN_BODY_BYTES, True)])
def test_minimum_body_bytes_boundary(tmp_path, length, accepted):
    plain = bytes(range(length))  # every symbol distinct, so only the length decides
    r = recover(tmp_path, {"a.tab": table(plain), "b.tab": keyed(plain)})
    assert bool(r["pairs"]) is accepted
    if not accepted:
        rejected = r["rejected_pairs"][0]
        assert rejected["outcome"] == "skipped_below_minimum" and rejected["models_rejected"] != list(MODELS)
        assert rejected["model_outcomes"]["substitution"] == {
            "result": "below_minimum_body_bytes", "observed_inputs": length, "distinct_outputs": length}
        assert r["gaps"] == {"pairs_below_minimum": 1}


@pytest.mark.parametrize("inputs, outputs, accepted", [
    (MIN_SYMBOLS - 1, MIN_SYMBOLS - 1, False),  # too few observed inputs
    (MIN_SYMBOLS, MIN_SYMBOLS - 1, False),  # enough inputs, too few distinct outputs
    (MIN_SYMBOLS, MIN_SYMBOLS, True),
])
def test_minimum_symbol_coverage_boundary(tmp_path, inputs, outputs, accepted):
    cipher_symbols = bytes(range(inputs))
    plain_symbols = bytes(min(i, outputs - 1) for i in range(inputs))
    reps = -(-128 // inputs)  # comfortably above the body minimum
    files = {"a.tab": table(plain_symbols * reps), "b.tab": table(cipher_symbols * reps, 7)}
    r = recover(tmp_path, files)
    assert bool(r["pairs"]) is accepted
    if accepted:
        assert r["pairs"][0]["model"] == "substitution"
        assert r["pairs"][0]["observed_inputs"] == r["pairs"][0]["distinct_outputs"] == MIN_SYMBOLS
    else:
        rejected = r["rejected_pairs"][0]
        assert rejected["outcome"] == "skipped_below_minimum"
        assert rejected["model_outcomes"]["substitution"] == {
            "result": "below_minimum_symbols", "observed_inputs": inputs, "distinct_outputs": outputs}


def test_short_consistent_pair_is_skipped_not_rejected(tmp_path):
    plain = bytes(range(32))
    r = recover(tmp_path, {"a.tab": table(plain), "b.tab": table(bytes(b ^ 37 for b in plain), 7)})
    rejected = r["rejected_pairs"][0]
    assert rejected["outcome"] == "skipped_below_minimum"
    assert rejected["models_rejected"] != list(MODELS)
    assert {o["result"] for o in rejected["model_outcomes"].values()} <= {"below_minimum_body_bytes", "inconsistent"}


def test_each_decoded_file_states_plaintext_verification(tmp_path):
    plain, extra = bytes(range(256)) * 2, b"unpaired" * 10
    r = recover(tmp_path, {"a.tab": table(plain), "c.tab": keyed(plain), "e.tab": keyed(extra)})
    by_path = {d["path"]: d for d in r["decoded"]}
    assert by_path["c.tab"]["plaintext_verified"] is True
    assert by_path["c.tab"]["verified_against"] == [{
        "reference_path": "a.tab", "reference_sha256": hashlib.sha256(table(plain)).hexdigest(),
        "reference_body_sha256": hashlib.sha256(plain).hexdigest()}]
    assert by_path["e.tab"]["plaintext_verified"] is False and by_path["e.tab"]["verified_against"] == []
    g = r["key_ids"][0]
    assert (g["decoded_plaintext_verified"], g["decoded_hypothesis_only"]) == (1, 1)
    assert (r["decoded_plaintext_verified"], r["decoded_hypothesis_only"]) == (1, 1)


def test_cancel_mid_decode_removes_derivatives_already_written(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "c.tab": keyed(plain), "e.tab": keyed(b"x" * 3_000_000)}
    passes = {"n": 0}
    base = entries_for(files)
    def entries():
        passes["n"] += 1
        yield from base()
    calls = {"n": 0}
    def check():
        if passes["n"] == 3:
            calls["n"] += 1
            if calls["n"] > 4:  # c.tab is written; cancel inside e.tab's stream
                raise ffs_ingest.IngestCancelled()
    with pytest.raises(ffs_ingest.IngestCancelled):
        TableRecovery([profile(k, v) for k, v in files.items()]).run(entries, tmp_path / "d", check)
    assert calls["n"] > 4 and list((tmp_path / "d").iterdir()) == []


def test_stale_derivatives_from_an_interrupted_run_are_removed(tmp_path):
    out = tmp_path / "decoded"
    out.mkdir()
    (out / ("f" * 64 + ".body")).write_bytes(b"orphan")
    (out / ("0" * 32 + ".tmp")).write_bytes(b"orphan")
    (out / "notes.txt").write_bytes(b"not ours")
    r = recover(tmp_path, {"a.tab": table(b"a" * 100), "b.tab": table(b"b" * 100, 7)})
    assert r["stale_derivatives_removed"] == 2
    assert [p.name for p in out.iterdir()] == ["notes.txt"]


def test_anomalous_members_of_a_solved_key_are_counted(tmp_path):
    plain = bytes(range(256)) * 2
    bad = bytearray(keyed(b"z" * 100))
    bad[30] = 1  # non-zero reserved byte
    r = recover(tmp_path, {"a.tab": table(plain), "c.tab": keyed(plain), "e.tab": bytes(bad)})
    g = r["key_ids"][0]
    assert g["solved"] and g["files"] == 2 and g["decoded_files"] == 1
    assert g["decode_gaps"] == {"decode_skipped_anomalous": 1}
    assert g["files"] == g["decoded_files"] + sum(g["decode_gaps"].values())
    assert r["gaps"] == {"decode_skipped_anomalous": 1}
    assert [d["path"] for d in r["decoded"]] == ["c.tab"]
    assert len(list((tmp_path / "decoded").iterdir())) == 1


def test_missing_member_of_a_solved_key_is_a_decode_gap(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "c.tab": keyed(plain), "e.tab": keyed(b"gone" * 30)}
    profiles = [profile(k, v) for k, v in files.items()]
    del files["e.tab"]
    r = recover(tmp_path, files, profiles)
    g = r["key_ids"][0]
    assert g["decode_gaps"] == {"decode_source_missing": 1}
    assert g["files"] == g["decoded_files"] + sum(g["decode_gaps"].values())
    assert r["integrity"]["changed"] == [{"path": "e.tab", "stage": "decode", "missing": True}]


def test_decode_refuses_a_source_whose_hash_changed(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "c.tab": keyed(plain), "e.tab": keyed(b"changed after indexing" * 4)}
    profiles = [profile(k, v) for k, v in files.items()]
    profiles[2]["sha256"] = "0" * 64  # e.tab is only re-read by the decode pass
    r = recover(tmp_path, files, profiles)
    assert [d["path"] for d in r["decoded"]] == ["c.tab"]
    assert r["key_ids"][0]["decode_gaps"] == {"decode_source_changed": 1}
    assert r["integrity"]["changed"] == [{"path": "e.tab", "stage": "decode"}]
    assert len(list((tmp_path / "decoded").iterdir())) == 1


def test_decode_helper_writes_nothing_on_hash_mismatch(tmp_path):
    raw = keyed(b"payload" * 20)
    group = {"model": "substitution", "cipher_to_plain": [KEY.index(b) for b in range(256)]}
    target = tmp_path / "out.body"
    good = profile("a.tab", raw)
    assert TableRecovery._decode(lambda: io.BytesIO(raw), good, group, target, lambda: None)["body_bytes"] == 140
    target.unlink()
    assert TableRecovery._decode(lambda: io.BytesIO(raw), {**good, "sha256": "0" * 64}, group, target,
                                 lambda: None) is None
    assert not list(tmp_path.iterdir())


def test_linked_derivative_directory_is_refused(tmp_path):
    plain = bytes(range(256)) * 2
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "decoded"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available to this user")
    with pytest.raises(PermissionError, match="Linked/reparse"):
        recover(tmp_path, {"a.tab": table(plain), "c.tab": keyed(plain)})
    assert not list(real.iterdir())


def test_reparse_point_derivative_directory_is_refused(tmp_path, monkeypatch):
    out = tmp_path / "decoded"
    out.mkdir()
    real = out.lstat()
    fake = type("Stat", (), {"st_mode": real.st_mode,
                             "st_file_attributes": tab_recovery.FILE_ATTRIBUTE_REPARSE_POINT})()
    monkeypatch.setattr(Path, "lstat", lambda self: fake if self == out else real)
    with pytest.raises(PermissionError, match="Linked/reparse"):
        TableRecovery._prepare_output(out, create=True)


@pytest.mark.parametrize("plain, paired", [
    (b"ID\tNAME VALUE TEXT 0123\n" * 8, True),  # 16+ symbols, so only the structure gate decides
    (b"ID NAME VALUE TEXT 0123, no tabs\n" * 8, False),
    (b"ID\tNAME VALUE TEXT 0123, no newline;" * 8, False),
])
def test_xor_reference_must_decode_to_tab_and_newline_text(tmp_path, plain, paired):
    files = {"ref/en_text.tab": bytes(b ^ 73 for b in plain), "make/en_text.tab": keyed(plain)}
    profiles = [profile(p, d, xor_key=73 if p.startswith("ref") else None) for p, d in files.items()]
    r = recover(tmp_path, files, profiles)
    assert bool(r["pairs"]) is paired
    assert r["gaps"] == ({} if paired else {"xor_not_tsv": 1})
    assert r["reference_files"] == int(paired)


def failing_opener(exc):
    def opener():
        raise exc
    return opener


def test_reread_distinguishes_changed_from_unreadable(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "c.tab": keyed(plain), "d.tab": table(plain[::-1]), "f.tab": keyed(plain[::-1])}
    profiles = [profile(k, v) for k, v in files.items()]
    profiles[2]["sha256"] = "0" * 64  # d.tab: bytes no longer match the index
    def entries():
        for path, raw in files.items():
            opener = failing_opener(OSError(5, "I/O error")) if path == "a.tab" else (lambda raw=raw: io.BytesIO(raw))
            yield path, len(raw), 0, opener
    r = TableRecovery(profiles).run(entries, tmp_path / "decoded", source_available=lambda: True)
    assert r["gaps"] == {"reference_unreadable": 1, "reference_changed": 1}
    assert r["integrity"]["changed"] == [{"path": "d.tab", "stage": "reference"}]
    assert r["integrity"]["unreadable"] == [{"path": "a.tab", "stage": "reference", "error": "OSError: [Errno 5] I/O error"}]


def test_read_surfaces_errors_and_detects_growth():
    raw = b"x" * 100
    with pytest.raises(MemberReadError):
        TableRecovery._read(failing_opener(OSError("gone")), profile("a", raw))
    assert TableRecovery._read(lambda: io.BytesIO(raw + b"y"), profile("a", raw)) is None
    assert TableRecovery._read(lambda: io.BytesIO(raw), profile("a", raw)) == raw


def test_vanished_source_reraises_for_resume(tmp_path):
    plain = bytes(range(256)) * 2
    files = {"a.tab": table(plain), "c.tab": keyed(plain)}
    def entries():
        for path, raw in files.items():
            yield path, len(raw), 0, failing_opener(FileNotFoundError(2, "No such file"))
    with pytest.raises(FileNotFoundError, match="No such file"):  # the member's own error, re-raised
        TableRecovery([profile(k, v) for k, v in files.items()]).run(
            entries, tmp_path / "decoded", source_available=lambda: False)
    # A vanished folder yields no entries at all: still an interruption, not an empty analysis.
    with pytest.raises(FileNotFoundError, match="no longer available during table recovery"):
        TableRecovery([profile(k, v) for k, v in files.items()]).run(
            lambda: iter(()), tmp_path / "decoded", source_available=lambda: False)


def test_full_substitution_pair_solves_without_false_conflict(tmp_path):
    plain = bytes(range(256)) * 2
    r = recover(tmp_path, {"a.tab": table(plain), "c.tab": keyed(plain)})
    assert r["key_ids"][0]["solved"] and not r["key_ids"][0]["conflicting_pairs"]


# ----- ingest level: cancellation, failures and re-read integrity during recovery ---------

def test_ingest_cancel_during_recovery_then_resume_completes(tmp_path, monkeypatch):
    folder = ingest_env(tmp_path, monkeypatch)
    plain = solvable_folder(folder)
    worker = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)])
    original = TableRecovery._decode
    def decode_then_cancel(*args):
        result = original(*args)
        worker.cancel_event.set()  # the owner cancels after the first derivative is written
        return result
    monkeypatch.setattr(TableRecovery, "_decode", staticmethod(decode_then_cancel))
    row = worker.run_sync()
    ident = row["id"]
    directory = store.directory(ident) / "index"
    assert row["status"] == "interrupted" and row["progress"]["phase"] == "cancelled"
    assert row["chain_of_custody"][-1]["event"] == "ingest_interrupted"
    assert custody(ident)["sessions"][-1]["outcome"] == "cancelled"
    assert custody(ident)["sessions"][-1]["ended_at"]
    assert not (directory / "tab_recovery.json").exists()
    assert list((directory / "decoded_tables").iterdir()) == []

    monkeypatch.setattr(TableRecovery, "_decode", staticmethod(original))
    row = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)], investigation_id=ident).run_sync()
    assert row["status"] == "completed", row.get("last_error")
    report = json.loads((directory / "tab_recovery.json").read_text())
    assert len(report["decoded"]) == 2 and report["stale_derivatives_removed"] == 0
    assert sorted(p.name for p in (directory / "decoded_tables").iterdir()) == sorted(
        d["derivative"] for d in report["decoded"])
    verified = next(d for d in report["decoded"] if d["path"] == "b_keyed.tab")
    assert (directory / "decoded_tables" / verified["derivative"]).read_bytes() == plain


def test_ingest_recovery_failure_closes_session_and_reraises(tmp_path, monkeypatch):
    folder = ingest_env(tmp_path, monkeypatch)
    solvable_folder(folder)
    def boom(self, *args, **kwargs):
        raise ValueError("unexpected recovery failure")
    monkeypatch.setattr(TableRecovery, "run", boom)
    worker = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)])
    with pytest.raises(ValueError, match="unexpected recovery failure"):
        worker.run_sync()
    row = store.load(worker.investigation_id)
    assert row["status"] == "interrupted"
    assert row["last_error"] == "Table recovery: ValueError: unexpected recovery failure"
    session = custody(row["id"])["sessions"][-1]
    assert session["outcome"] == "interrupted" and session["ended_at"]


def test_ingest_vanished_source_during_recovery_interrupts_and_resumes(tmp_path, monkeypatch):
    folder = ingest_env(tmp_path, monkeypatch)
    solvable_folder(folder)
    away = tmp_path / "unplugged"
    original = TableRecovery._read
    def unplug(opener, prof, check=lambda: None):
        folder.rename(away)
        return original(opener, prof, check)
    monkeypatch.setattr(TableRecovery, "_read", staticmethod(unplug))
    worker = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)])
    with pytest.raises(FileNotFoundError):
        worker.run_sync()
    ident = worker.investigation_id
    assert store.load(ident)["status"] == "interrupted"
    assert custody(ident)["sessions"][-1]["outcome"] == "interrupted"

    away.rename(folder)
    monkeypatch.setattr(TableRecovery, "_read", staticmethod(original))
    row = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)], investigation_id=ident).run_sync()
    assert row["status"] == "completed" and row["ffs"]["coverage"] == "complete"


@pytest.mark.parametrize("failure, unknown, unchanged", [
    ("changed", "no longer matched their index size/SHA-256 when re-read", False),
    ("unreadable", "could not be re-read for table recovery", True),
])
def test_ingest_reread_integrity_reaches_custody_and_coverage(tmp_path, monkeypatch, failure, unknown, unchanged):
    folder = ingest_env(tmp_path, monkeypatch)
    solvable_folder(folder)
    original = TableRecovery._read
    def reread(opener, prof, check=lambda: None):
        if prof["path"] != "a_plain.tab":
            return original(opener, prof, check)
        if failure == "unreadable":
            raise MemberReadError(OSError(5, "I/O error"))
        return None
    monkeypatch.setattr(TableRecovery, "_read", staticmethod(reread))
    row = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)]).run_sync()
    assert row["status"] == "completed"
    assert row["ffs"]["coverage"] == "partial"
    assert any(unknown in u and "a_plain.tab" in u for u in row["unknowns"])
    record = custody(row["id"])
    assert record["source_unchanged"] is unchanged
    assert record["recovery_reread"] == {"changed": int(failure == "changed"), "unreadable": int(failure == "unreadable")}
    directory = store.directory(row["id"])
    ingest_ev = next(e for e in row["evidence"] if e["operation"] == "ffs_ingest")
    result = json.loads((directory / "evidence" / f"{ingest_ev['id']}.json").read_text())["result"]
    assert result["source_unchanged"] is unchanged


def test_ingest_evidence_carries_per_file_verification(tmp_path, monkeypatch):
    folder = ingest_env(tmp_path, monkeypatch)
    solvable_folder(folder)
    row = ffs_ingest.FFSIngest(str(folder), allowed_directories=[str(tmp_path)]).run_sync()
    directory = store.directory(row["id"])
    ev = next(e for e in row["evidence"] if e["operation"] == "ffs_tab_recovery")
    result = json.loads((directory / "evidence" / f"{ev['id']}.json").read_text())["result"]
    assert {d["path"]: d["plaintext_verified"] for d in result["decoded"]} == {
        "b_keyed.tab": True, "c_extra0.tab": False}
    assert (result["decoded_plaintext_verified"], result["decoded_hypothesis_only"]) == (1, 1)
    assert result["integrity"] == {"changed": [], "unreadable": []}
