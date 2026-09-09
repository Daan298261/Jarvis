# RFC-0043 — LM Studio graded model profiles (digest)

**Full spec:** `docs/rfcs/0043-lmstudio-graded-model-profiles.md`

When `inference.backend` is `lmstudio`, Jarvis scans the LM Studio models directory for `.gguf` files, merges them with a **graded catalog** (overall rank, axis scores, VRAM warnings), and binds rows to RuntimeProfiles. Pinned favorites sort first; >16 GB footprints hide by default. Grades are provisional estimates, not live harness scores.
