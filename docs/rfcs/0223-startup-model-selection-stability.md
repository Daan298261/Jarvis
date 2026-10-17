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
- Installer source globs exclude build outputs relative to each source root; output slices, duplicate model/sidecar staging, Rust caches and vendor-only issuer code cannot enter the customer payload through those globs.
- A failed installer shutdown returns failure even after waiting for a polite stop, so elevation retry can run instead of reporting success while protected processes remain.
- LAN discovery responds only to phone probes, avoiding announcement echo loops. Connectivity/route checks and UI status/catalog probes run off the API event loop; beacon replies are bounded and cancelled on shutdown.
- The frozen voice stack includes its dynamically loaded spaCy English model and verifies the actual language pipeline at build time. Optional warmup and voice dependency failures cannot terminate the core API.

## Likely files

Inference manager, hotswap, running model discovery, startup, config, App and RunningModels, targeted tests.
