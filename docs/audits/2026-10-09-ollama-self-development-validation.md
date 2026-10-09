# RFC-0211 validation — 2026-10-09

## Delivered source

ANZU has a revision-bound RFC queue, recurring scheduler, owner chat tool and self-development page. Missions use registered development worktrees and a separate process running the existing ANZU tool/authorization/coding-verification loop. Text and image turns route to separate local Ollama models. An independent harness runs diff checks, pytest and frontend build/lint when relevant before returning `review_ready`; it does not merge or install candidates.

Repository intake reads accepted RFCs from the selected Git base, excluding dirty checkout edits. Drive intake supports explicit document snapshots and recurring refresh using configured MCP read-only search/fetch tools. Changed, deleted or unrefreshable sources revoke queue approval. Drive staging digests are not automatically executable tickets. The Drive jarvis_specs adoption digest and work-item-bound sessions proposal informed source identity, revision checks and serialized execution.

## Validation

- Focused scheduler/worktree/self-dev/coding-contract/MCP tests: 76 passed.
- Frontend TypeScript/Vite build: passed. Lint: exit 0 with existing repository warnings.
- `git diff --check`: passed.
- Headless rendered-page smoke: no JavaScript errors; priority reservation displayed; Run disabled while models are reserved. Screenshot retained outside the public repository.
- Full Windows pytest attempted: stopped after roughly six minutes without progress beyond approximately 5%. No full-suite pass is claimed.

## Local-model acceptance remains pending

Read-only Ollama metadata confirmed `anzu-coder-27b:latest` supports tools but not vision; `anzu-qwen-worker:latest` supports tools and vision. The first disposable calculator-repository smoke used the generic OpenAI-compatible transport and failed before any tool execution with an approximately 80-second model-call deadline. A native `/api/chat` adapter was then added with explicit `think: false`, native tools and image conversion. These controls follow [Ollama's official API documentation](https://github.com/ollama/ollama/blob/main/docs/api.md); protocol behavior is covered using a mock transport.

The second live smoke was stopped when the owner clarified that Grokbot was using Ollama and Antigravity for priority ANZU reverse-engineering tickets. Only our scheduler worker was stopped; the shared Ollama service and Antigravity sessions were not stopped or reconfigured. The disposable scheduler was paused with a priority reservation. No further live inference or vision requests were made.

Therefore actual native-Qwen edit/test completion, screenshot-to-vision action verification, installed-sidecar execution and continuous Drive refresh through a real ANZU connector are **not signed off**. The change is a draft for review, not a claim of working installed self-development. The scheduler remains opt-in and supports explicit resource holds so priority work can retain the local workers.
