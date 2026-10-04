# RFC-0196: Native ANZU manager and friendly local address

**Status:** accepted  
**Queue item:** none — user-promoted installer and local-control capability  
**Author:** Codex  
**Date:** 2026-10-05

## Problem

ANZU currently opens its browser portal directly and has no independent local control surface when the core backend is stopped.

## Decision

Ship a loopback-only manager service on port 4782 plus a native tray shell. The core and manager web endpoints remain local fallbacks; the native windows are the normal entry points. The installer can add a managed `anzu` hosts alias for convenience.

## Acceptance criteria

- [ ] Manager status and start/stop/restart controls work without importing the core app lifecycle.
- [ ] Closing the manager window hides it; explicit Quit Manager terminates only the manager.
- [ ] Installer hosts handling is marked, idempotent, elevated, and uninstall-safe.
- [ ] All installer choices except the 27B model are selected by default.
- [ ] Focused tests, backend tests, and frontend build pass.

## Out of scope

Remote node registration/control, LAN/WAN manager exposure, and a Windows Service running before user logon.
