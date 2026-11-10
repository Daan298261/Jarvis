# RFC-0241: Reliable saved-model startup and incremental upgrades

**Status:** accepted
**Date:** 2026-10-28
**Author:** Codex, requested by Daan

## Problem
The desktop remains unloaded after a loopback Ollama startup race even though its saved model is installed. Normal upgrades still show first-install component choices and repeat preparation/download work. The user requests current lightweight community unrestricted models in the download catalog.

## Decision
Start or wait for the selected local Ollama endpoint, verify the saved model and warm it without implicitly downloading or changing the selected model. Preserve exact model preferences and expose actionable failures. Normal upgrades preserve component selections and installed assets, skip first-install choices, and only prepare missing or changed runtime/dependencies. Fresh installs, explicit repair and clean reinstall retain their intended controls. Add verified, public Hugging Face GGUF catalog entries for lightweight publisher-described uncensored/abliterated models, recording license, exact filenames, sizes and provenance without promising unrestricted behavior or unmeasured quality.

## Acceptance criteria
- Cold startup loads the saved installed model after the local service starts; a missing model never triggers an unsolicited pull.
- Remote inference hosts are never started or reconfigured, and failed warming is not reported as model readiness.
- Normal upgrade avoids selection/download churn, preserves settings, and reuses valid components; missing/changed dependencies are repaired.
- New catalog entries resolve to verified GGUF artifacts and carry honest provenance/license and compatibility metadata.
- Targeted regressions, required CI/build checks, actual local model reply and installed upgrade/reuse checks pass. Do not equate source checks with a completed installer artifact.

## Scope
Inference startup/Ollama lifecycle, installer upgrade/bootstrap reuse, existing model catalog, and focused tests. No changes to the preserved humanoid, architect specifications, user chat data or unrelated branches.
