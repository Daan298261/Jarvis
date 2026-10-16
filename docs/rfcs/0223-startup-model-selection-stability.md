# RFC-0223: Startup and saved model selection stability

**Status:** accepted
**Date:** 2026-10-16

## Problem

The owner reports slow startup, lost model selections, unreliable autoload and unstable UI switching. External model offers interrupt the workspace, runtime activation omits custom GGUF persistence, and repeated remote loads do unnecessary work.

## Decision

Preserve the exact successful runtime selection including custom GGUF and context. Reuse only matching endpoint/model/configuration; honor forced reloads. Restore the saved selection at startup without rewriting it during temporary fallback. External discovery remains informational and never stops another application's server automatically. Move blocking hardware and persona preparation off the event loop. Lazy-load secondary pages with a local loading/error boundary that keeps navigation available. Prevent stale discovery polling from replacing a successful choice.

Settings saves merge the writer's changed fields into the latest file under a write lock. The inference section stays an atomic selection so concurrent model switches cannot mix endpoints and weights; unrelated appearance/persona saves cannot reset that selection.

## Acceptance criteria

- Saved built-in and custom model choices survive restart and temporary fallback.
- Identical remote loads reuse the provider; endpoint/model changes and force reload do not.
- Discovery cannot indefinitely prevent configured autoload or present downloaded Ollama models as loaded when native inventory is unavailable.
- Startup hardware/persona probes do not block API requests.
- Secondary page code loads on demand; failed chunks expose retry while navigation stays usable.
- Focused regression tests, frontend build/lint, and a Windows build are checked; live acceptance limitations are recorded separately.

## Likely files

Inference manager, hotswap, running model discovery, startup, config, App and RunningModels, targeted tests.
