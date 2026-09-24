# RFC-0165: Developer SDK, simulator and contract-test kit

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Anzu cannot outpace a broad ecosystem if every extension requires knowledge of internal implementation details.

## Decision
Publish a versioned developer SDK for Capability Packages, tools, personas, workflow nodes, channel/sensor adapters and model providers. Include local simulator with fake Anzu services, typed schemas, example packages, permission linter and contract tests. Generate API docs from schemas. Compatibility policy defines deprecation windows and manifest/runtime versions.

## Acceptance criteria
- [ ] Extension can be developed/tested without production user data.
- [ ] Contract tests cover lifecycle, permissions, tool I/O, health and uninstall.
- [ ] SDK versions map to runtime compatibility ranges.
- [ ] Examples cover minimal tool, provider, workflow node and UI panel.
- [ ] CI validates docs/examples against current SDK.

## Likely files
`sdk/`, schemas, simulator, docs site/content, CI tests.
