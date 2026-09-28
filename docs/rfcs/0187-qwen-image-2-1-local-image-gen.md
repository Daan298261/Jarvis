# RFC-0187: Qwen-Image-2.1 local image gen

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-28

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md). Living index: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) § 2026-09-28 reel batch (implement-first #5).  
**Beside:** [RFC-0096](0096-comfyui-sana-blackgrid-media-gen.md) ComfyUI / SANA.  
**Related (do not rewrite):** RFC-0059 `studio_capabilities()`. RFC-0109 ingest. RFC-0186 video engine. `JARVIS_2.0.md` §76 GPU load/unload (read only).

This file is **specs-only**. Do not vendor weights or `QwenLM/Qwen-Image-2.1`. Full intent. **No stubs / soft-fail.**

## Problem

BlackGrid `image` is still only as real as an owner-installed ComfyUI/SANA sidecar (RFC-0096). Qwen-Image-2.1 is a local text-to-image and image-edit model (about 7B in the visual stack, native RGBA, multi-reference edits) that ComfyUI can already run, and that Diffusers / vLLM-Omni / SGLang can serve directly. Jarvis has no contract for that engine, so a worker will either ignore it or mark `image` available with no weights on disk.

## Goals

- Optional **local** image sidecar beside ComfyUI/SANA, not a second portal studio.
- Operations: text-to-image, image edit (including more than one reference, capped at the model’s limit of 10), and transparent RGBA when the owner asked for it.
- `studio_capabilities().image` is true only for a backend that actually answers. Name which backend (Comfy Qwen workflow, or a direct local server). Never a placeholder.
- Weights stay owner-installed under the upstream Qwen Research License. Jarvis does not relicense them and does not commit them.

## Non-goals

- Replacing RFC-0096. If ComfyUI is the installed sidecar and the Qwen-Image-2.1 workflow is registered, route through that connector. A direct Diffusers or vLLM-Omni server is the path when **that** runtime is what the owner installed.
- Cloud demo sites (Hugging Face Space, wuli.art) as the product backend.
- Shipping a 2K render on machines that cannot load the model. CPU-offload may be offered; pretending a CUDA render finished is a fail.
- Prompt-rewrite VLMs as a silent always-on. They are optional and must show in the job record when used.
- Vendoring the model repo. Invented LE / ATO gates. Video (RFC-0186 / RFC-0097).

## Contract

| Rule | Requirement |
| --- | --- |
| Source | Code: [QwenLM/Qwen-Image-2.1](https://github.com/QwenLM/Qwen-Image-2.1). Weights: `Qwen/Qwen-Image-2.1` (and the Comfy-Org weight repo when the Comfy path is used). License: upstream Qwen Research License. |
| Route | One active image backend per job. Comfy workflow **or** direct local HTTP/CLI. Not both writing the same artifact. |
| Job | Prompt, optional reference images from RFC-0109 / allowlisted paths, seed, size, steps, RGBA flag. Result is an artifact with those parameters and the backend id. |
| Capabilities | `available: true` only after a live probe (server up, weights resolved, or Comfy workflow listed). Detail string names the backend. Down ⇒ `available: false`. |
| GPU | Load for the job and unload per the existing §76 policy. Do not leave a second resident model beside the chat GGUF without that policy. |
| Honesty | Failed probe, OOM, or missing weight file returns an error artifact state. No stock PNG labeled as a generation. |
| Fail | `image.available: true` with no backend. A custom gen canvas in the portal. Weights inside the Jarvis git tree. |

Aspect ratios and the 40-step default are upstream recommendations, not a second product spec. The implement ticket passes owner overrides through and records what ran.

## Acceptance

- [x] Spec: sidecar beside RFC-0096, truthful `studio_capabilities()`, no vendored weights
- [ ] Implement: Comfy route and/or direct local route; probe gates the capability flag
- [ ] Implement: text-to-image and edit jobs write artifacts; RGBA only when requested and the backend returns it
- [ ] Implement: missing weights or dead sidecar ⇒ `available: false` and a repair/Download CTA
- [ ] Tests use a scripted sidecar, not a GPU (`tests/test_rfc0187_*.py`)
- [ ] Desktop sign-off later for a real local render; cloud VM cannot sign that off
- [ ] No weights and no vendored tree in the specs PR

## Local clone

Not in git. Clone is the model card / code; weights download on the owner machine under the upstream license.

| Machine | Path |
| --- | --- |
| Architect box | `/workspace/projects/rfc/Qwen-Image-2.1` |
| Windows owner library | `C:\Users\daanv\projects\jarvis-ig\rfc\Qwen-Image-2.1` |

Upstream: https://github.com/QwenLM/Qwen-Image-2.1

## Lane

**D1** (studio adapter, capability probe, artifact handoff, tests).

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `studio_capabilities()`; BlackGrid image adapter next to the RFC-0096 connector |
| Tests | `tests/test_rfc0187_*.py` |
| Docs | this RFC; [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md); §59 ledger only |

## Out of scope

Video engine (RFC-0186). Rewriting RFC-0096. Portal image editor. Live GPU sign-off on a cloud VM.
