# RFC-0119: License-package entitlements, release unrestricted license, HexStrike overview

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Taco via Chief of Staff / Cursor  
**Date:** 2026-09-18

**Related (read; do not rewrite those contracts except the successor notes named below):** [RFC-0087](0087-vendor-license-manager.md) vendor License Manager, sealed `.jarvis-license`, `modules[]`. [RFC-0086 ATO](0086-in-person-cyber-ato-license.md) LE / Blue / Red signed artifact (**implemented**; password-gate half is **superseded here** — keep ATO/LE fields). [RFC-0086 Daybreak](0086-daybreak-blue-defensive-hexstrike.md) / [RFC-0106](0106-hexstrike-jarvis-full-operator-control.md) HexStrike product (overview prompt is a **UX add-on**, not an operator-control rewrite). [RFC-0012](0012-local-license-byo-inference.md) commercial lease `features[]` / `pack_entitlements[]`. [RFC-0048](0048-specialist-model-stack-routing.md) specialist routing (password unlock **superseded**; routing catalog stays). RFC-0079 / RFC-0110 per-action grants stay (operational consent, not capability unlock).

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `frontend/src/` or backend in this PR. **RFC-0118** is reserved for a parallel memo — do not take that number. Do not block RFC-0108 implement work. Draft #282 is out of scope.

**Hard constraint for this spec and for implement PRs:** do **not** include exploit recipes, PoCs, payload samples, command recipes, or step-by-step attack procedures — not in this RFC, not in the HexStrike overview / help text, not in tests as copy-pastable tradecraft.

## Problem

Capability unlock is split and dishonest:

1. **Password gates** (`data/security-model-gates.json`, `/api/runtime-profiles/security-gates/{role}/unlock`, Model page `SecurityModelGates`) still sit in front of Blue/Red specialist routing, computer-use cyber flags, and HexStrike defensive tool exposure (`gate_is_enabled`). RFC-0086 already required a signed ATO **and** a password; RFC-0087 already ships License Manager `modules[]` + `law_enforcement`. A password is not the product gate Taco asked for.
2. **License Manager packages and the commercial lease are not the runtime gate.** `GET /api/license/entitlements` and `frontend/src/pages/License.tsx` can list `features[]` / `pack_entitlements[]` while HexStrike, Daybreak, and LE/red/blue still unlock from a password toggle. That is a stub.
3. **Owner unrestricted licenses are hand-minted.** Every Windows Setup / release cut already drops `JarvisSetup.exe` and vendor `JarvisLicenseManager` into `installer/windows/dist/`. Taco still has to regenerate a full unrestricted package by hand.
4. **HexStrike loads with no product overview.** When the suite is selected in ModelSelector / Daybreak HUD, Jarvis does not say what HexStrike is. Help copy still talks about unlocking the Blue password gate.

## Decision

One RFC, three product facts:

1. The **signed license package** issued by **License Manager** is the **sole capability gate** for modules, functionalities, and LE / red / blue packs.
2. Every **Windows release / Setup build** **automatically** emits a **full unrestricted** owner/dev license file into the release artifacts folder beside Setup, so Taco never hand-regens.
3. When HexStrike is **selected and loaded**, Jarvis gives **one short** spoken and/or chat **product overview**. No exploit recipes.

**Will not:** invent new LE / Red / Purple / ATO officer-procedure rules beyond “entitlement comes from the signed license package” and the existing RFC-0086/0087 fields. Rewrite RFC-0106 operator control. Put `JarvisLicenseManager` or issuer private keys in the customer Inno payload. Ship product code in this PR. Take RFC-0118.

### 1. License package is the sole capability gate

**Source of truth for product modules** is the installed License Manager / ATO package (sealed `.jarvis-license` / installed ATO), not a password file:

| Field (already specified) | Meaning (do not invent new policy) |
| --- | --- |
| `modules[]` | Licensed module ids from RFC-0087 catalog (`backend/app/licensing/modules.py`: `blue-team`, `red-team`, `hexstrike`, `computer-use`, `specialist.security`, `domain.finance`, plus future catalog rows). |
| `law_enforcement` | Existing LE checkbox. **Red still requires LE** to issue and to enable (`requires_law_enforcement("red-team")`). Blue may be licensed without LE. |
| `expires_at` / `renew_by` / `max_expires_at` | Existing ATO validity / autorenew cap. Expired package does not unlock. |
| Clock-rollback lock | RFC-0087 daily UTC clock log still suspends **licensed modules** without taking down household chat. |

**Commercial lease** (RFC-0012 `SignedLease.payload.features` / `pack_entitlements`, e.g. RFC-0116 `decision.jev_plus`) remains the SKU layer for subscription extras. It does **not** replace License Manager for HexStrike / Daybreak / Blue / Red. It also must be consulted through the same entitlement functions — never `if True`.

