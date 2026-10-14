import os

from app.reverse_engineering.tab_analyzer import analyze_tab_files, shannon_entropy


def test_low_entropy_file(tmp_path):
    (tmp_path / "flat.tab").write_bytes(b"\x00" * 4096)
    [entry] = analyze_tab_files(tmp_path)
    assert entry["relative_path"] == "flat.tab"
    assert entry["size"] == 4096
    assert entry["entropy"] == 0.0
    assert entry["header_hex"] == "00" * 16


def test_high_entropy_file(tmp_path):
    (tmp_path / "enc.tab").write_bytes(os.urandom(256 * 1024))
    [entry] = analyze_tab_files(tmp_path)
    assert entry["entropy"] > 7.9


def test_ignores_non_tab_and_recurses(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"hello")
    sub = tmp_path / "data" / "vehicles"
    sub.mkdir(parents=True)
    (sub / "BMW.TAB").write_bytes(b"ABCD" * 10)
    results = analyze_tab_files(tmp_path)
    assert [r["relative_path"] for r in results] == ["data/vehicles/BMW.TAB"]
    assert results[0]["header_hex"] == (b"ABCD" * 4).hex()


def test_two_symbol_entropy_is_one_bit():
    assert shannon_entropy([5, 5] + [0] * 254, 10) == 1.0


def test_empty_file(tmp_path):
    (tmp_path / "empty.tab").write_bytes(b"")
    [entry] = analyze_tab_files(tmp_path)
    assert entry["size"] == 0 and entry["entropy"] == 0.0 and entry["header_hex"] == ""
