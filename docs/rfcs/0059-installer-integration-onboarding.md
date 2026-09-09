# RFC-0059: Installer integration onboarding

**Status:** accepted

**Queue item:** P1 — Installer integration onboarding for Gmail and WhatsApp

**Author:** Codex session

**Date:** 2026-09-08

## Problem

Jarvis currently exposes Gmail and WhatsApp through pinned MCP servers, but account setup depends on terminal-only third-party configuration programs. That is inappropriate for the Windows product experience: a normal user cannot tell what to enter, where credentials are stored, whether a connection worked, or how to recover from a failed WhatsApp pairing.

## Decision

Add a polished integrations step to the existing Jarvis first-run setup and make it available later from the MCP page. The Jarvis backend will own a small, explicit setup API: Gmail credentials are connection-tested and saved to the connector's user-profile config without returning the password, while WhatsApp pairing runs as a managed local helper that publishes the current QR payload and connection state. The React UI renders provider cards, progress, actionable errors, retry/cancel controls, and the WhatsApp QR in Jarvis. The Windows installer starts Jarvis directly on the integrations step after bootstrap. No terminal window is part of the user flow.

## Acceptance criteria

- [ ] The Windows installer can finish by opening Jarvis on the integrations setup step.
- [ ] Gmail setup asks for account name, email address, display name, and Google app password; it tests IMAP and SMTP before reporting success.
- [ ] Gmail secrets are stored only in the Windows user's connector config, are never returned by the API, and are never written to logs or Git.
- [ ] WhatsApp setup starts, retries, and cancels a managed pairing session and renders a scannable QR plus live `starting`, `pairing`, `connected`, `failed`, and `idle` states in the Jarvis UI.
- [ ] Successful setup ensures the pinned email and WhatsApp MCP presets are enabled in Jarvis settings.
- [ ] The same provider setup cards remain available from the MCP page after first run.
- [ ] Backend tests cover secret redaction, Gmail validation/config persistence, pairing state transitions, and process cleanup.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] `npm --prefix frontend run build` and `npm --prefix frontend run lint` pass.
- [ ] An existing installation gets a version-aware Upgrade or Repair choice, plus reinstall options that either preserve custom files or remove them after a separate destructive confirmation.
- [ ] Older installers are blocked from silently downgrading a newer Jarvis installation.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/api/integrations.py`, `backend/app/integrations/*`, `backend/app/main.py`, `backend/app/config.py` |
| Frontend | `frontend/src/pages/Setup.tsx`, `frontend/src/pages/Mcp.tsx`, `frontend/src/api.ts`, `frontend/src/styles.css` |
| Installer | `installer/windows/Jarvis.iss`, `installer/windows/bootstrap.ps1` |
| Connector bridge | `mcp/package.json`, `mcp/whatsapp-pairing.mjs` |
| Tests | `tests/test_integration_setup.py` |
| Docs | `docs/rfcs/0059-installer-integration-onboarding.md` |

## Out of scope

WhatsApp contact/chat allowlist editing, OAuth client registration, email inbox workflows, sending messages during setup, and changes to Jarvis model selection or swarm architecture.

## Notes

The live Gmail and WhatsApp sign-in checks require a Windows desktop and user-owned accounts. Automated tests use fakes and must not contact either provider.