**Central consult point** (extend, do not bypass):

- `has_feature(lease, feature)` / `has_pack_entitlement(lease, pack_id)` / `evaluate_cluster_entitlements(lease)` in `backend/app/licensing/entitlements.py`
- Installed package modules via existing `licensed_module_allowed` / `evaluate()` in `backend/app/policy/cyber_ato.py` (LE + expiry + clock already there)

Implement **must** make `evaluate_cluster_entitlements()` (and `/api/license/entitlements`) report **both** commercial lease fields **and** installed package `modules[]` + `law_enforcement` + validity, so UI and APIs have one read model. HexStrike / Daybreak / Blue / Red / module-worker surfaces **must** call that path (or a thin `has_module` / `has_feature` wrapper over it). A License page that **lists** packs but never **gates** those surfaces is a **fail**.

Suggested module → surface mapping (catalog ids already in code; do not invent new LE flags):

| Package module | What it unlocks |
| --- | --- |
| `hexstrike` | HexStrike suite select/start, Daybreak operator HUD, owner-chat HexStrike sidecar, `/api/hexstrike` operate, HexStrike MCP registration (RFC-0106 surface **unchanged** once entitled). |
| `blue-team` | Blue / DFIR specialist routing and Blue computer-use flags. |
| `red-team` | Red specialist routing and Red computer-use **permission flags only** — still default-deny; still requires `law_enforcement` on the **same** package. No payloads / exploits / hack-back added here. |
| `computer-use` | Desktop computer-use catalog (non-cyber). Cyber flags still need the matching blue/red/hexstrike module. |
| `specialist.security` / `domain.finance` | Pack entitlements already named in the catalog / RFC-0012. |
| RFC-0105 `cybersecurity` sibling | Gate through a License Manager module id **when that id is in the catalog**. Do not collapse into HexStrike. Do not add a new LE checkbox beyond existing `requires_le` on catalog rows. |

Missing / expired / clock-locked / forged package → capability **denied**, with a License-page / HUD reason that says the **package** does not cover it (not “unlock the password”).

### 2. Retire password gates for capability unlock

**Supersedes:** RFC-0048 “persistent security-role password gate” as a **capability unlock**; RFC-0086 ATO decision (2) “password gate **and** valid ATO”; RFC-0079 copy that Red flags “still require the Red Team password gate”; Model page password unlock; `gate_is_enabled` requiring `security-model-gates.json` `enabled=true`.

**Replacement:** `gate_is_enabled(role)` (or its successor) is **true** iff the installed license package currently allows that role module (`licensed_module_allowed` / entitlements), including existing LE + expiry + clock rules. No scrypt password, no unlock POST, no “Locked until the Blue Team password gate is unlocked.”

**Keep (not password gates):**

- RFC-0086/0087 signed package, LE flag, dates, in-person issuance record in License Manager.
- RFC-0079 / RFC-0110 **per-action** Allow once / Always / Deny (operational consent after the pack is entitled).
- RFC-0048 rule that generic `/route` must not enable security specialist profiles just because a pack is installed — still go through the security-role / entitlement path, not the generic `enabled=true` registry.
- Existing Red **issue** rule: License Manager **cannot issue** `red-team` without `law_enforcement` (already coded). Do not add case-file / officer-checklist UI here.

**Remove or make status-only (implement ticket):** password set/unlock/lock on `SecurityModelGates`; `/api/runtime-profiles/security-gates/{role}/unlock`; PermissionPrompt “password gate” lock copy; tests that unlock HexStrike/Blue/Red by posting a password. A leftover password file must **not** grant modules the package omitted, and must **not** be required when the package includes them.

### 3. Release cut emits a full unrestricted license file

Every Windows **release / Setup** build **automatically** writes a **full unrestricted** owner/dev license package into the **release artifacts folder** beside `JarvisSetup.exe`. Taco does not hand-regenerate.

**Hook point (spec now, implement later):**

1. `installer/windows/build-installer.ps1` already compiles Setup, then calls `build-license-manager.ps1` into `$OutDir` (`installer/windows/dist/`). **Immediately after that**, invoke a documented non-interactive issuer:
   - preferred script: `installer/windows/issue-release-unrestricted-license.ps1 -OutDir $OutDir`
   - which calls License Manager / vendor issuer CLI (not the Tk GUI), e.g. `python -m app.licensing.vendor_issuer` / a `issue-unrestricted` entry next to `issue_customer_license`.
2. Same hook belongs on any later release-cut wrapper that already calls `build-installer.ps1`. Do not invent a second unsigned mint path.

**Artifact (vendor folder only, like `JarvisLicenseManager.exe`):**

