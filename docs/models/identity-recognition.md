# Local identity recognition model gate

RFC-0054 deliberately ships the identity resolver, encrypted embedding store, enrollment lifecycle and matching policy **without bundling face-recognition weights in the first implementation**.

## Candidate production backend

The initial production candidate is OpenCV Zoo **SFace** (`face_recognition_sface_2021dec`), which is based on MobileFaceNet-style face embeddings and is published by the OpenCV model zoo under the model directory's Apache-2.0 license metadata.

Jarvis must not download arbitrary mirrors or silently substitute a face-recognition model. Before a production model is bundled or fetched by the installer, the implementation ticket must pin:

- canonical upstream repository/release;
- exact model filename and version;
- SHA-256 hash;
- model-weight license and redistribution terms;
- expected embedding dimension;
- calibrated cosine-match threshold and ambiguity/margin threshold;
- CPU/GPU provider requirements;
- supported operating systems/architectures;
- model-pack signature under Jarvis's existing pack/update verification path where available.

## Provider contract

The biometric policy layer is backend-neutral. A local adapter must convert an ephemeral aligned face crop into a numeric embedding and then discard the crop:

```py
class IdentityBackend(Protocol):
    def embed(self, aligned_face: EphemeralFaceCrop) -> FaceEmbedding: ...
```

The adapter is not allowed to call a cloud face-identification API. Embeddings are passed to `IdentityResolver` in-process; there is intentionally no public HTTP `identify-face`, image-upload or embedding-search endpoint.

## Packaging status

As of RFC-0054's first implementation:

- no face-recognition model weights are bundled;
- no OpenCV dependency is added solely for identity recognition;
- recognition defaults to disabled;
- the backend setting defaults to `none`;
- production camera/detector/alignment integration remains a subsequent local desktop/runtime adapter ticket.

This keeps the security/privacy boundary testable before introducing camera/model dependencies.
