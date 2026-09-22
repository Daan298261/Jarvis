# RFC-0134: MCP usability and native-first tools

**Status:** implemented
**Queue item:** Owner-authorized: make configured MCPs actually usable; pin+adapter sidecars, not git-vendored trees
**Author:** desktop session
**Date:** 2026-09-22

## Problem

Configured MCP servers (Gmail/WhatsApp presets and custom stdio/http) did not reach the agent. Mixed/long-horizon exposure omitted MCP schemas unless the model already knew to `request_tools` with `mcp`. `mcp_call` was dispatched as `MCP.call("mcp_call")` because it starts with `mcp_`. Connections UI showed no refresh status or tool names. stdio launches used a CWD-relative `--prefix mcp`, so they failed when Jarvis ran from `%LOCALAPPDATA%`. Sessions were opened and closed on every list/call.

## Decision

- Persist MCP client sessions per server and reuse them for list/call; reconnect once on failure.
- Resolve stdio `cwd` to the repo root and rewrite `--prefix mcp` to an absolute `mcp/` path. Presets store that absolute prefix.
- Attach connected MCP tool schemas (plus `mcp_call`) whenever the turn has tools and servers have listed tools. Granting `mcp` adds `mcp_call` without dumping the full native catalog.
- Route `mcp_call` through the proxy tool. Direct `mcp_*` keys still call the runtime.
- Connections shows live status, tool names, Refresh, Obsidian vault, Supermemory, and optional workers. GET `/api/mcp` includes status; GET `/api/mcp/usability` is the hub snapshot.
- Keep python salvage and filesystem copy reroute. Do not git-vendor third-party trees or License Manager.

## Acceptance criteria

- [x] Mixed tasks attach connected `mcp_*` schemas and `mcp_call`
- [x] `REGISTRY.execute("mcp_call", …)` reaches `MCP.call` with the inner tool name
- [x] stdio prefix rewrite is absolute
- [x] Connections UI can refresh and show status/tools
- [x] Unit tests for exposure, proxy routing, salvage reroute
- [x] `python -m pytest` for the new tests (full suite as available)
- [ ] Live Gmail/WhatsApp stdio list/call — desktop sign-off (needs Node + owner credentials)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tools/mcp_runtime.py`, `registry.py`, `agent/tool_exposure.py`, `agent/tool_retrieval.py`, `api/mcp.py`, `api/integrations.py`, `integrations/setup.py` |
| Frontend | `frontend/src/pages/Mcp.tsx`, `frontend/src/components/IntegrationSetup.tsx`, `frontend/src/settings/IntegrationsSettingsPane.tsx` |
| Tests | `tests/test_mcp_usability.py`, `tests/conftest.py` |

## Out of scope

Vendoring ComfyUI, OpenViking, Firecrawl, Pipecat, LocalSend, RuView, or License Manager. Unpinned clone-at-runtime of those repos.

## Notes

Installer still pins `@codefuturist/email-mcp` and `wappmcp` in `mcp/package.json`. Desktop must have Node/npm and the connector `node_modules` for live email/WhatsApp MCP.
