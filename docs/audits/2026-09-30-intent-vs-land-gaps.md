# Intent-vs-land gap list — 2026-09-30

**Audience:** Chief of Staff (assign harden / bug / debt tickets to D1 / D2 / UX / Desktop)  
**Scope:** Tip `development` @ `9bd2481` (RFC-0194 presence idle restore #466). Audit only — no product code, no new RFCs, no ledger flips.  
**Quality bar:** Anzu 1.0 / multibillion — stubs, soft-fail, half-wires, “coming soon” chips count as gaps.  
**Standing order:** No new RFCs unless Taco names one. Finish open work; hunt bugs / incomplete lands / shortcuts.

### Inventory method

- ~90 RFC files with `Status: implemented` (case variants); §58 `[x] … implemented` lines cover 0139–0140, 0171–0178.
- Cross-checked flagged RFCs against headers, §59 Decision Log residuals, and concrete `rg` hits in `backend/` / `frontend/`.
- Prefer high-impact intent misses over exhaustive line-by-line of every implemented RFC.

---

## P0 (blocks product intent)

- **RFC-0107** — Obsidian durable brain still **accepted**; backend bind/index/working-set + Desktop embed host landed, but product intent (embedded real Obsidian **used** on owner turns) is not closed.  
  **Evidence:** RFC header stays `accepted` until UX embed + remaining backend; §59 / INTEGRATION ladder still treat hot-path use as residual. Code: `backend/app/memory/obsidian_vault.py`, `backend/app/agent/turn_working_set.py`, `frontend/src-tauri/src/obsidian_host.rs`, `frontend/src/pages/Obsidian.tsx`. Browser portal path explicitly cannot embed (`Chrome cannot embed Obsidian.exe`) and soft-routes to external Obsidian open — acceptable as platform limit, but Desktop soak of hwnd-parent embed + vault-relevant turn provenance is unsigned. Acceptance boxes for embed / operational use still unchecked.  
  **Lane:** UX (Desktop host polish) + D1 (hot-path retrieve/write proof, no empty working-set décor)  
  **Ticket:** Close RFC-0107: prove bound vault on owner turns + Windows Desktop Obsidian.exe embed soak; then Architect may flip Status.

- **RFC-0031** — Reversibility-first action gates **accepted**, essentially **unlanded** as specified.  
  **Evidence:** All acceptance boxes unchecked. `backend/app/policy/action_gate.py` is a Laya harm-veto wrapper over `authorize()`, not the RFC-0031 contract (`REVERSIBLE` / `COMPENSATABLE` / `IRREVERSIBLE` / `UNKNOWN`, durable undo, unforgeable `ApprovalGrant`, park-without-holding-worker). No tool-level `reversibility` metadata, no composite rollback journal as specified. Related pieces exist elsewhere (RFC-0110 approvals, `RiskLevel.IRREVERSIBLE`, memory `reversible` flag) but do not satisfy 0031.  
  **Lane:** D1  
  **Ticket:** Implement RFC-0031 reversibility metadata + durable undo + model-unforgeable approval provenance (do not rename Laya veto as “done”).

- **RFC-0026** — Marked **implemented**, but UI / owner observability intent is open.  
  **Evidence:** Status `implemented` (backend #393); queue line and §59 say UI residual open; acceptance checkboxes for home/task-row phase + verification badge remain unchecked. Frontend has almost no `ExecutionPhase` / `VerificationSummary` surface (only loose `current_activity` on System self-dev). §58 still shows backlog `[ ]` “accepted” — ledger mismatch.  
  **Lane:** UX  
  **Ticket:** Ship compact phase + verification on home/task rows and task detail from `GET /api/tasks/{id}/observability`.

- **RFC-0172** — Marked **implemented — P0**, but reflex lane can soft into a fail-closed stub; 0145/0151 remain soft deps.  
  **Evidence:** RFC residuals: tip wire follow-up + live a11y soak; soft 0145/0151. Code: `backend/app/reflex_loop/reflex_client.py` documents fail-closed stub when 0171 client absent (`source="fail_closed_stub"`, log “Reflex Lane unavailable”); `tests/test_rfc0172_reflex_computer_use.py` covers stub refuse. §58: tip wire + a11y soak residual.  
  **Lane:** D1 (wire hardening) + D2 (0145/0151 minimal ActionFrame / sandbox posture if CoS names those accepted RFCs)  
  **Ticket:** Harden 0172→0171 `browser_operation_target` path so production never idles on stub; schedule soft 0145/0151 lands or explicit narrow in-ticket substitutes.

---

## P1 (incomplete / soft)

- **RFC-0092** — Status still **accepted** while most code criteria appear landed; ledger/status lag + Desktop A/B proof.  
  **Evidence:** `DEFAULT_VOICE_PROFILE_ID = butler_original_v1`; SAPI pack `quality_tier: "baseline"`, display “Windows system (SAPI)”; `synthesize.py` refuses silent SAPI on Kokoro/Chatterbox failure; `tests/test_rfc0092_neural_tts.py` asserts no silent system audio. Chatterbox env gate largely removed in favor of pack readiness. RFC acceptance boxes still unchecked; Status not `implemented`. Live Desktop Setup A/B (engine_id/profile_id in preview samples) remains sign-off. Sibling **RFC-0089** still accepted with unchecked TTS/GPU rows.  
  **Lane:** Desktop soak + Architect ledger tick (if CoS confirms intent met); D1 only if A/B finds silent degrade or wrong default  
  **Ticket:** Desktop A/B: default butler neural, no silent SAPI; then Architect flip 0092 (and close overlapping 0089 TTS rows).

- **RFC-0105** — **Implemented** as Module Catalog + Daybreak panel, but connectors stay intentionally **`partial`**.  
  **Evidence:** `backend/app/modules/cybersecurity.py` `integrate_decision: "partial"`; RFC/§59: six members, partial connectors; live Daybreak HUD / Open folder / subprocess = desktop sign-off. Soft shell vs “real module workers for each clone.”  
  **Lane:** D1  
  **Ticket:** Deepen cybersecurity member connectors beyond download/enable/open-folder shell (per-member launch hooks that are real, not catalog décor).

- **RFC-0106 / HexStrike Daybreak** — **Implemented** operator console, but live Windows operator invoke unsigned; optional proxy stubs remain in tree.  
  **Evidence:** Acceptance Windows desktop sign-off unchecked. `backend/app/security/hexstrike_compat.py` installs mitmproxy/selenium stubs when packages absent (`install_optional_stubs`). Sibling **RFC-0086** Daybreak Blue file still **accepted** with all boxes unchecked (product stance superseded by 0106; install/scope/Blue-role criteria not re-closed as 0086).  
  **Lane:** Desktop (soak) + D1 (stub honesty / missing-dep UX if soft)  
  **Ticket:** Windows soak: pinned install → HUD+chat operator invoke → job/log/artifact; audit stub paths so missing deps never look “running.”

- **RFC-0108** — **Implemented**; offline tokens = device sign-off; pack-cache/popup claimed landed (#309/#319/#317) but acceptance boxes left open.  
  **Evidence:** RFC footer + device sign-off residual; live on-device token generation not cloud-verifiable.  
  **Lane:** D2 / Android device  
  **Ticket:** Phone soak: recommended pack download → real offline tokens → sync; close open acceptance rows or file concrete bugs.

- **RFC-0109** — **Implemented** (#371); live camera/GPU analyze + OCR engine presence = device/desktop sign-off.  
  **Evidence:** `backend/app/media/analyze.py` honest missing-OCR path (`_ocr_available`); acceptance left open for live sign-off. Risk: environments without Tesseract look “analyze works” but OCR empty.  
  **Lane:** Desktop + D2  
  **Ticket:** Soak OCR on phone+PC images of text; ensure UI states missing engine (no stub transcript).

- **RFC-0140** (companion on-device voice) — **Implemented** (#403); Whisper/TTS native bake + phone soak residual.  
  **Evidence:** RFC residual line; §58 same; fail-closed flags acknowledged in §59.  
  **Lane:** D2 / Android  
  **Ticket:** Bake Whisper+TTS ORT device path; phone soak — no fake listen/speak.

- **RFC-0171** — **Implemented — P0**; GPU/Laya sha + speed-claim release gate residual.  
  **Evidence:** RFC residual: empty Laya sha256 pin still fail-closed / refuses install; TypeSafe/Laya GPU soak; release-gate speed claims need Desktop evidence.  
  **Lane:** Desktop + D1 (pin fills when artifacts known)  
  **Ticket:** Fill production Laya sha pins; Desktop latency soak; block marketing speed claims without evidence.

- **RFC-0175** — **Implemented**; Desktop GPU / WebGL soak vs refs A/B/C + real webcam face attract residual.  
  **Evidence:** Unchecked soak acceptance; camera stack exists (`frontend/src/presence/presenceCameraTrack.ts` MediaPipe / FaceDetector fail-closed). #466 (RFC-0194) restored idle free-float on tip — soak still needed against mood boards.  
  **Lane:** UX / Desktop  
  **Ticket:** Taco Desktop soak: morph vs refs A/B/C + webcam face attract.

- **RFC-0178** — **Implemented**; Windows GPU clarity / sustained FPS unsigned (low FPS noted in #430).  
  **Evidence:** Unchecked GPU review row; #432 low-tier bypass is part of implement, not residual close.  
  **Lane:** UX / Desktop  
  **Ticket:** GPU soak: sustained FPS + silhouette clarity across personas/tiers.

- **RFC-0174** — **Implemented**; portal closed; live multi-model room Desktop soak residual.  
  **Evidence:** RFC + §58 residual wording.  
  **Lane:** Desktop  
  **Ticket:** Live multi-model room soak on Desktop GPU host.

- **RFC-0071** — **Implemented** (portal #392); soft debt remains.  
  **Evidence:** §59: GET list/detail/audit not owner-key gated; threshold PUT / `admit_automatic_trigger` call `ensure_automation` with default `kind="generic"` (rewrites prior kind); race test allows `<= 2`; audit rows under-asserted; RFC-0016 dispatcher still absent.  
  **Lane:** D1  
  **Ticket:** Harden 0071 API auth + stop kind rewrite on threshold PUT.

---

## P2 (debt / soak residuals that don’t block)

- **RFC-0139** — Android fancy orb implemented; physical phone daylight soak only.  
  **Lane:** Android device sign-off.

- **RFC-0194** — Presence idle/framing restore just landed (#466); Status in file may still say `accepted` with Galaxy/GPU soak checkbox open — treat as presence soak companion to 0175/0178, not a new feature.  
  **Lane:** UX / Desktop / Architect ledger hygiene.

- **RFC-0193** — Voice alternatives marked implemented; installer download checkboxes + live VoiceStudio/Pocket/Whisper paths still need Desktop Setup soak.  
  **Lane:** Desktop.

- **RFC-0095 children (0096–0104)** — Still `partial` / later ladder; not falsely “full product.” Keep off quality-pass P0 unless Taco elevates.  
  **Lane:** backlog (Architect/CoS ranking).

- **Advisor stub** — `backend/app/agent/advisor.py` / `frontend/src/pages/Advisor.tsx` intentional practice stub provider; not an RFC-implemented miss, but do not market as live commercial advisor.  
  **Lane:** UX copy hygiene if needed.

- **Duplicate RFC numbers** — Stale accepted copies (`0139` skill-forge, `0140` multi-agent rooms) vs canon `0173`/`0174` implemented — docs hygiene only.  
  **Lane:** Architect cleanup when Taco allows.

---

## Already solid (skip)

- **RFC-0173** Skill Forge — portal residual closed (#416); residuals none.  
- **RFC-0176** Shared dot appearance profiles — residuals none.  
- **RFC-0177** Shared dot persona motion cues — residuals none.  
- **RFC-0111** Kokoro real runtime / **RFC-0114** context overflow recovery / **RFC-0115** Ornith router — implemented with desktop-only live residuals, not soft shells.  
- **RFC-0120** coding+3D tools / **RFC-0121** projects+chats-in-DB / **RFC-0110** approval modal — treat as landed for quality-pass unless soak finds bugs.  
- **RFC-0078** HexStrike suite shell acceptance checked; deeper operator bar owned by 0106 soak above.  
- **RFC-0050 / RFC-0051** presence architecture / humanoid runtime — Status Implemented; lifecycle owned by 0175+ amend lands.

---

## Recommended first 5 assigns

Ordered for CoS (quality/fix pass + Taco Obsidian priority):

1. **RFC-0107** — Obsidian embed + hot-path operational proof (UX + D1) — product priority; do not tick implemented until Anzu bar met.  
2. **RFC-0026** — Execution phase / verifier portal UI residual (UX) — already marked implemented; half-wire.  
3. **RFC-0031** — Reversibility-first action gates full contract (D1) — accepted gap; autonomy quality.  
4. **RFC-0172** — Reflex tip-wire harden; kill production stub idle; decide 0145/0151 soft deps (D1, optional D2).  
5. **RFC-0175 + RFC-0178** — Combined Desktop GPU presence soak (morph/refs/webcam + FPS) (Desktop/UX) — blocks calling presence “done.”

**Next wave:** 0105 connector deepen (D1); 0106 HexStrike Windows operator soak (Desktop); 0092 Desktop A/B then Architect status flip; 0071 auth/kind harden (D1); 0108/0140 phone soaks (D2).

---

## Concrete `rg` hits (tied areas)

| Area | Hit |
| --- | --- |
| Reflex soft stub | `backend/app/reflex_loop/reflex_client.py` — `fail_closed_stub`, “Reflex Lane unavailable” |
| HexStrike optional stubs | `backend/app/security/hexstrike_compat.py` — `install_optional_stubs`, `hexstrike_stub` |
| Cyber module partial | `backend/app/modules/cybersecurity.py` — `integrate_decision: "partial"` |
| Obsidian browser soft path | `frontend/src/pages/Obsidian.tsx` — portal cannot embed; external open CTA |
| Voice picker empty states | `frontend/src/tts/VoiceProfilePicker.tsx` — `voice-profile-stub` CSS when catalog unavailable/empty |
| Advisor practice stub | `backend/app/agent/advisor.py`, `frontend/src/pages/Advisor.tsx` — stub provider |
| Action gate ≠ 0031 | `backend/app/policy/action_gate.py` — Laya harm veto only |

No `coming soon` copy found under `frontend/src`.

---

## Notes for Architect / CoS

- Do **not** invent new RFC numbers for these gaps — assign as harden/bug/debt against the existing RFC id.  
- Desktop soak residuals are real Anzu-bar blockers when the RFC claims visual/audio/operator full intent (0175/0178/0106/0092), even when unit tests are green on Linux cloud.  
- Spec docs / §58 ledger flips are Architect-only after CoS confirms a ticket closed.
