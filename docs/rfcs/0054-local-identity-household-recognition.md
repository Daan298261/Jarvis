# RFC-0054: Local identity resolver and household recognition

**Status:** implemented
**Queue item:** P1 — Optional local household recognition  
**Author:** ChatGPT design session  
**Date:** 2026-09-08

## Problem

Ambient perception becomes substantially more useful when Jarvis can distinguish the enrolled owner from an unknown visitor or another explicitly enrolled household member. That capability is also biometric processing and therefore must not be smuggled into the ordinary camera/presence feature. Identity resolution needs its own consent, storage, lifecycle, audit and failure behavior.

## Decision

Add an **optional, local-only face-embedding identity resolver** that maps a detected face to an owner-enrolled identity. It is disabled by default, never required for humanoid gaze or general social perception, and never sends embeddings or enrollment images to remote inference.

### Principles

1. Explicit enrollment only.
2. Local processing only by default; no cloud identity matching path.
3. Store embeddings, not enrollment photos, unless the owner explicitly exports a recovery bundle.
4. Treat embeddings as sensitive biometric data.
5. Unknown remains a valid result; never force a nearest identity match.
6. Identity confidence and face-quality thresholds are separate.
7. Jarvis dialogue must not expose identity details to guests/remote portals.
8. Enrollment/deletion is an owner-authenticated action and cannot be initiated silently by an LLM.

### Candidate implementation

Use a small commercially redistributable face-recognition model through a provider interface. OpenCV Zoo SFace is a strong initial candidate because its model directory is Apache-2.0 and it has compact/quantized variants, but the implementation must keep the model adapter replaceable.

```py
class IdentityBackend(Protocol):
    def embed(self, aligned_face: EphemeralFaceCrop) -> FaceEmbedding: ...
```

Face detection/alignment and identity matching are distinct operations.

### Enrollment model

Each enrolled identity has:

```json
{
  "identity_id": "owner",
  "display_name": "Owner",
  "relationship": "owner",
  "created_at": "...",
  "embedding_model": "sface-2021dec",
  "embedding_version": 1,
  "samples": 5
}
```

The persisted record stores one or more normalized embeddings plus metadata required to invalidate/re-enroll if the model changes. No raw camera frame is retained.

Enrollment flow:

1. Owner opens Settings > Presence > Recognition.
2. Jarvis explains that face embeddings are biometric data and local-only.
3. Owner explicitly enables recognition.
4. Capture several frames across modest pose/lighting variation.
5. Reject low-quality/occluded samples.
6. Convert accepted samples to embeddings.
7. Show enrollment result and sample count.
8. Discard image frames.
9. Persist encrypted-at-rest embedding payload where platform primitives permit.

### Matching

For a detected face:

```text
quality gate
  -> embedding
  -> compare only against enrolled local identities
  -> if best score >= threshold AND margin to second-best >= margin threshold
       known(identity_id, confidence)
     else
       unknown
```

Do not report a known identity from a weak nearest-neighbour match.

### Presence session

Identity should have temporal hysteresis. A single frame must not make Jarvis repeatedly flip between known/unknown.

Recommended state:

- provisional after first strong match;
- confirmed after N of M recent matches;
- keep confirmation briefly through short occlusion;
- clear after person exits or timeout;
- revalidate if another face becomes dominant.

### Household support

Roles are deliberately coarse:

- owner;
- household_member;
- trusted_person;

The system does not infer relationship automatically. The owner names/labels enrolled people.

### Privacy and access

- Embeddings are excluded from normal `/api/memory`, task prompts, logs and remote telemetry.
- Guest portals cannot enumerate enrolled identities.
- Normal agents receive only the minimum event, e.g. `person.identity=owner`, when policy permits.
- Exporting identity data is a separate explicit action.
- Deleting an identity removes all embeddings and cached recognition state.
- Turning recognition off stops matching but may preserve enrollment records unless the owner chooses delete.
- A `Delete all recognition data` control must exist.

### API

Owner-only API:

- `GET /api/perception/identity/status`
- `GET /api/perception/identity/enrollments`
- `POST /api/perception/identity/enrollments` — enrollment metadata/session creation, not arbitrary remote face uploads.
- `DELETE /api/perception/identity/enrollments/{id}`
- `POST /api/perception/identity/reset`

The camera capture path should remain inside the local desktop/frontend bridge. A LAN/API client must not automatically gain a convenient face-recognition upload service.

### Settings

```py
class IdentityRecognitionSettings(BaseModel):
    enabled: bool = False
    backend: str = "none"
    match_threshold: float = 0.0  # backend supplies calibrated default
    confirmation_window: int = 5
    confirmation_hits: int = 3
    lost_timeout_seconds: float = 3.0
    expose_identity_to_dialogue: bool = True
```

`enabled=False` is authoritative.

### Security

- Enrollment and deletion require owner authentication and explicit UI action.
- Reject path traversal / arbitrary model paths.
- Model packages must be signed/verified under Jarvis pack/update policy where available.
- Embedding files use restrictive filesystem permissions.
- Identity store must not be synchronized to swarm nodes automatically.
- Swarm sharing, if ever added, needs a separate explicit RFC.

### Accuracy / UX

Jarvis should prefer silence/unknown over a confident-sounding wrong identity.

UI states:

- `Owner recognized` only after confirmed matching;
- `Person present` when identity is unknown;
- avoid displaying similarity scores in ordinary UI;
- expose diagnostic scores only in Advanced/Diagnostics.

### Acceptance criteria

- [ ] Recognition defaults off and social perception works without it.
- [ ] Enrollment requires explicit owner action.
- [ ] Raw enrollment frames are discarded after embedding.
- [ ] Persisted identity data contains embeddings/metadata, not photos.
- [ ] Unknown faces remain unknown below threshold/margin.
- [ ] Temporal confirmation suppresses one-frame identity flapping.
- [ ] Identity API is inaccessible to guest portals.
- [ ] Owner can delete one enrollment and all recognition data.
- [ ] Tests cover threshold, second-best margin, temporal confirmation, delete/reset and disabled behavior.
- [ ] Production model/license is documented before bundling.
- [ ] `python3 -m pytest` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Recognition | `backend/app/perception/identity.py`, `backend/app/perception/identity_store.py` |
| API | `backend/app/api/perception_identity.py` |
| Config | `backend/app/config.py`, `backend/app/api/settings.py` |
| Frontend enrollment | `frontend/src/pages/Settings.tsx`, `frontend/src/perception/identity/**` |
| Tests | `tests/test_perception_identity.py` |

## Out of scope

- General person tracking across cameras.
- Search over unknown people.
- Law-enforcement/forensic face identification.
- Cloud face-recognition services.
- Inferring names/relationships from the image.
- Any protected/sensitive trait inference.

## Notes

OpenCV Zoo's SFace model directory documents Apache-2.0 licensing and compact/quantized MobileFaceNet-based models. Verify exact model asset provenance and hashes at implementation time rather than downloading arbitrary third-party weights.
