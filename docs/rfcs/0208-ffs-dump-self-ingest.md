# RFC-0208: ANZU FFS Dump Self-Ingest (Phase 2)

**Status:** accepted
**Author:** Grok Bot (supervisor) / Daan
**Date:** 2026-10-09

## Problem

Phase 1 (RFC-0201) investigates a single bounded artifact that is copied into the
investigation workspace (`store.prepare` enforces an 8 GiB / 50k-file cap). Full
file-system (FFS) extractions of seized devices (e.g. an Autel MS906BT diagnostic
tablet, ~60 GB) exceed those caps and must not be copied: the source is evidence and
stays read-only in place. ANZU must ingest such a dump, build a verifiable file index
with chain-of-custody, and expose it to the existing investigation path so later
analyzers (`.tab` encryption review, DID tables) and reports can cite it.

## Decision

Extend the existing REA path with a dedicated, non-copying FFS ingest lane. Do not
change `store.prepare`'s bounded single-artifact behavior.

- New investigation `kind == "ffs"` prepared by `store.prepare_ffs`. The original
  dump path is referenced read-only as the snapshot; nothing is copied.
- Accepted sources: an extracted folder, a `.tar`/`.tar.*` archive, a `.zip`
  archive, or a raw image file. Folder/zip/tar entries are enumerated and streamed;
  a raw image with no supported container is indexed as a single whole-image blob and
  records an explicit unknown ("filesystem enumeration requires Sleuth Kit; not yet
  provisioned") rather than guessing — preserving incomplete coverage per RFC-0201.
- Streaming only: every file/entry is hashed in 1 MiB blocks; the dump is never loaded
  into RAM. The source is opened read-only and never modified.
- Index: append-only NDJSON at `<investigation>/index/files.ndjson`. Each line is
  `{path, bytes, sha256, mtime, magic_hex, type}` (`magic_hex` = first 16 bytes).
- Chain-of-custody: `<investigation>/index/custody.json` records the source, source
  kind, owning task, ISO-timestamped ingest sessions (for resume), tool version, and
  the finalized manifest digest (`source_sha256`) once ingest completes.
- Resumable: ingest counts entries already present in the index and continues from
  there in a deterministic order, so a 60 GB run survives interruption.
- Progress is written onto the investigation row (`row["ffs"]`: status,
  files_indexed, bytes_indexed, last_path, updated_at, unknowns) and surfaced through
  the existing `GET /api/investigations/{id}` and list endpoints. On completion an
  evidence record is written so findings can cite the index.
- API: `POST /api/investigations/ffs` prepares; `POST /api/investigations/{id}/ingest`
  starts/resumes a background ingest; status is read through the existing detail endpoint.

## Acceptance criteria

- [x] Folder, zip and tar dumps index path/size/SHA-256/mtime/magic for every file.
- [x] A raw image with no container is indexed as a blob with a declared unknown.
- [x] Ingest never copies the source and leaves source bytes/mtimes unchanged.
- [x] Interrupted ingest resumes without duplicating or dropping entries.
- [x] Progress and completion are visible through the investigation status API.
- [x] Completion writes chain-of-custody and a citable evidence record.
- [x] RE/REA/forensic pytest suites plus new FFS tests pass; diff is clean.

## Implementation (conformance pass, 2026-10-20)

The first implementation (#582/#583) diverged from this RFC: rows were `kind == "forensic"`,
the whole index was rewritten into one `checkpoint.json` after every file (quadratic on a
60 GB dump) and inlined into the evidence record, and nothing wrote `index/files.ndjson`,
so the RFC-0207 slice 4 FFS origin (which requires `kind == "ffs"` and that index) could not
consume a real ingest. The `.tab` profiler had no caller. The conformance pass:

- `backend/app/reverse_engineering/ffs_ingest.py`: rows are `kind == "ffs"`, prepared by
  `store.prepare_ffs`, which references the dump in place as the read-only snapshot
  (`target` and `snapshot` are both the dump path; nothing is copied, and `public_row` in
  `backend/app/api/investigations.py` keeps `snapshot` out of API responses). Members are
  yielded lazily (resume skips without reading) in a deterministic order and streamed once in
  1 MiB blocks (`ffs_ingest.CHUNK_SIZE = 1024 * 1024`, the default for `_digest` and
  `file_sha256`; `HEADER_MAX_BYTES` = 64 KiB is only the magic-detection window). Each
  member appends one line `{path, bytes, sha256, mtime, magic_hex, type}` to `index/files.ndjson` (flushed per line,
  fsynced at checkpoints every 256 files or 5 s). Resume re-reads the NDJSON, drops a torn
  final line and fails closed on corruption elsewhere. `index/custody.json` records source,
  source kind, task, tool version, admission stat and every session; completion seals the
  manifest digest (`source_sha256` = SHA-256 of the finished index) and re-checks the source
  stat. `row["ffs"]` carries status, files/bytes indexed, last path, totals, unknowns and
  coverage; `row["progress"]` mirrors it with a percent where totals are knowable.
- Declared unknowns instead of silent gaps: raw images (Sleuth Kit not provisioned),
  unreadable members (indexed with `error`, no SHA-256), duplicate archive member names,
  links/reparse points, special files and unsafe archive names.
- Evidence: `ffs_ingest` (index summary, manifest digest, type histogram, unknowns; never
  the inlined index) and `ffs_tab_profile` (derived from it).
- `.tab` profiling (`tab_analyzer.py`) runs inside the same pass: `.tab` lines carry
  `entropy`; `index/tab_profile.json` holds every profile plus entropy classes and shared
  header prefixes; `ffs_tab_profile` inlines up to 2,000 rows.
- Stopping: every stop path signals the ingest thread (`ffs_ingest.cancel`), which stops at the
  next block, abandons the in-flight member and checkpoints (`FFSIngest._interrupt`). The
  owner's close/cancel is final: `runtime.Investigations.close` and `release_task(...,
  cancelled=True)` set the terminal status (`store.TERMINAL_STATUSES` = closed/cancelled) and
  wait up to `runtime.FFS_STOP_WAIT_SECONDS` for the thread; `store.save_guarded` never lets the
  thread downgrade it, and both `store.prepare_ffs` and `FFSIngest.run_sync` refuse to start or
  resume a closed/cancelled investigation. Shutdown (`Investigations.shutdown`), a task
  release without cancel, `stop_after`, a vanished source and unexpected errors leave the row
  `interrupted` (errors also record `last_error`) and resumable. A second concurrent ingest of
  the same investigation is refused (`RuntimeError`, HTTP 409).
- Reachability (`backend/app/api/investigations.py`): `POST /api/investigations/ffs`
  (`prepare_ffs`, prepares the row; start with `POST /{id}/ingest`), `POST /{id}/ingest`
  (`ingest_into_investigation`, runs in the background unless `background: false`),
  `POST /api/investigations/ingest` (`ingest`, prepare and run in one call; runs to completion
  unless `background: true`), `GET /{id}/ffs/files` (path/suffix/type filters, paged) and
  `GET /{id}/ffs/tab-profile`; agent tool `reverse_engineer` actions `ingest` (background by
  default, `options.background`), `ingest_status` and `ffs_query`; FFS catalog workflow and
  skill guide. Background runs are the investigation's active work
  (`Investigations.ingest(background=True)`), so close/cancel/shutdown reach them.
- Tests (`tests/test_ffs_ingest.py`, `tests/test_tab_analyzer.py`) include an end-to-end
  folder ingest feeding `apk_sidecar.prepare_apk(source_type="ffs")`, torn-line resume,
  stop-and-resume, final close/cancel (including a close before the thread starts), the
  read-only snapshot reference, unreadable and duplicate members, API and agent-tool paths.
  Validated on the real Autel MaxiSys `Root.zip` (see the PR for numbers).

## Out of scope

Deep filesystem parsing of raw images (Sleuth Kit integration), `.tab` decryption and
the 0x22 DID table writeup (later analyzer slices), promotion to main, and any change to
`store.prepare`'s bounded single-artifact path.

## Notes

The `.tab` entropy/header analyzer (RFC-0208 companion, branch re/ffs-analyzers)
consumes the NDJSON index records and reads file bytes read-only; it is independent of
this ingest module and integrates at report time.