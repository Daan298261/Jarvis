import os

from app.reverse_engineering.tab_analyzer import (
    TabProfiler,
    entropy_class,
    is_tab_path,
    parse_tab_header,
    shannon_entropy,
    summarize,
)


def profile(data: bytes) -> dict:
    profiler = TabProfiler()
    profiler.update(data)
    return profiler.result()


def test_low_entropy_file():
    entry = profile(b"\x00" * 4096)
    assert entry["size"] == 4096
    assert entry["entropy"] == 0.0
    assert entry["header_hex"] == "00" * 16


def test_high_entropy_file():
    assert profile(os.urandom(256 * 1024))["entropy"] > 7.9


def test_streaming_profiler_matches_whole_file_profile():
    data = (b"ABCD" * 1000) + os.urandom(3000)
    profiler = TabProfiler()
    for i in range(0, len(data), 333):  # odd chunking must not change the result
        profiler.update(data[i:i + 333])
    assert profiler.result() == profile(data)
    assert profiler.result()["header_hex"] == (b"ABCD" * 4).hex()


def test_tab_suffix_is_case_insensitive():
    assert is_tab_path("data/vehicles/BMW.TAB")
    assert is_tab_path("a.tab")
    assert not is_tab_path("notes.txt")
    assert not is_tab_path("table.tabx")


def test_two_symbol_entropy_is_one_bit():
    assert shannon_entropy([5, 5] + [0] * 254, 10) == 1.0


def test_empty_file():
    entry = profile(b"")
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


# --- Autel AT\x00\x02 container + XOR-text census (docs/reverse-engineering/autel-tab-container.md) ---

# Real headers from the 2026-10 Autel MaxiSys dump (Root.zip).
KEYED_HEADER = bytes.fromhex("415400024e4c06010001000000000aa9300045589400010000") + b"\x00" * 39  # nl_FunctionText.tab, BAIC
PLAIN_HEADER = bytes.fromhex("415400020000060000020000000002980009111921290109")  # PubTab/gr_text_utf.tab
TSV = b"52\tAll\t1\t31\t20\t00\t00,00,1B\tN\tY\tY\tNA\t00,05,73\tY\tNA\r\n" * 40


def test_keyed_container_header_is_parsed():
    parsed = parse_tab_header(KEYED_HEADER)
    assert len(KEYED_HEADER) == 64
    assert parsed["container"] == "autel-at2"
    assert parsed["tag"] == "NL" and parsed["table_type"] == 6
    assert parsed["body_transform"] == "keyed" and parsed["header_len"] == 64
    assert parsed["format_rev"] == 1 and parsed["flags"] == 0
    assert parsed["record_count"] == 0x0AA9
    assert parsed["key_id"] == 0x94 and parsed["reserved_zero"] is True
    assert parsed["anomalies"] == []


def test_plain_container_header_has_16_byte_header_and_no_key():
    parsed = parse_tab_header(PLAIN_HEADER)
    assert parsed["body_transform"] == "plain" and parsed["header_len"] == 16
    assert parsed["tag"] is None and parsed["record_count"] == 0x0298
    assert parsed["key_id"] is None and parsed["anomalies"] == []


def test_short_or_foreign_headers():
    assert parse_tab_header(b"") == {"container": "empty"}
    assert parse_tab_header(b"AT\x00\x02\x00")["container"] == "truncated"
    assert parse_tab_header(b"PK\x03\x04" + b"\x00" * 60) == {"container": "unknown", "magic_hex": "504b0304"}
    # Indexes written before the parser kept only the 16-byte magic: parse what is there.
    legacy = parse_tab_header(KEYED_HEADER[:16])
    assert legacy["container"] == "autel-at2" and legacy["key_id"] is None and legacy["reserved_zero"] is None
    assert legacy["anomalies"] == []


def test_deviations_from_the_observed_layout_are_reported():
    bad = bytearray(KEYED_HEADER)
    bad[16:20] = b"XXXX"
    bad[40] = 1
    parsed = parse_tab_header(bytes(bad))
    assert parsed["reserved_zero"] is False
    assert any("descriptor" in a for a in parsed["anomalies"])
    assert any("reserved" in a for a in parsed["anomalies"])
    odd = bytearray(KEYED_HEADER)
    odd[7] = 0x59  # 13 files in the dump carry 0x59 here
    parsed = parse_tab_header(bytes(odd))
    assert parsed["body_transform"] is None and any("offset 7" in a for a in parsed["anomalies"])


def test_xor_text_key_is_recovered_from_the_histogram():
    for key in (0x09 ^ 0xD4, 0x9A, 0x21):
        profiler = TabProfiler()
        profiler.update(bytes(b ^ key for b in TSV))
        assert profiler.result()["xor_key"] == key
    for data in (TSV, os.urandom(64 * 1024), b"\x00" * 4096, b""):
        profiler = TabProfiler()
        profiler.update(data)
        assert profiler.result()["xor_key"] is None


def test_at2_files_skip_the_xor_test_and_capture_the_full_header():
    data = KEYED_HEADER + bytes(b ^ 0x5C for b in TSV)
    profiler = TabProfiler()
    for i in range(0, len(data), 7):  # header split across many chunks
        profiler.update(data[i:i + 7])
    result = profiler.result()
    assert result["container_hex"] == KEYED_HEADER.hex()
    assert result["header_hex"] == KEYED_HEADER[:16].hex()
    assert result["xor_key"] is None
    assert result["top_byte"] == 0x09 ^ 0x5C


def test_summary_container_census_groups_key_ids_and_xor_files():
    keyed = [
        {"path": f"k{i}.tab", "bytes": 500, "entropy": 6.5, "header_hex": KEYED_HEADER[:16].hex(),
         "container": parse_tab_header(KEYED_HEADER), "top_byte": 0x37 if i < 2 else 0x10}
        for i in range(3)
    ]
    other_key = bytearray(KEYED_HEADER)
    other_key[20] = 0x35
    profiles = keyed + [
        {"path": "b.tab", "bytes": 500, "entropy": 6.0, "header_hex": "",
         "container_hex": bytes(other_key).hex(), "top_byte": 0x14},
        {"path": "x.tab", "bytes": 900, "entropy": 4.0, "header_hex": "e7d4", "xor_key": 0xDD},
        {"path": "p.tab", "bytes": 40, "entropy": 3.0, "header_hex": PLAIN_HEADER[:16].hex()},
    ]
    census = summarize(profiles)["container_census"]
    assert census["containers"] == {"autel-at2": 5, "unknown": 1}
    at2 = census["at2"]
    assert at2["body_transform"] == {"keyed": 4, "plain": 1}
    assert at2["key_ids"][0] == {"key_id": 0x94, "files": 3, "dominant_top_byte": 0x37, "dominant_top_byte_files": 2}
    assert at2["key_ids"][1]["key_id"] == 0x35 and at2["key_ids"][1]["dominant_top_byte"] == 0x14
    assert {"tag": "NL", "files": 4} in at2["tags"]
    assert at2["anomalous_headers"] == 0
    assert census["single_byte_xor_text"] == {"files": 1, "keys": [{"xor_key": 0xDD, "files": 1}]}
