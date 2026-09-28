# Release 1.4.16 — merged attestation

Combines **1.4.15** (RFC-0181 owner drive roots, LAN access defaults) with **UX/voice hotfix** work.

## Automated

- `python -m pytest tests/test_front_responder.py tests/test_planning_tool_route.py`
- `npm --prefix frontend run build`

## Owner verification (Windows)

- [ ] Start Jarvis opens browser on `:4780`; LAN URLs work with private key when enabled
- [ ] HUD Persona/Voice/Appearance/Cybersecurity menus expand in table rows (no overlap)
- [ ] Chat: named persona (Anzu) left, user right, timestamps on task threads
- [ ] Voice lane: >128 token replies; long input; “run … tool” starts harness task
- [ ] RFC-0181: mounted drives + LAN behavior from 1.4.15 still holds
- [ ] Optional `-Desktop` / Obsidian embed unchanged

## Package

Build on Windows: `.\installer\windows\build-installer.ps1 -Release` → `Releases\r1.4.16\` + `installer\windows\dist\`
