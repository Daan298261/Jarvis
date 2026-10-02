# RFC-0198: blue.re fit, cyber modes UX, and LTA protected-folder unlock

**Status:** accepted  
**Queue item:** (none — no §58 checkbox)  
**Author:** Jarvis Architect  
**Date:** 2026-10-02

**Related:** [RFC-0197](0197-blue-red-purple-security-agents.md) blue/red/purple agents. [RFC-0196](0196-hexstrike-operator-chain-anzu-1.md) Daybreak console. [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) **Veles**, **Themis**, Daybreak suite chrome. [RFC-0086 Daybreak](0086-daybreak-blue-defensive-hexstrike.md) HUD patterns.

Specs-only. **No ledger ticks.** **No** pasted Access blobs, private keys, police certificates, or live decode steps.

## Problem

Owners working cyber defense and authorized recovery need a **conforming workflow** to open **Global Disk Long-Time Archiving (LTA)** protected folders on Windows: XML manifest `Access` sections as base64 PKCS#7-wrapped keys, decryption with owner-held RSA private key material, archive password extraction, and 7-Zip unpack — without Jarvis becoming a tool to break third-party archives without owner keys. Separately, [blue.re](https://blue.re) may align with blue-team product positioning; public integration surface was **not** reachable from the Architect cloud environment during spec authoring, so API claims must stay honest.

## Decision

### 1. blue.re — research spike (no invented APIs)

**Public research status (2026-10-02):** HTTPS fetch to `https://blue.re` from the cloud agent environment returned no usable public HTML (timeout/empty). **Do not** document REST endpoints, SDKs, or auth flows until a follow-up spike succeeds.

| Spike id | Acceptance criteria |
| --- | --- |
| `blue-re-public-surface` | Document from **primary sources only**: product positioning, intended customer, any published API/docs links, privacy/security statements. Output: `docs/rfcs/spikes/blue-re-public-surface.md` (implement spike ticket, not this PR). |
| `blue-re-jarvis-fit` | Decision memo: integrate as (a) link-out partner, (b) Module Catalog backend, (c) no integration — with owner-scoped data handling constraints. Requires Taco sign-off before implement. |

Until spike completes, Jarvis **must not** ship hard-coded blue.re API clients or mock “connected to blue.re” UI.

### 2. UX intent — “open this protected folder”

**Personas:** Blue/defensive flows default **Themis** (`twin_shield`); red/adversarial context **Veles**; operational HexStrike/Daybreak chrome unchanged ([RFC-0137](0137-persona-presence-shape-and-voice-binding.md)). Purple uses both per RFC-0197.

**Owner utterance examples (product intent only):**

- “Open this protected folder: `D:\Evidence\Case-42\manifest.xml`”
- “Unlock the LTA archive at `\\server\share\bundle`”

**Jarvis behavior (workflow, not tradecraft):**

1. Resolve owner-provided **filesystem path** (must be under `allowed_directories` or explicit owner grant per RFC-0079).
2. Locate **XML manifest** (owner path or child `manifest.xml` / documented LTA naming — implement discovers from owner doc in spike; do not embed law-enforcement-specific filenames in spec).
3. Parse manifest **Access** sections: each value is **base64-encoded PKCS#7** encrypted message (CMS EnvelopedData pattern). Example shape only:

```xml
<Access CertThumbprint="…" SubjectKeyIdentifier="…">base64-PKCS7-ciphertext…</Access>
```

4. **Key material retrieval (Windows only):**
   - Match `CertThumbprint` and/or `SubjectKeyIdentifier` against **Current User** / **Local Machine** cert store (owner-provisioned).
   - If owner has stored **authorized recovery key** material in Jarvis-owned vault (`data_dir()/recovery-keys/` metadata only — private keys never logged), use per owner policy.
5. Decrypt PKCS#7 → plaintext yields **archive password** (UTF-8 string or documented encoding from owner LTA spec spike).
6. Invoke **7-Zip** (or owner-configured archiver path) to extract to a Jarvis-owned working directory under `data_dir()/lta-extract/{job-id}/`.
7. Present extract summary in **Daybreak** job panel + chat; audit path, cert thumbprint used, success/failure (no password or key bytes in audit).

**Forbidden:**

- In-product decode of **third-party** archives without owner-provided keys/certs
- Shipping default police/LE certificates or sample PKCS#7 blobs in repo
- Bypassing license or target registry ([RFC-0197](0197-blue-red-purple-security-agents.md))

### 3. CRYPTO / WORKFLOW contract (conforming only)

| Step | Input | Output | Failure (honest) |
| --- | --- | --- | --- |
| Load manifest | Path to XML | Parsed `Access[]` entries | `manifest_not_found`, `xml_invalid` |
| Resolve cert | Thumbprint/SKI | Cert with private key handle | `cert_not_found`, `no_private_key` |
| Decrypt Access | base64 PKCS#7 + RSA private key | Archive password bytes | `decrypt_failed` (show CMS error class, not ciphertext) |
| Extract | 7z archive + password | Files under job dir | `archive_failed` with 7z exit code |

Placeholders in docs/tests: `CertThumbprint=ABCD…`, `Access=base64-PKCS7…`, `archive.7z`.

### 4. API sketch (implement may rename)

| Method | Path | Intent |
| --- | --- | --- |
| `POST` | `/api/lta/protected-folder/open` | `{ "manifest_path": "...", "archive_path": "..." }` → job id |
| `GET` | `/api/lta/jobs/{id}` | Status + extract listing |
| `GET` | `/api/lta/certs/candidates` | Thumbprints/SKIs available for match (no private key export) |

Reuse RFC-0196 job streaming patterns in Daybreak (shared Jobs UX or LTA tab).

### 5. Implement anti-patterns

- “Unlock” button that always succeeds with a dummy password
- Parsing Access blobs from spec/examples committed to git
- Network calls to blue.re before spike approves integration
- Skipping cert-store match and asking owner to paste PEM private keys into chat (redirect to secure local picker)

## Acceptance criteria

Specs-only:

- [x] LTA workflow documented with placeholder crypto shapes only
- [x] blue.re marked research/spike with acceptance criteria
- [x] Personas Veles/Themis/Daybreak cited
- [x] No secrets, blobs, or live decode instructions

Implement follow-up:

- [x] Windows cert store + PKCS#7 decrypt + 7z extract pipeline
- [x] Daybreak/job streaming + audit without secret leakage
- [x] Deny paths outside allowed_directories
- [x] Unit tests with **synthetic** keys generated in test temp dir only
- [ ] blue.re spike files if Taco approves next wave
- [ ] **Desktop soak**: owner manifest + owner cert → extract listing in Daybreak

## Likely files

| Area | Paths |
| --- | --- |
| Backend | new `backend/app/security/lta_archive.py`, `backend/app/api/lta.py`, Windows cert helpers |
| Frontend | Daybreak cyber/LTA panel (extend HexStrike job UI patterns) |
| Tests | `tests/test_rfc0198_*.py` |
| Spikes | `docs/rfcs/spikes/blue-re-public-surface.md` (later) |

## Out of scope

- Law-enforcement case systems beyond owner-scoped recovery
- Cracking unknown archives
- Committing third-party certificates or real Access ciphertext
- Architect edits to `BLUE_TEAM.md` body

## Notes

- Authorized recovery tooling only; aligns with defensive owner use (Themis-led UX).
- Cloud VM cannot run Windows cert store or desktop soak.
