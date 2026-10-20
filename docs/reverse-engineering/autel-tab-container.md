# Autel `.tab` container (`AT\x00\x02`): format writeup

Status: working notes (RE Phase 2 analyzer slice, RFC-0208 companion). Every field
name below comes from the 2026-10 Autel MaxiSys dump, not from vendor documentation.
Anything marked *hypothesis* has not been confirmed by decoding a body.

Source: `D:\AUTEL MAXISYS\Root.zip` (20.7 GB, ingested in PR #651, manifest
`0eee174c…139eb`). Read-only `zipfile` streaming of the members on VRPC, 2026-10-20.
The census scripts read only the first 64 bytes of each member, except where a sample
is stated.

## 1. Population

| `.tab` members | Count |
|---|---|
| Total | 279,170 |
| Empty (0 bytes, mostly `*.DELETED.tab` logs) | 2,993 |
| `AT\x00\x02` container | **267,467** |
| Other (no container magic) | 8,710 |

Every container file sits under `media/0/Scan/` (vehicle software). This includes
copies inside the downloaded update zips under `Scan/Download/…`.

## 2. Header layout

All offsets are hex and multi-byte integers are big-endian. Byte 7 selects one of two
header lengths.

```
00  41 54 00 02        magic "AT\0\2"                       267,467 / 267,467
04  tt tt              tag: 00 00, or 2 ASCII chars          264,413 none / 3,054 tagged
06  ty                 table type                            see table below
07  tr                 body transform: 01 keyed, 00 plain    267,355 / 98  (+14 anomalous)
08  rr rr              format revision (u16)                 0001 148,224 · 0002 116,089 · 0008 2,540 · 0005 548 · 0006 53 · 0004 13
0A  fl                 flags                                 00 252,924 · 10 12,983 · 01 1,305 · 23 180 · 50 50 · 60 13 · 15 12
0B  ??                 field_11 (always 00 in samples)
0C  nn nn nn nn        record count (u32)                    see §4
--- byte 07 == 00 (plain): header ends, records start at 0x10
--- byte 07 == 01 (keyed): descriptor follows
10  30 00 45 58        descriptor "0\0EX"                    267,355 / 267,355
14  kk                 key id                                49 distinct values, see §3
15  00 01              descriptor tail                       267,355 / 267,355
17  00 × 41            reserved, zero                        267,355 / 267,355
40  body
```

**Tag (04–05).** When it is set, the tag repeats the file-name prefix:

- the language for text tables, for example `NL` in `nl_FunctionText.tab` and `EN` in `en_text.tab`;
- the module family for module tables, for example `AC` in `AC_CAN_….tab`, `GW` in `GW_….tab` and `DS` in Volvo `Ds_….tab`.

The most common tags are GW 584, AC 533, EN 381, AT 325, NL 272, EV 120, DS 92, 16 83 and IC 79.

**Table type (06).**

| Type | Files | Examples |
|---|---|---|
| 0x04 | 106,311 | `Diagnosis/Script/script_*.tab` |
| 0x06 | 102,356 | `Module/*/<SYS>_*_CAN_*.tab`, `*_text.tab`, `Ds_*_Info.tab` |
| 0x05 | 35,251 | `ASAM/odx_x/E0xx.tab`, `nl_DataStream.tab`, `nl_Menu.tab` |
| 0x08 | 11,296 | `ACT_MODE.tab`, `Amtag*.tab`, `ktt_vehicle.tab` |
| 0x03 | 10,635 | `ASAM/DataStream`, `ECUInfo` and `Menu` tables |
| 0x02 | 720 | Honda `tool_*.tab`, `ecuid2Name_ALL.tab` |
| 0x07 | 662 | `Hino_PID.tab`, Peugeot `MenuFlowLibs/*_MENU.tab` |
| 0x0A | 117 | GM `Amtag000*.tab` |
| 0x01 | 108 | |
| 0x09, 0x0B, 0x0C | 8, 2, 1 | |

*Hypothesis:* the type is the column or record schema id. The ratio of bytes to records
varies a lot within a type, which fits variable-length cells.

**Plain bodies (byte 07 = 00, 98 files).** These are the `Scan/PubTab/*` language tables,
for example `gr_text_utf.tab`, `my_text.tab` and `cn_bms.tab`. The structured
low-entropy records start directly at 0x10. They use the same container without the
keyed transform, so they are the natural known-plaintext corpus.

**Anomalous byte 07.** Fourteen files carry `0x59` (13 files) or `0x69` (1 file).
The parser flags them in `anomalies` and does not guess a header length.

## 3. Key id (byte 0x14) is per manufacturer

Each of the 49 key ids maps to one vehicle make, or to one platform family. The largest groups are below. The full list is in the census output.

| Key id | Files | Vehicle software dirs |
|---|---|---|
| 0xE9 (233) | 87,187 | Peugeot (87,177), Opel (10) |
| 0x35 (53) | 59,255 | Benz, Benz_Sprinter, Fawcar, Fuso (the Daimler-platform set) |
| 0x9F (159) | 15,406 | BYD |
| 0x76 (118) | 14,308 | Hyundai, Daily |
| 0xB0 (176) | 13,644 | VW |
| 0xC4 (196) | 11,829 | Renault |
| 0x94 (148) | 7,198 | BAICMotor |
| 0xEC (236) | 6,542 | ChangAn |
| 0x0F (15) | 6,443 | LandRover |
| 0x93 (147) | 6,426 | Nissan |
| 0xA8 (168) | 1,475 | Volvo |
| 0xA2 (162) | 1,224 | GM |

## 4. What the keyed body is, and is not

These measurements come from samples of keyed bodies, from offset 0x40 to the end of the file:

