# RFC-0164: Backup, restore, migration and device transfer

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Persistent personal AI state makes machine loss or migration costly. Ad-hoc copying risks broken DBs and leaked credentials.

## Decision
Add encrypted versioned backups of owner-selected Anzu data with consistency snapshots and manifest/checksums. Credentials are excluded by default and reconnected on restore; optionally export only through OS-supported secure transfer. Restore supports full, project/persona-selective and dry-run compatibility checks. Device transfer pairs old/new installations and streams encrypted backup material with explicit owner approval.

## Acceptance criteria
- [ ] Consistent backup manifest with version/schema/checksums.
- [ ] Encrypted local destination and pluggable owner-selected remote destination.
- [ ] Restore dry-run reports incompatible/missing modules/models.
- [ ] Selective restore does not overwrite unrelated current data.
- [ ] Backup/restore roundtrip is release-gated.

## Likely files
Storage migrations, backup service, Setup/Privacy UI, tests.
