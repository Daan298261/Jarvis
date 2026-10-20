import os

from app.reverse_engineering.tab_analyzer import (
    TabProfiler,
    entropy_class,
    is_tab_path,
    profile_file,
    shannon_entropy,
    summarize,
)


def test_low_entropy_file(tmp_path):
    (tmp_path / "flat.tab").write_bytes(b"\x00" * 4096)
    entry = profile_file(tmp_path / "flat.tab")
    assert entry["size"] == 4096
    assert entry["entropy"] == 0.0
    assert entry["header_hex"] == "00" * 16


def test_high_entropy_file(tmp_path):
    (tmp_path / "enc.tab").write_bytes(os.urandom(256 * 1024))
    assert profile_file(tmp_path / "enc.tab")["entropy"] > 7.9


def test_streaming_profiler_matches_whole_file_profile(tmp_path):
    data = (b"ABCD" * 1000) + os.urandom(3000)
    (tmp_path / "x.tab").write_bytes(data)
    profiler = TabProfiler()
    for i in range(0, len(data), 333):  # odd chunking must not change the result
        profiler.update(data[i:i + 333])
    assert profiler.result() == profile_file(tmp_path / "x.tab")
    assert profiler.result()["header_hex"] == (b"ABCD" * 4).hex()


def test_tab_suffix_is_case_insensitive():
    assert is_tab_path("data/vehicles/BMW.TAB")
    assert is_tab_path("a.tab")
    assert not is_tab_path("notes.txt")
    assert not is_tab_path("table.tabx")


def test_two_symbol_entropy_is_one_bit():
    assert shannon_entropy([5, 5] + [0] * 254, 10) == 1.0


def test_empty_file(tmp_path):
    (tmp_path / "empty.tab").write_bytes(b"")
    entry = profile_file(tmp_path / "empty.tab")
    assert entry["size"] == 0 and entry["entropy"] == 0.0 and entry["header_hex"] == ""


def test_summary_classes_and_shared_header_prefixes():
    profiles = [
        {"path": "a.tab", "bytes": 100, "entropy": 7.99, "header_hex": "41555445" + "00" * 12},
        {"path": "b.tab", "bytes": 100, "entropy": 7.95, "header_hex": "41555445" + "11" * 12},
        {"path": "c.tab", "bytes": 100, "entropy": 3.2, "header_hex": "deadbeef" + "00" * 12},
        {"path": "d.tab", "bytes": 0, "entropy": 0.0, "header_hex": ""},
    ]
    summary = summarize(profiles)
    assert summary["file_count"] == 4 and summary["total_bytes"] == 300
    assert summary["entropy_classes"] == {"high": 2, "medium": 0, "low": 1, "empty": 1}
    assert summary["entropy_min"] == 3.2 and summary["entropy_max"] == 7.99
    assert summary["common_header_prefixes"]["4_bytes"][0] == {"prefix_hex": "41555445", "files": 2}
    assert entropy_class(6.5, 10) == "medium"