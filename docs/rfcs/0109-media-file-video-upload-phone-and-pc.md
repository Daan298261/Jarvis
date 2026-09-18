# RFC-0109: Media / file / video upload on phone and PC apps

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it — after RFC-0108)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17  
**Amended:** 2026-09-18 — Taco goal 3: analyze **must OCR** images/photos of text on phone **and** desktop ([RFC-0118](0118-taco-goals-highest-leverage.md) rank 1). Not a third media RFC.

**Parent / index:** [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (Taco priority #3).  
**Related (do not rewrite):** RFC-0021 artifact crafts. RFC-0020 project knowledge (attach sources to a workspace). [RFC-0121](0121-projects-folder-chats-db-media-placement.md) project folder + media placement (0109 ingest writes through that layout when 0121 has landed; until then Leader data-dir artifact store). RFC-0058 Apex media parity. RFC-0059 BlackGrid capability contract (`studio_capabilities()`). RFC-0096 ComfyUI/SANA gen. RFC-0097 stitch / Real-ESRGAN. RFC-0102 LocalSend (device-to-device share ≠ ingest into Jarvis). `JARVIS_2.0.md` §76 multimedia. Companion `POST /api/companion/attachments` (exists, 64 MiB). `frontend/src/pages/Chat.tsx` composer (text + Speak only today). [RFC-0118](0118-taco-goals-highest-leverage.md) rank 1.

This PR is **specs-only**. Product code is a follow-up implement ticket.

## Problem

Taco needs to **drop media, files, and videos into Jarvis from the phone and from the PC** so Jarvis can **analyze**, **edit**, and send them through **Black Grid / media pipelines**.

Today:

- **Android companion** can attach via gallery (`GetContent`), camera capture, and share-sheet, then `POST /api/companion/attachments` (raw stream, 64 MiB cap, `x-filename` / content-type headers). Attachments hang on the conversation as ids. There is no typed media pipeline, no progress UI beyond “N attachment(s) ready,” no video-sized cap, and BlackGrid `studio_capabilities()` remains `available: False`.
- **Desktop / portal / Daybreak Chat** (`Chat.tsx` composer) is **text + Speak only**. There is no file input, drag-and-drop, paste-image, or video pick. Packs has a file input for manifests; that is not owner-media ingest.
- **Analyze / edit** have no first-class “this blob is the input artifact” path into vision, transcribe, filesystem-adjacent review, or RFC-0096/0097 jobs.

A chip that never becomes an artifact/tool input is a **fail**. Phone-only attach while the PC composer stays text-only is a **fail**. Advertising BlackGrid gen from upload before RFC-0096/0097 sidecars are reachable remains forbidden (RFC-0059) — but upload **must** still land in the artifact store and be ready for those pipelines.

## Decision

Add **first-class media ingest** on **both** the Android companion and the Desktop/portal (Chat / Daybreak composer), with one backend artifact contract.

### 1. One ingest contract (both clients)

Typed upload, not an opaque bag:

| Kind | Examples | v1 destination |
| --- | --- | --- |
| `image` | jpeg/png/webp/heic | analyze (vision/describe), BlackGrid `image` input, artifacts |
| `video` | mp4/webm/mov | analyze (transcribe/describe when models allow), BlackGrid `video` / `takes` / `stitch` input |
| `audio` | wav/mp3/m4a | transcribe (existing Whisper path where installed), BlackGrid `audio` |
| `file` | pdf/txt/zip/docx/… | analyze / project knowledge attach / filesystem-adjacent review under allowlist |

API (implement may rename, **not** invent a second store per client):

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/media/uploads` (desktop, owner session) | multipart or chunked; returns artifact id + kind + size + hash |
| `POST` | `/api/companion/attachments` | **evolve** the existing route: same artifact id space, typed `kind`, progress-friendly chunking; keep device auth |
| `GET` | `/api/media/uploads/{id}` | metadata + download (owner / same companion device) |
| `POST` | `/api/media/uploads/{id}/analyze` | start analyze job (describe / transcribe / extract) |
| `POST` | `/api/media/uploads/{id}/studio` | attach as BlackGrid take/input when studio reports that operation available |

Chunked / resumable upload is **required for video** (phone networks). 64 MiB remains the default **image/file** cap unless settings raise it; **video** cap is higher (implementer sets a documented default ≥ several hundred MiB, owner-configurable, disk-bounded under Jarvis data dir). Empty bodies 400; path-escape and device-mismatch 404; oversize 413 with a clear limit. Never log file bytes.

### 2. Desktop / portal / Daybreak (UX)

Composer (`Chat.tsx` and the Daybreak HUD chat composer) gains:

- Attach control (file picker) accepting the kinds above.
- Drag-and-drop onto the composer.
- Paste image from clipboard.
- Per-item progress, cancel, remove-before-send.
- Send includes media ids on the owner-chat / task turn so the agent **receives** them as tool-visible artifacts (not “filename mentioned in text only”).

Studio / companion studio page: if `studio_capabilities()` says `image`/`video`/`takes` available, **Use in studio** is enabled; otherwise the file still stores and analyze still runs, with truthful “studio backend not connected” (RFC-0096/0097).

### 3. Android companion (UX)

Keep gallery, camera, share-sheet. Add:

- Explicit **video** pick (not only `*/*` hope).
- Upload **progress** and failure retry (Outbox-class persistence for in-flight chunks).
- Same kind tagging and artifact ids as desktop so a phone upload is visible on the PC conversation/studio list.
- Share-to-Jarvis continues to upload; it must hit the new contract, not a dead legacy blob.

### 4. Analyze / edit / Black Grid handoff

**Analyze (this RFC, required):** given an uploaded artifact, Jarvis can describe images, **OCR images and photos of text** (phone camera/gallery **and** desktop attach/paste), transcribe audio/video (Whisper when installed), extract text from documents, and attach the result to the conversation/task as RFC-0021 artifacts. Missing optional models degrade to a **stated** limitation plus the stored file — not a silent drop.

**OCR (required, both surfaces):** photos and screenshots of printed/handwritten/on-screen text (whiteboards, receipts, pages, terminals, documents-as-images) **must** yield extracted text, not only a vision caption. Document `file` kinds already extract text; **image** kinds that contain text use the same owner-visible “extracted text” result. Prefer a **local** OCR engine (Tesseract-class or equivalent documented local runtime). Lazy mmproj / vision describe may **assist** but must not be the only path: OCR of photos of text is required even when the vision projector is not attached. Phone and desktop share one analyze job (`POST /api/media/uploads/{id}/analyze` with an `ocr` / extract-text action). Missing OCR engine: stated limitation + stored file — **not** a fake transcript and **not** a silent drop. Never log image bytes.

**Edit / Black Grid (this RFC wires ingest; gen/stitch engines stay 0096/0097):** uploads register as studio `takes` / inputs. When Comfy/OpenCut connectors are down, the take is stored and listed; jobs do not pretend to have generated. RFC-0102 LocalSend remains LAN **transport** between devices; it is not a substitute for this ingest.

GPU-heavy analyze-on-video follows §76 checkpoint/unload when it would fight the resident chat model.

**Architect’s initial recommendation:** one artifact store, both surfaces, analyze in this ticket, studio attach ready for 0096/0097. Taco can override caps.

**Will not:** vendor editors; fake BlackGrid gen; replace LocalSend; unrestricted WAN media scrape; HexStrike; persona merge; commit owner media to git.

## Acceptance criteria

- [ ] Specs-only in this PR (no `frontend/src` / `android/` / backend product edits)
- [ ] Desktop/portal **and** Android can upload image/video/audio/file into one artifact id space
- [ ] Composer attach + drag-drop + paste-image specified for PC; video pick + progress specified for phone
- [ ] Analyze job path specified (describe / **OCR for images/photos of text on phone and desktop** / transcribe / extract) with honest missing-model behavior
- [ ] OCR is a required analyze action for image kinds that contain text; missing OCR engine is a stated limitation + stored file, not a stub transcript
- [ ] Studio handoff specified; placeholder gen still not advertised live (RFC-0059)
- [ ] Video chunking / higher cap specified; oversize and empty rejected; bytes not logged
- [ ] Light §59 Decision Log line only (via `INTEGRATION_SPECS.md` batch)
- [ ] Implement follow-up: `python3 -m pytest`; `npm --prefix frontend run build` (and lint if TS changed); Android tests for pick/progress. Live camera/GPU analyze is desktop/device sign-off

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | new `backend/app/api/media.py` + `backend/app/media/` store; evolve `backend/app/api/companion.py` `POST /attachments` + `backend/app/mobile/service.py`; RFC-0021 artifact registry; analyze workers (vision / **OCR** / whisper / extract); studio attach hook next to `studio_capabilities()`; blob paths per RFC-0121 when that ticket has landed |
| Frontend (implement PR only) | `frontend/src/pages/Chat.tsx` composer; Daybreak HUD composer (`HudChatHome` / chat dock); `frontend/src/api.ts`; optional studio page attach |
| Android (implement PR only) | `CompanionModel.kt` `uploadNow`; `MainActivity.kt` picker (image/video/file), progress; share-sheet path |
| Tests | `tests/test_rfc0109_*.py` — kinds, caps, chunk assemble, device isolation, analyze-without-studio; Android unit tests for progress/retry |
| Docs | this RFC; `INTEGRATION_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. RFC-0096/0097 engine implement. RFC-0102 protocol. RFC-0108 on-device LLM (uploads may queue offline; analyze/OCR is Leader-side). RFC-0121 folder/chat topology (placement only, when that ticket lands). HexStrike. Persona merge. Instagram ingest of Saved media (Architect mines offline; this is owner-initiated upload). A third media RFC.

## Notes

- Source: Taco high-impact add 2026-09-17. Number **0109**. Amended 2026-09-18: explicit **OCR** for images/photos of text on phone + desktop (Taco goal 3; RFC-0118). Do **not** file a third media RFC.
- Linux cloud can unit-test caps, hashing, OCR job contracts with fixture bytes. Live camera, large video, GPU analyze, and OCR of real photos are Windows / device sign-off.
- Implement launch: **after RFC-0108**; this RFC only; branch from `development`; pytest + frontend build; Android companion agent for `android/` if that slice is named; do not edit Architect spec docs; PR against `development`.