- Path: `installer/windows/dist/Jarvis-unrestricted.jarvis-license` (stable name) plus optional versioned copy `Jarvis-unrestricted-<JarvisVersion>.jarvis-license`.
- **Not** listed in `Jarvis.iss` `[Files]`. Customers do not receive owner-unrestricted by installing Setup.
- Payload: **every** current `LICENSE_MODULES` id; `law_enforcement=true` so `red-team` can be included under existing 0087 rules; long `expires_at` / `max_expires_at` at the issuer cap (today `term_days` ≤ 3660); licensee recorded as the owner/dev row License Manager already uses (name/email from issuer env / existing licensee — do not commit secrets).
- Signed and sealed the same way as any other License Manager file. Tag the payload (e.g. `kind` / `package_class`: `owner_unrestricted`) so it is distinguishable from a customer SKU.
- Uses the **vendor issuer private key** already on the release machine (`JARVIS_LICENSE_ISSUER_DIR` / `%LOCALAPPDATA%\Jarvis\license-issuer\`). Do not embed that key in git or in Setup.

**No soft-fail:** if the unrestricted file is missing, unsigned, module-incomplete, or LE-false while `red-team` is listed, **fail the release cut** (nonzero). The current “License manager build failed … JarvisSetup.exe is still usable” warning must **not** apply to this artifact. A README sentence that “the owner may generate an unrestricted license” without emitting the file is a **fail**.

Cloud/Linux CI still cannot compile Setup; this hook is Windows release-machine work. Unit-test the issuer helper (full module set, LE true, output path, not added to Inno `[Files]`).

### 4. HexStrike load overview (product only)

When the HexStrike suite is **selected and loaded** — ModelSelector `hexstrike-suite` / Daybreak HUD (`HudHexStrikeSuite` visible) **or** owner chat starts the sidecar — Jarvis delivers **one short** overview, **once per suite-load** (not on every catalog poll).

**Delivery:** canned owner-chat turn via existing `publish_owner_text` (`backend/app/persona/chat_delivery.py`, same family as `backend/app/persona/greeting.py`) with `speak=True`. If TTS is down, the **chat text still appears**. Do not skip the overview because voice failed.

**Canonical copy (implement may tighten wording, not the intent):**

> HexStrike is Jarvis’s embedded operator suite for security tooling on this PC. When it is loaded I can install and repair the local HexStrike runtime, show which tools are available, run the operator jobs you ask for, and bring logs and artifacts back into Daybreak and this chat. It binds to loopback only. I will not walk through exploits, payloads, or attack steps.

**Hard ban** in that prompt, HUD chrome, and the HexStrike help topic:

- no exploit recipes, PoCs, payloads, command recipes, or attack procedures
- no dump of the discovered tool catalog as how-to tradecraft (Daybreak Catalog remains the operator list per RFC-0106; the **overview** stays product-level)

Help topic `hexstrike-blue` must drop “Unlock the Blue gate” password language and must not keep “only the listed typed defensive actions” as the capability ceiling (RFC-0106 already won that). Replace with license-package entitlement + the same product overview. RFC-0106 operator routes, MCP, jobs, loopback, and pin **stay**.

### 5. Full intent — no stubs

| Stub (fail) | Required |
| --- | --- |
| License page lists packs; HexStrike/Blue/Red still password-unlocked | Every listed surface consults entitlements / package modules |
| Password unlock still enables a module the package omitted | Package wins; password cannot grant |
| Package includes `hexstrike` but Daybreak still needs a password | Suite starts from package alone (plus existing per-action grants) |
| Release docs “generate unrestricted later” / warning-only issuer | File always lands in `dist/` or the cut fails |
| Overview is a 150-tool attack cookbook or silent | One short product overview, spoken and/or chat |
| New LE/ATO checklists, guest HexStrike, Inno-shipped issuer key | Out of scope |

## Acceptance criteria

Specs-only in **this** PR:

- [x] RFC-0119 filed as `docs/rfcs/0119-license-package-entitlements-and-release-unrestricted.md`, status **accepted**, Date 2026-09-18 — this specs PR
- [x] License package is the sole capability gate; password gates retired for HexStrike / Daybreak / cyber / modules
- [x] Existing 0086/0087 LE / `modules[]` / expiry / clock rules referenced, not replaced with new officer policy
- [x] Release cut hook specified (`build-installer.ps1` → issue unrestricted into `dist/`, not Inno payload, hard-fail if missing)
- [x] HexStrike load overview specified (one short product prompt; exploit/PoC/payload/attack-step ban)
- [x] No stubs/soft-fail called out as fails
- [x] Light §59 Decision Log line only; no §57/§58 rewrite
- [x] Number **0119** (not 0118 / 0120 / 0121)
- [x] No `frontend/src/` or backend product edits in this PR

Implement follow-up (separate named ticket; not this PR):

- [ ] Entitlements evaluator + `/api/license/entitlements` + License page reflect package `modules[]` **and** those ids actually gate HexStrike / Daybreak / Blue / Red / catalog modules
- [ ] Password unlock APIs / Model-page password forms no longer unlock capability; leftover password state cannot override the package
- [ ] `gate_is_enabled` (or successor) reads the license package; tests that previously posted a password to unlock Blue/Red/HexStrike are rewritten
- [ ] `build-installer.ps1` (or the documented script it calls) writes `dist/Jarvis-unrestricted.jarvis-license` covering the full catalog + LE; missing/incomplete file fails the cut; `Jarvis.iss` still excludes it
- [ ] HexStrike select/load publishes the canned overview once (chat + TTS when voice is up); tests assert the copy has no exploit/payload/attack-step recipes and is not a tool-by-tool how-to
- [ ] Help topic no longer tells the owner to unlock a password gate
- [ ] Unit tests: `python3 -m pytest`; `npm --prefix frontend run build` (and lint if TS changed)
- [ ] Windows desktop sign-off: install owner-unrestricted from `dist/`, confirm HexStrike/Daybreak/Blue/Red follow the package (not a password), hear/see the overview on suite load. Cloud VMs cannot sign this off

## Likely files

| Area | Paths |
| --- | --- |
| Backend — entitlements | `backend/app/licensing/entitlements.py` (`has_feature`, `has_pack_entitlement`, `evaluate_cluster_entitlements`); `backend/app/api/license.py`; `backend/app/licensing/modules.py`; `backend/app/licensing/vendor_issuer.py`; `backend/app/policy/cyber_ato.py` (`licensed_module_allowed`) |
| Backend — retire password unlock | `backend/app/inference/security_gates.py` (`gate_is_enabled`); `backend/app/api/runtime_profiles.py`; `backend/app/policy/computer_permissions.py`; `backend/app/agent/tool_exposure.py`; `backend/app/tools/hexstrike_defensive.py` |
| Backend — HexStrike overview | `backend/app/persona/chat_delivery.py` / `greeting.py` pattern; HexStrike start path (`backend/app/api/hexstrike.py` / suite supervisor); `backend/app/help/topics.py` |
| Frontend | `frontend/src/pages/License.tsx`; `frontend/src/pages/SecurityModelGates.tsx`; `frontend/src/chat/PermissionPrompt.tsx`; `frontend/src/hud/HudHexStrikeSuite.tsx`; `frontend/src/hud/HudModelSelector.tsx`; `frontend/src/hud/hexstrikeSuite.ts` |
| Installer / vendor | `installer/windows/build-installer.ps1`; `installer/windows/build-license-manager.ps1`; new `installer/windows/issue-release-unrestricted-license.ps1`; `installer/windows/Jarvis.iss` (confirm **exclusion**); `tools/license_manager/` |
| Tests | `tests/test_license_entitlement.py`; `tests/test_security_gates.py`; `tests/test_cyber_ato.py`; `tests/test_installer.py`; new `tests/test_rfc0119_*.py` (overview copy ban; unrestricted issuer completeness; password cannot grant) |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only; one-line Related on RFC-0106 / INTEGRATION_SPECS 0106 row; successor note on RFC-0086 ATO |

## Out of scope

- Product implementation in this PR.
- RFC-0118 top-5 memo; RFC-0120 / 0121 if a parallel agent takes them.
- RFC-0108 phone companion offline model (do not block).
- Draft pull request #282.
- New LE / Red / Purple / ATO officer checklists, PolitieGPT internals, or changing `requires_le` on catalog rows except by existing 0087 rules.
- Rewriting RFC-0106 operator MCP/HTTP/jobs contracts, loopback bind, or install pin.
- Shipping `JarvisLicenseManager` or issuer private keys inside `Jarvis.iss`.
- Customer SKU that is unrestricted (owner/dev artifact only).
- Swarm / P4–P5 / model-stack.
- Architect rewrites of `SECURITY_AGENTS.md` / `BLUE_TEAM.md` / `INSTALLER.md` / `PORTAL_UX.md` beyond the §59 ledger tick.
- Exploit, PoC, payload, or attack-step documentation.

## Notes

- Source: Taco via CoS 2026-09-18. License Manager package is the central entitlement for HexStrike / Daybreak / modules / LE-red-blue. No password gates. Each release cut emits owner-unrestricted beside Setup.
- RFC-0087 License Manager remains vendor-only in `installer/windows/dist/` beside Setup.
- Linux cloud VMs: unit-test entitlements, issuer helper, overview copy bans. Live Setup + HexStrike load + spoken overview is **Windows desktop sign-off**.
- Implement launch: this RFC only; branch from `development`; pytest + frontend build; do not edit Architect spec docs beyond the §59 line Architect/CoS already asked for; PR against `development`; do not merge other PRs.
