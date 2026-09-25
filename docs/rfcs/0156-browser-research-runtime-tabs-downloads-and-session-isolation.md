# RFC-0156: Browser/Research runtime — tabs, downloads and session isolation

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Web research and transactional browser tasks need persistent tab/session state, safe downloads and evidence capture beyond stateless search calls.

## Decision
Create browser sessions with explicit profiles, tab IDs, navigation policy, download quarantine and screenshot/DOM evidence. Research sessions default read-only; transactional sessions require elevated policy for form submission, purchases, messages or account changes. Protect against prompt injection in pages by separating page data from system/tool instructions. Capture cited snapshots/URLs/timestamps into Evidence Graph. Login secrets are filled through credential broker, never exposed to the model.

## Acceptance criteria
- [ ] Persistent isolated browser sessions/tabs with bounded lifetime.
- [ ] Read-only research and transactional permissions are distinct.
- [ ] Page content cannot issue tool permissions/instructions.
- [ ] Downloads quarantine and scan before opening/tool ingestion.
- [ ] Evidence capture integrates with RFC-0143.
- [ ] Sensitive form/send/purchase actions require applicable approval.

## Likely files
Browser tools/runtime, credential broker, evidence service, computer-use runtime, tests.
