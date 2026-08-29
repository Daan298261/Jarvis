# RFC-0017: MCP 2026-07-28 protocol upgrade

**Status:** accepted  
**Queue item:** MCP interoperability / long-running tools  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-29

## Problem

Jarvis currently supports user-configured MCP servers through stdio and HTTP/streamable-http and exposes them through `mcp_call`, but the MCP 2026-07-28 specification materially changes the protocol model and adds production features Jarvis does not explicitly support: a stateless core, Multi Round-Trip Requests, header-based routing, cacheable list results, Tasks for long-running work, MCP Apps for server-rendered UI, and hardened OAuth/OIDC authorization.

Without an explicit compatibility layer, Jarvis risks remaining tied to older MCP assumptions and missing standardized long-running task and UI capabilities that would otherwise require bespoke Jarvis protocols.

## Decision

Upgrade Jarvis MCP support around a version-aware client/runtime abstraction targeting MCP `2026-07-28` while preserving compatibility with older configured servers where practical.

Adopt Tasks as the preferred standardized mechanism for MCP work that outlives a single request. Support MCP Apps as sandboxed/permission-scoped UI surfaces rather than granting them unrestricted portal access. Implement cache-aware tool/resource discovery, method-header routing where applicable, and OAuth/OIDC authorization flows for remote MCP servers.

Do not let MCP Tasks bypass Jarvis policy, budgets, audit, or GoalRun lifecycle. Jarvis remains the authority layer around MCP.

## Acceptance criteria

- [ ] MCP server configuration records negotiated/supported protocol version and capabilities.
- [ ] Client supports the MCP `2026-07-28` stateless request model and Multi Round-Trip Requests for compatible servers.
- [ ] HTTP transport supports protocol-required method/header routing and handles cache metadata/TTL for list operations.
- [ ] Jarvis can create, inspect, resume/poll, cancel, and consume results from MCP Tasks without holding one model turn open.
- [ ] MCP Task execution is linked to Jarvis task/GoalRun identity, policy, budget, provenance, and cancellation.
- [ ] MCP Apps render only in a sandboxed, explicitly permissioned UI container with origin/content restrictions and no implicit access to Jarvis secrets or unrelated state.
- [ ] Remote MCP authorization supports standards-aligned OAuth 2.0/OIDC flows without storing access tokens in plain settings files.
- [ ] Existing stdio and compatible legacy MCP configurations continue to function or produce a clear migration warning.
- [ ] Server capability/list discovery is cached only according to protocol metadata and invalidated safely on configuration/version changes.
- [ ] Tests cover version negotiation, stateless requests, MRTR, Task lifecycle/cancellation, auth failure/refresh, cache invalidation, and legacy fallback.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tools/...` MCP client/registry, MCP settings/schemas, task runtime integration |
| Security | credential/token store, OAuth/OIDC callback/session handling |
| Frontend | MCP server configuration, Task status, sandboxed MCP App host |
| Tests | MCP protocol/version/task/auth compatibility tests |
| Docs | MCP configuration and compatibility matrix |

## Out of scope

Replacing Jarvis native tools with MCP, exposing Jarvis itself as a full MCP server, or allowing MCP Apps to become unrestricted plugin code.

## Notes

Source: https://blog.modelcontextprotocol.io/posts/2026-07-28/ — final MCP 2026-07-28 specification. Related release-candidate detail: https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/

Discovery date: 2026-08-29. Recommendation: **ADAPT STRONGLY**. Jarvis already has MCP transport support, so the right move is an interoperability upgrade that maps standardized MCP Tasks/Apps/auth into Jarvis's own policy and lifecycle model rather than duplicating those features with proprietary protocols.
