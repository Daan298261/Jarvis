# RFC-0180: Local model agentic reliability and owner workspace

**Status:** accepted
**Date:** 2026-09-26

## Problem

Local Qwen models need a verified tool-call contract with llama.cpp/Ollama. The current provider assumes OpenAI-typed tool arguments, the loop can accept a call outside the schemas offered on a turn, the existing agent suite route does not run the live model, and the owner workspace defaults exclude many normal profile paths.

## Decision

Keep ANZU as the task and tool authority. Probe the selected model with a harmless tool round trip, normalize provider tool-call payloads before the loop, limit small models to relevant tools and reject malformed or unoffered calls. Add a live benchmark runner with independently scored fixture outcomes. Include the signed-in user's home and mounted fixed Windows drives in local owner defaults; Windows UAC elevation remains separate and destructive operations still require confirmation.

## Acceptance

- Model page reports a real tool-call probe for the loaded model and explains failures.
- Tool arguments from local servers are normalized without granting new tools; invalid calls are rejected with actionable feedback.
- 9B profiles see a bounded set of task-relevant schemas and cannot execute an unoffered tool.
- Agent suite runs real ANZU tasks in prepared workspaces, records verified outcomes and metrics per profile.
- Local owner can use paths on mounted fixed drives by default, subject to OS account permissions; explicit configured roots and destructive approval still work.
- Focused and full backend tests pass; frontend build and lint pass. Live GPU benchmark results are reported only when a model server is actually available.
