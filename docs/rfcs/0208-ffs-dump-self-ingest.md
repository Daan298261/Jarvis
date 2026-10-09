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

- [ ] Folder, zip and tar dumps index path/size/SHA-256/mtime/magic for every file.
- [ ] A raw image with no container is indexed as a blob with a declared unknown.
- [ ] Ingest never copies the source and leaves source bytes/mtimes unchanged.
- [ ] Interrupted ingest resumes without duplicating or dropping entries.
- [ ] Progress and completion are visible through the investigation status API.
- [ ] Completion writes chain-of-custody and a citable evidence record.
- [ ] RE/REA/forensic pytest suites plus new FFS tests pass; diff is clean.

## Out of scope

Deep filesystem parsing of raw images (Sleuth Kit integration), `.tab` decryption and
the 0x22 DID table writeup (later analyzer slices), promotion to main, and any change to
`store.prepare`'s bounded single-artifact path.

## Notes

The `.tab` entropy/header analyzer (RFC-0208 companion, branch re/ffs-analyzers)
consumes the NDJSON index records and reads file bytes read-only; it is independent of
this ingest module and integrates at report time.