- **Not a 16-byte block cipher.** The body length minus 64, mod 16, is spread evenly over 0–15 (2,898 files). Duplicate 16-byte blocks are equally common at alignment shifts 0, 4 and 8: 123,822, 123,560 and 123,849 duplicates over 579 files. ECB or CBC would need aligned lengths. ECB would repeat only on aligned blocks, and CBC or CTR would not repeat at all.
- **Not a position-dependent keystream.** The index of coincidence has a median of 0.0095. Uniform ciphertext would be 0.0039. The autocorrelation peaks at record-like lags (72, 36, 63, 3, 10, …) in 467 of 579 files, so the record structure survives the transform.
- **Keyed by byte 0x14.** The most common body byte (counted from offset 0x40, so the mostly-zero header is excluded) is stable within a key id and differs between key ids:
  - 0xE9 gives 0x37 in 1,046 of 1,380 sampled files.
  - 0xB0 gives 0x21 in 182 of 196.
  - 0x35 gives 0x14 or 0x2D.
  - 0x9F gives 0x3B.
  - Several smaller key ids give 0x00.
- **Entropy.** The median per type is 6.3 to 7.9 bits/byte. Text tables run highest (type 0x06 has a median of 7.92), which is consistent with a substituted alphabet over UTF-8 text.
- **Record count.** Bytes 0C–0F are non-zero in all sampled keyed files. The ratio of bytes to count is plausible for rows, with a median of 36 to 564 bytes depending on type. For example, `ACT_MODE.tab` (20.9 MB) has 44,515 records.

*Hypothesis (to confirm by decoding):* the body is a **position-independent byte
substitution selected by the key id**. It could be a 256-entry table, or a bit
permutation plus XOR. Peugeot script bodies show nibble-regular sequences: second
bytes `e2 fa f2 0a 02 1a …` in consecutive 8-byte records, which looks like a counter
under a fixed bijection.

## 5. Files without the container (8,710)

| Family | Files | Finding |
|---|---|---|
| Single-byte XOR over tab-separated text | 1,207 (1.48 GB) | 244 distinct keys, one key per file. TATA 409, GM 142, Mazda `tool_j*`/`tool_r*` 63, Ford 57, Saab 56, Subaru 46, Foton 44, … For example, TATA `live_data/0x07_2.tab` XOR 0xAC decodes to `59\t342\t25\t2\t1\t00,11,68…`. |
| Mazda `tool_b1/<12-char>.tab` | 2,718 | Unidentified scheme with nibble-structured bytes. Not single-byte XOR. |
| Ford | 2,710 | Unidentified |
| LandRover | 1,793 | Unidentified |
| VW, others | ~300 | Unidentified |

The XOR detector scores each of the 256 keys against the streaming byte histogram:
the share of bytes that decode to likely-text characters, with digits and whitespace as a
tie-breaker. It reports a key only when that share is at least 90%, the file is not
already text, and it has at least 8 distinct bytes. It is a **candidate**: some hits,
such as `Saab/1998_AutoComm`, decode to letters without obvious words, which suggests
a second layer or another alphabet.

## 6. How ANZU uses this

`backend/app/reverse_engineering/tab_analyzer.py`:

- `TabProfiler` keeps the first 64 bytes of every `.tab` member during the ingest pass. It also keeps `top_byte`, the most common byte of the body, and a candidate single-byte XOR key, which applies only to files without the container. For AT2 members the header (`AT2_TRANSFORMED_HEADER_LEN` = 64 bytes when keyed, `AT2_PLAIN_HEADER_LEN` = 16 otherwise) is subtracted from the histogram, so the ~48 zero header bytes of a keyed file cannot outvote a short body. A member with no body after its header has no `top_byte`. Files without the container have no header to drop, so their `top_byte` covers the whole file.
- `parse_tab_header(raw, size)` decodes the layout above. It returns `container` (`autel-at2`, `unknown`, `empty` or `truncated`), every field, and `anomalies` for any deviation from the observed layout. Those include a descriptor or tail mismatch, non-zero reserved bytes, an unknown byte 07, a non-ASCII tag, and a keyed member whose real `size` is shorter than the 64-byte keyed header. The ingest passes the member size, because the captured bytes alone cannot tell a short member from a short capture; a legacy 16-byte index entry of a full-size member is therefore not flagged.
- `summarize(...)["container_census"]` aggregates:
  - container kinds;
  - AT2 transforms, table types, tags and record totals;
  - key-id groups with their dominant body byte (the most common `top_byte`, which excludes the header);
  - XOR-text candidates.

`ffs_ingest.py` writes `tab_header_hex`, `top_byte` and `xor_key` on `.tab` index lines.
Each row of `index/tab_profile.json` and of the `ffs_tab_profile` evidence carries the
parsed `container`, and the evidence summary carries `container_census`. Indexes written
before this change hold only the 16-byte magic. For those, the parser reports everything
except the key id and reserved range, and it does not guess them.

## 7. Next steps

1. **Known-plaintext table recovery per key id.** Pair the plain PubTab tables (byte 07 = 00) and the single-byte-XOR TSV families with keyed tables that carry the same content. Candidates are the same language table under different makes, and the `*_text.tab` sets. Then check whether each key id is a bijection: 256 distinct outputs, and the same mapping across files.
2. **Locate the decoder in the Autel APK.** Use the RFC-0207 apk sidecar and search the native libraries for the `30 00 45 58` descriptor constant and the `AT\0\2` magic. The decoder is the authoritative source for the field names in §2.
3. Explain the 14 files with byte 07 = 0x59 or 0x69, and the byte 0x0A flag values.
4. Characterise the Mazda `tool_b1`, Ford and LandRover families.
