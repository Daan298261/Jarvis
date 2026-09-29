# RFC-0195: Model discovery, OpenMuse, HyImage, Harness research

**Status:** partially implemented (discovery + settings; image gen backend selection only)  
**Date:** 2026-09-29

## Implemented

- Local GGUF discovery (`model_discovery.py`), `GET/POST /api/model/discover-local`, installer `-ScanLocalModels`, Settings **Discover models on this PC**.
- OpenMuse session personality mode + Ship Notes–inspired signal orb in Settings when active.
- `image_generation.backend` setting (Hunyuan 2.1 local, Hunyuan 3 local, Hy 3.5 API placeholder).
- `GET /api/model/integrations/research` summarizes Harness vs Strands, MiMo Pro, HyImage.

## Research (not fully integrated)

| Item | Finding |
| --- | --- |
| **Jarvis harness** | `POST /api/model/harness/run` — local perf harness, not Strands SDK. |
| **Strands Harness SDK** | RFC-0192 sidecar only; do not replace ANZU loop. |
| **MiMo-V2.6-Pro** | Not local on consumer GPU; use Distill 9B GGUF (`bartowski/...`). |
| **HyImage 2.5** | No public local artifact; 3.5 Preview is API/cloud (Sept 2026). |
| **Shipnotes components** | MIT reference UI; Jarvis ships lightweight `ShipnotesSignalOrb` for OpenMuse. |

## Follow-up tickets

- Wire `image_generation.backend` to a media worker (ComfyUI / hyimage pipeline).
- Optional Strands sidecar evaluation per RFC-0192 after CoS names ticket.
