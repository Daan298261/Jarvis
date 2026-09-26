# RFC-0181: Owner drive and LAN access hotfix

**Status:** accepted
**Date:** 2026-09-26

## Problem

RFC-0180 is merged on development but absent from the installed 1.4.14 build and main. Its default scope covers fixed drive letters only. Steam under Program Files is denied by the current installed build, while removable drives, mapped drives, and local SMB shares remain outside the intended owner workspace.

## Decision

The local owner gets every mounted, scannable Windows drive root by default, plus UNC shares on the private LAN. Preserve explicit per-path restrictions in tests, OS account ACLs, explicit denied permissions, and destructive-action approval. Local HTTP and browser access is available by default. Promote the hotfix through development and main, then package version 1.4.15 with the model downloaded at install and retain the newest three Drive release runs.

## Acceptance criteria

- The live-install gap is identified and the new Windows installer includes the scope change.
- Steam under Program Files and mounted fixed, removable, and mapped drives resolve within the owner scope.
- Private LAN UNC shares resolve; public UNC hosts and explicitly narrow allowlists remain denied.
- Local-network tool permission defaults to allow, while explicit deny still wins.
- Focused tests, repository CI, frontend build, Windows installer, Android APK, and release artifact hashes are checked.
- The new release is on main and its Drive folder contains the paired installer files, companion APK, owner license, vendor manager, notes, and checksums; only the newest three release runs remain.

## Likely files

`backend/app/config.py`, `backend/app/tools/safety.py`, `backend/app/policy/computer_permissions.py`, focused tests, version files, and release outputs outside Git.
