# External Agent Infrastructure Integration Specs

Status: proposed architecture / implementation specification  
Date: 2026-09-14  
Scope: evaluation and integration plan for the seven external repositories identified from the Duncan Rogoff post, plus Obsidian Brain.

## 1. Executive decision

Jarvis should **not** replace its FastAPI orchestrator, task state, scheduler, policy layer, verification loop, SQLite persistence, Worker/Node abstractions, or native memory repository with any one of these projects.

The correct design is to make selected external systems replaceable providers behind Jarvis-owned interfaces:

```text
                                 +---------------------+
                                 |   React / Desktop   |
                                 +----------+----------+
                                            |
                                            v
+-------------------------------------------------------------------+
|                       JARVIS ORCHESTRATOR                          |
| task state | policy | scheduling | routing | recovery | verifier  |
+----------+----------------+----------------+------------------------+
           |                |                |
           v                v                v
   ContextBackend      SkillPack layer    Worker / Tool layer
   - Native             - native packs     - Playwright
   - OpenViking*        - Agent Skills     - Browser Use
   - AgentMemory**      - scientific       - coding workers
                        - diagram           - security workers
                        - cyber
           ^
           |
   ReferenceStore
   - Obsidian-compatible Markdown vault

* Optional advanced context provider / sidecar.
** Optional coding-agent memory bridge or benchmark provider, not the default global memory authority.
```

The strongest additions are:

1. **Obsidian Brain pattern as the human-readable ReferenceStore**.
2. **A generic Agent Skills / external skill-pack loader**, then import Scientific Agent Skills, Diagram Design, and Cybersecurity Skills through that one mechanism.
3. **OpenViking as an optional ContextBackend sidecar**, not a hard dependency, because the main project is AGPLv3 and overlaps Jarvis memory/context responsibilities.
4. **Complete the existing Browser Use adapter** and turn it into a first-class browser Worker capability.
5. **AgentMemory only as an optional coding-worker memory provider / benchmark source**, because Jarvis already has native versioned memory, consolidation, provenance, conflict handling, trajectories, and learned skills.
6. **Awesome Harness Engineering is reference material, not runtime infrastructure**.

This preserves the existing one-machine behavior and the P2/P3 swarm architecture while adding useful capabilities incrementally.

---

## 2. Repositories identified

### 2.1 Browser Use

Canonical repository: `browser-use/browser-use`  
URL: https://github.com/browser-use/browser-use  
Role: autonomous browser worker / browser harness.  
License: MIT.

Jarvis status: **already partially integrated** through `backend/app/tools/browser_use.py` and `backend/app/workers/browser.py`. Playwright correctly remains the deterministic default.

Decision: **ADOPT / COMPLETE INTEGRATION. Not a Jarvis backbone.**

### 2.2 Agent Memory

Canonical repository matching the post: `rohitg00/agentmemory`  
URL: https://github.com/rohitg00/agentmemory  
Role: persistent cross-session memory for coding agents, exposed through MCP/HTTP/hooks.  
License: Apache-2.0.

Decision: **OPTIONAL PROVIDER / REFERENCE IMPLEMENTATION. Do not replace native Jarvis memory.**

Reason: Jarvis already has `backend/app/memory/`, versioned ContextRepo semantics, consolidation, provenance, mutations, conflict detection, trajectories, and skills. Running two equal global memory authorities would create duplicate facts, inconsistent forgetting, competing context injection, and unclear provenance.

### 2.3 Scientific Agent Skills

Canonical repository: `K-Dense-AI/scientific-agent-skills`  
URL: https://github.com/K-Dense-AI/scientific-agent-skills  
Role: Agent Skills-compatible research/science capability library.  
Repository license: MIT; imported individual resources/dependencies must still be license-scanned.

Decision: **ADOPT AS OPTIONAL SKILL PACK. Not a backbone.**

### 2.4 Diagram Design

Canonical repository: `cathrynlavery/diagram-design`  
URL: https://github.com/cathrynlavery/diagram-design  
Role: progressive-disclosure diagram-generation Agent Skill, self-contained HTML/SVG with export helpers.  
License: MIT.

Decision: **ADOPT AS OPTIONAL SKILL PACK + OUTPUT CAPABILITY. Not a backbone.**

### 2.5 Anthropic Cybersecurity Skills

Canonical upstream: `mukul975/Anthropic-Cybersecurity-Skills`  
URL: https://github.com/mukul975/Anthropic-Cybersecurity-Skills  
Role: large Agent Skills-compatible cybersecurity knowledge/workflow collection.  
License: Apache-2.0 in current releases.  
Important: community project; it is not an official Anthropic product.

Decision: **ADOPT AS SEPARATELY INSTALLABLE SECURITY SKILL PACK WITH POLICY GATING. Not a backbone.**

### 2.6 Awesome Harness Engineering

There are several similarly named repositories. Two useful current references are:

- `ai-boost/awesome-harness-engineering` — https://github.com/ai-boost/awesome-harness-engineering
- `harness-engineer/awesome-harness-engineering` — https://github.com/harness-engineer/awesome-harness-engineering

The post does not expose enough information to prove which fork/list the creator intended. Both are curated collections rather than a runtime framework.

Decision: **REFERENCE ONLY. Do not add as a runtime dependency or backbone.**

Use it to improve Jarvis architecture checklists, evals, context engineering, tool design, verification, observability, and long-running-agent patterns.

### 2.7 OpenViking

Canonical repository: `volcengine/OpenViking`  
URL: https://github.com/volcengine/OpenViking  
Role: agent context database using a virtual filesystem paradigm for memories, resources, and skills, with hierarchical/tiered retrieval.  
License: main project AGPLv3; `ov_cli` and examples are Apache-2.0.

Decision: **PROTOTYPE AS OPTIONAL ContextBackend / SIDECAR. Strongest external backbone candidate for context only, but it must not replace the Jarvis control plane.**

Because of AGPLv3, do not vendor its main-project code into Jarvis or make it an inseparable linked component without explicit licensing review. Prefer a separately installed service/process reached through HTTP/MCP/SDK boundaries.

### 2.8 Obsidian Brain

Primary repository for the requested reference-store role: `Rob-Morris/obsidian-brain`  
URL: https://github.com/Rob-Morris/obsidian-brain  
Role: local-first, human-readable Markdown knowledge base with router/taxonomy conventions, living and temporal artifacts, designed for agent retrieval and Obsidian editing.  
License: MIT.

A separate project, `sweir1/obsidian-brain`, can be evaluated later as an MCP/semantic-search access layer, but it is not required for the initial design.

Decision: **ADOPT THE STORAGE/ROUTING PATTERN AS JARVIS ReferenceStore. Do not use it as transient task-state storage.**

---

## 3. Cross-cutting architecture changes

### 3.1 Add a ContextBackend abstraction

Create a Jarvis-owned interface for retrieval and durable context. The Orchestrator remains the only component that decides what context is injected into a task.

Proposed files:

```text
backend/app/context/
    __init__.py
    base.py
    native.py
    openviking.py
    agentmemory.py
    service.py
    schema.py
```

Required interface, conceptually:

```python
class ContextBackend(Protocol):
    async def health(self) -> BackendHealth: ...
    async def put(self, entry: ContextDocument) -> ContextRef: ...
    async def get(self, ref: str) -> ContextDocument | None: ...
    async def search(self, query: ContextQuery) -> list[ContextHit]: ...
    async def delete(self, ref: str) -> None: ...
    async def compact(self, scope: ContextScope) -> CompactResult: ...
```

Rules:

- `NativeContextBackend` wraps the existing `backend/app/memory/` repository and remains default.
- The interface must preserve provenance, source IDs, agent/task scope, sensitivity labels, timestamps, and confidence/relevance metadata.
- Context providers never obtain authority to alter Jarvis policy, approvals, task status, or verification decisions.
- Provider failure must degrade to native context rather than aborting unrelated tasks.
- A user can select `native`, `openviking`, or a future backend in Settings.
- Provider-specific IDs must be mapped to stable Jarvis context IDs.
- Never silently dual-write the same memory to multiple backends. Mirroring must be explicit and auditable.

### 3.2 Add a ReferenceStore abstraction

Reference material is distinct from agent memory. The ReferenceStore is user-editable source knowledge; memory is Jarvis-learned/user-state knowledge.

Proposed files:

```text
backend/app/reference/
    __init__.py
    base.py
    obsidian.py
    watcher.py
    indexer.py
    schema.py
```

Required operations:

- register/unregister a vault;
- read/list/search documents;
- create/update Jarvis-managed notes;
- watch filesystem changes;
- produce stable content hashes;
- expose backlinks/tags/frontmatter;
- emit ingest/update/delete events to the selected ContextBackend;
- never overwrite user-edited notes without merge/conflict handling.

### 3.3 Extend the Pack system for open Agent Skills

Jarvis already has `backend/app/packs/` with schema, trust, preview/install/upgrade semantics. Extend that system rather than inventing a second plugin manager.

Current `RESOURCE_TYPES` should gain a first-class `skill` resource type. Add an Agent Skills importer which understands:

```text
<skill>/
    SKILL.md
    references/     # optional, lazy-loaded
    scripts/        # optional, never implicitly trusted
    assets/         # optional
```

Proposed files:

```text
backend/app/packs/agent_skills.py
backend/app/packs/skill_index.py
backend/app/packs/skill_runtime.py
```

Required behavior:

- import a whole repo/plugin or selected skills;
- parse frontmatter/metadata and normalize into Jarvis pack resources;
- build a lightweight searchable skill index;
- inject only the selected `SKILL.md` into model context;
- load referenced files only on demand;
- expose required packages, binaries, environment variables, APIs, tools, and scripts before activation;
- show a preview before installation/upgrades using the existing Pack preview mechanism;
- pin source repo + commit/tag for reproducibility;
- retain license/attribution metadata per imported skill;
- validate relative links and block traversal outside the skill root;
- treat imported text as instructions for a capability, never as system-level policy.

### 3.4 External-content trust model

All remote skill repositories and reference repositories are untrusted supply-chain inputs even when popular.

Before activation Jarvis must:

- compute content hashes;
- record source URL, commit SHA/tag, license and import date;
- scan executable scripts and manifests;
- list requested tools/capabilities;
- reject path traversal and symlink escapes;
- never execute install scripts merely because a `SKILL.md` says to;
- require explicit dependency installation through Jarvis's install/dependency flow;
- preserve user policy and approval rules above external instructions;
- allow disable/uninstall/rollback without affecting core Jarvis;
- support an offline frozen copy after installation.

---

## 4. SPEC-BROWSER-USE-002 — Complete Browser Use integration

### Objective

Turn the existing Browser Use adapter into a first-class browser Worker for unfamiliar/dynamic websites while retaining Jarvis Playwright as the deterministic path for known and repeated workflows.

### Existing Jarvis components to preserve

- `backend/app/tools/browser_use.py`
- `backend/app/workers/browser.py`
- existing Playwright/browser tool
- task loop, policy checks, trajectories and verification

### Routing rules

Use Playwright when selectors/procedure are known, the workflow has become a learned skill, or deterministic repeatability matters. Use Browser Use when the page structure is unknown, discovery/navigation is required, or selectors have changed and deterministic recovery failed.

Do not let Browser Use become a second orchestrator. Jarvis passes it a bounded browser sub-goal and receives evidence/result state.

### Required changes

- Add Browser Use to the Worker/capability registry as `browser.agentic`.
- Advertise availability/version/core-runtime status in capability telemetry.
- Add a version compatibility layer for current stable and beta/core APIs.
- Support persistent browser sessions when policy permits, with per-profile isolation.
- Add domain allow/deny scopes per task.
- Add timeout, cancellation, maximum-step and maximum-token budgets.
- Capture final URL, structured result, screenshots when useful, action summary, failure reason and timings.
- Feed sanitized execution evidence into Jarvis trajectories.
- If Browser Use discovers a stable repeatable procedure, allow Jarvis's existing skill-learning path to convert it into a deterministic Playwright workflow.
- Keep local-model support through Jarvis provider routing. Browser Use must not require a Browser Use cloud model.
- Provide fallback: Browser Use failure -> Playwright/web_fetch/manual task recovery.

### Acceptance criteria

- 20-task regression suite split between known deterministic sites and unfamiliar/dynamic sites.
- Known workflows continue preferring Playwright.
- Browser Use can complete bounded discovery tasks without owning top-level Jarvis task state.
- Browser failure/cancel leaves no orphan browser process.
- Sensitive browser profiles cannot be selected by an agent unless user policy allows them.

Priority: **HIGH**.

---

## 5. SPEC-REFERENCE-OBSIDIAN-001 — Obsidian-compatible ReferenceStore

### Objective

Give Jarvis a durable, human-readable reference library that both humans and agents can inspect and edit. This is the preferred location for project knowledge, decisions, research notes, manuals, source summaries and long-lived documentation.

### Storage contract

Default suggested structure:

```text
<reference-vault>/
    _Config/
        router.md
        Taxonomy/
    Projects/
    Decisions/
    Reference/
    Procedures/
    Sources/
    _Temporal/
        Sessions/
```

Jarvis may start with this layout and allow users to evolve it. The router is a compact orientation file, not a dump of the whole vault.

Recommended YAML frontmatter for Jarvis-managed notes:

```yaml
id: stable-uuid
type: reference
created_at: 2026-09-14T00:00:00Z
updated_at: 2026-09-14T00:00:00Z
source: jarvis
tags: []
sensitivity: private
jarvis_managed: true
```

### Behavior

- User chooses any local folder; Obsidian itself is optional.
- Plain Markdown remains canonical. No proprietary format.
- Jarvis watches changes and re-indexes only changed files.
- User edits win over generated content; conflict is surfaced rather than overwritten.
- Notes can link with normal Markdown/Wiki links; backlinks may be indexed.
- Reference retrieval returns file path, heading/section, content hash and source metadata.
- The Orchestrator requests only relevant excerpts; never inject the full vault.
- Selected task outcomes can be promoted into the vault only when useful as durable reference.
- Raw tool traces and temporary chain/state do not belong in the vault.

### Indexing modes

1. `native`: existing Jarvis ingest/search indexes vault content.
2. `openviking`: the vault is registered/indexed as resources in OpenViking while Markdown remains canonical.
3. Future semantic providers can be added behind `ReferenceStore`/`ContextBackend` boundaries.

### Acceptance criteria

- User edits a note in Obsidian -> Jarvis notices and retrieves the new version without restart.
- Jarvis creates a managed note -> it opens normally in Obsidian and any text editor.
- Rename/delete/update events are idempotent.
- 10,000 Markdown files do not require full re-index on one-file edits.
- Search results always contain provenance to an actual vault file/section.

Priority: **HIGH**.

---

## 6. SPEC-AGENT-SKILLS-001 — Generic Agent Skills loader

### Objective

Implement one standards-compatible skill ingestion/runtime layer so external libraries can be added as modular packs instead of writing a custom integration for each repository.

### Core design

Extend `backend/app/packs/` rather than replacing it. Add `skill` to pack resource types and convert external Agent Skills into Jarvis resources.

### Skill lifecycle

```text
repo URL / local folder
      |
      v
Fetch / inspect -> trust scan -> manifest preview -> user/policy install
      |
      v
Normalize metadata -> index SKILL.md -> keep references lazy
      |
      v
Task classifier / skill retrieval
      |
      v
Load selected SKILL.md only
      |
      +--> load reference/script metadata on demand
      |
      v
Jarvis executes through existing tools/workers/policy
```

### Requirements

- Git source, local directory and frozen bundled-pack sources.
- Repo-wide and selected-skill installs.
- Version pinning and upgrades with diffs.
- Search by name, description, tags, capability, domain and compatibility.
- Progressive disclosure: load only top skill instructions first, references only when required.
- Token-budget-aware skill injection.
- Per-skill enable/disable.
- Dependency declaration and health status.
- Skill scripts are executable only through normal Jarvis tools and approval/policy paths.
- An external skill cannot register arbitrary hidden tools.
- Imported skill content receives lower instruction precedence than Jarvis system/policy instructions.
- Metrics: activations, task success, token overhead, failures, missing dependencies.

### Acceptance criteria

- Import K-Dense Scientific Agent Skills without manually translating each skill.
- Import Diagram Design using the same loader.
- Import Cybersecurity Skills using the same loader.
- Loading 700+ skills must not add 700 skill bodies to every prompt.
- Uninstall removes imported resources but not user-created Jarvis memory or vault notes.

Priority: **HIGH; prerequisite for the next three specs.**

---

## 7. SPEC-SCIENTIFIC-SKILLS-001 — Scientific Agent Skills pack

### Objective

Expose research/scientific workflows as an optional Jarvis capability pack using `SPEC-AGENT-SKILLS-001`.

### Install profile

Pack ID: `external.scientific-agent-skills`  
Source: `K-Dense-AI/scientific-agent-skills`  
Default state: optional / disabled until installed.

### Integration rules

- Import the repository's Agent Skills/plugin metadata.
- Do not install every Python dependency globally.
- Resolve dependencies lazily per selected skill or capability family.
- Route Python-heavy work to an eligible Worker/Node with the required environment and resources.
- Preserve source/database provenance in task results when the skill provides it.
- Mark clinical, laboratory, financial or other high-impact domains so the existing Jarvis policy layer can apply appropriate review requirements.
- Cache dependency/environment readiness as Node capabilities for swarm placement.

### Acceptance criteria

- Skill discovery can select a relevant scientific skill from a natural-language research task.
- Only selected skill references enter context.
- Missing dependencies produce an actionable capability/dependency status rather than a hallucinated execution result.
- Research outputs preserve source provenance supplied by tools/databases.

Priority: **MEDIUM-HIGH**.

---

## 8. SPEC-DIAGRAM-DESIGN-001 — Diagram Design pack

### Objective

Add high-quality architecture, process, data, timeline and other diagrams as a reusable Jarvis output capability.

Pack ID: `external.diagram-design`  
Source: `cathrynlavery/diagram-design`

### Integration

- Install through the generic Agent Skills loader.
- Keep its progressive-disclosure design: one top-level `SKILL.md`, then one relevant type/reference at a time.
- Store generated source artifacts in the task/workspace as self-contained HTML/SVG.
- Add optional export actions for SVG and PNG through an existing browser/Playwright worker.
- Do not let the skill choose arbitrary output locations outside the task workspace without explicit user path selection.
- Support a Jarvis/user brand-style profile that maps into the skill's style configuration.
- Add an artifact result type so the UI can show generated diagram files and previews.

### Acceptance criteria

- Generate an architecture diagram from a Jarvis project description.
- Export to SVG and PNG.
- Only diagram-related skill context is loaded for a diagram task.
- Generated files are deterministic enough to rerender from source and remain editable.

Priority: **MEDIUM**.

---

## 9. SPEC-CYBER-SKILLS-001 — Cybersecurity Skills pack

### Objective

Provide Jarvis security workers with a large structured skills/reference library while keeping the security module separately installable and policy-governed.

Pack ID: `external.cybersecurity-skills`  
Source: `mukul975/Anthropic-Cybersecurity-Skills`  
Default state: not installed / disabled.

### Integration

- Import via `SPEC-AGENT-SKILLS-001`.
- Map skill metadata/tags into security domains such as DFIR, blue team, vulnerability assessment, threat intelligence, red team, malware analysis and cloud security.
- The pack supplies guidance/reference/workflows; actual actions use Jarvis registered security tools/workers.
- Security skills must never bypass the normal Jarvis tool exposure, target scope, authorization or approval policy.
- Preserve framework tags such as MITRE ATT&CK/NIST where available for retrieval and reporting.
- Permit installation on a dedicated security-role Node later through swarm capability placement.
- Keep the pack independent from the base install so non-security users do not carry its context/dependencies.

### Acceptance criteria

- Security task classification retrieves relevant skills without loading the whole repository.
- Non-security tasks do not see security skills by default.
- Skill instructions cannot expose an otherwise-disabled tool.
- All external skill/version/source metadata appears in task provenance.

Priority: **MEDIUM-HIGH for the security module; not base-install priority.**

---

## 10. SPEC-OPENVIKING-001 — Optional OpenViking ContextBackend

### Objective

Evaluate OpenViking as an advanced hierarchical context/retrieval engine for Jarvis while preserving Jarvis as control-plane owner.

### Deployment model

Preferred:

```text
Jarvis process
    |
    | ContextBackend API
    v
OpenViking adapter
    |
    | localhost/LAN HTTP or supported service protocol
    v
OpenViking sidecar/service
```

Do not vendor/link the AGPL main project into Jarvis core until licensing implications are explicitly accepted.

### Data mapping

Suggested mapping:

```text
viking://jarvis/<cluster-id>/
    resources/      <- reference vault, manuals, imported docs
    memories/       <- selected durable Jarvis memory only
    skills/         <- metadata/index to enabled skills
    projects/<id>/  <- project-scoped context
```

Jarvis remains authoritative for:

- task state;
- approvals/policy;
- Node/Worker placement;
- tool permissions;
- user settings;
- verification;
- audit events.

OpenViking may be authoritative only for content it owns inside its selected ContextBackend scope.

### Retrieval contract

- Query includes agent/task/project scope and token budget.
- Adapter returns ranked snippets/documents plus stable `viking://` provenance.
- Jarvis performs final context selection and prompt assembly.
- Retrieval path/trace should be logged when available for debugging.
- Results must honor sensitivity and project/agent access scope before reaching a model.

### Migration / fallback

- Native memory remains supported indefinitely.
- Provide export/import tools between Jarvis ContextEntry representation and OpenViking documents.
- If sidecar is unavailable, task continues with native context where possible.
- Never delete native data after migration until an explicit verified cutover is performed.

### Evaluation benchmark

Use a fixed corpus built from:

- Jarvis architecture/docs;
- selected reference-vault documents;
- prior task summaries/trajectories converted into safe benchmark facts.

Measure:

- Recall@K / answer-support recall;
- irrelevant-context rate;
- retrieval latency;
- token volume injected;
- update/delete consistency;
- recovery after restart;
- context quality for long-running coding tasks.

Promotion criterion: OpenViking becomes a recommended optional backend only if it materially beats native retrieval on relevant Jarvis tasks without unacceptable latency/maintenance burden.

Priority: **MEDIUM-HIGH PROTOTYPE; decision after benchmark.**

---

## 11. SPEC-AGENTMEMORY-001 — Optional coding-worker memory bridge

### Objective

Test AgentMemory where it is strongest: persistent memory across coding-agent sessions such as Codex/Cursor/Claude-compatible workers, without making it a second global Jarvis memory authority.

### Modes

#### Mode A — Reference/algorithm adoption

Use AgentMemory as inspiration for hybrid retrieval, memory lifecycle/decay, observation capture and cross-session coding context. Implement improvements inside native Jarvis memory where they fit.

This is the preferred first step.

#### Mode B — External coding-worker memory

Run AgentMemory as an optional local service. A coding Worker may query it for project-local coding history. Important conclusions are promoted to native Jarvis memory only through an explicit summarization/promotion step.

### Rules

- No transparent bidirectional dual-write.
- Assign a project/workspace namespace per Jarvis project.
- Captured coding observations are not automatically user profile memory.
- Jarvis task state remains in Jarvis.
- Jarvis final verification never trusts AgentMemory as proof that work succeeded.
- Provide a per-worker switch and health probe.
- If unavailable, coding Worker runs normally with native Jarvis context.

### Benchmark before promotion

Compare native Jarvis memory versus AgentMemory on repeated coding sessions:

- recall of earlier architectural decisions;
- recall of prior bug root causes;
- token overhead;
- latency;
- stale/wrong memory rate;
- duplicate/conflict rate;
- setup and operational cost.

If it does not materially improve coding outcomes, do not ship it as a default dependency.

Priority: **LOW-MEDIUM, after OpenViking/native context work.**

---

## 12. SPEC-HARNESS-REFERENCE-001 — Harness Engineering reference program

### Objective

Use Awesome Harness Engineering as an architecture/evaluation reading source rather than installing it in runtime.

### Process

Periodically review useful patterns and convert accepted ones into Jarvis-owned RFCs/tests/checklists covering:

- agent loop design;
- context management;
- tool interface design;
- planning artifacts;
- verification and independent review;
- observability/tracing;
- safe autonomy;
- multi-agent orchestration;
- long-running task recovery;
- eval design.

Do not ingest the whole curated list into every prompt. Keep it in the ReferenceStore under a `Sources/Harness Engineering/` area if desired and retrieve it only during architecture work.

Priority: **REFERENCE ONLY**.

---

## 13. Configuration contract

Suggested configuration keys. Exact config-file syntax may follow current Jarvis settings conventions.

```text
context.backend = native | openviking
context.fallback_backend = native
context.openviking.base_url = http://127.0.0.1:<port>
context.openviking.enabled = false

reference.enabled = true
reference.provider = obsidian_markdown
reference.vault_path = <user-selected path>
reference.index_backend = context
reference.watch = true

packs.agent_skills.enabled = true
packs.agent_skills.allow_scripts = false
packs.agent_skills.auto_update = false

browser.agentic.provider = browser-use
browser.agentic.enabled = optional
browser.deterministic.provider = playwright

memory.coding_external.provider = none | agentmemory
memory.coding_external.base_url = http://127.0.0.1:3111
```

Secrets must stay in the existing secrets/config mechanism, not in vault Markdown, skill files, source control or generated diagrams.

---

## 14. UI requirements

Add these surfaces to the existing universal React UI rather than creating provider-specific frontends:

### Settings > Context

- active ContextBackend;
- backend health;
- benchmark/test action;
- migration/export/import controls;
- OpenViking license/external-service notice.

### Settings > Reference Library

- vault path;
- watch/index status;
- file count / last indexed;
- reindex button;
- conflicts;
- open-vault/open-folder action when supported by host shell.

### Packs

Extend current pack UI with:

- Agent Skills source URL/version;
- trust/license;
- skill count;
- enable/disable by skill/domain;
- dependencies;
- scripts present warning;
- upgrade diff;
- rollback.

### Worker / Swarm capability view

Expose:

- Browser Use availability/version;
- scientific environment capabilities;
- diagram render/export capability;
- security skill pack availability;
- OpenViking/AgentMemory sidecar health where locally hosted.

---

## 15. Recommended implementation order

### Phase 0 — Interfaces and tests

1. Add `ContextBackend` interface wrapping native memory first.
2. Add `ReferenceStore` interface.
3. Add `skill` resource type and Agent Skills loader to existing Pack subsystem.
4. Build retrieval/skill-loading regression tests before adding external providers.

### Phase 1 — Lowest-risk high-value integrations

1. Obsidian-compatible Markdown ReferenceStore.
2. Diagram Design pack through generic loader.
3. Scientific Agent Skills through generic loader.
4. Cybersecurity Skills through generic loader, security-module scoped.

### Phase 2 — Browser worker completion

Upgrade the existing Browser Use adapter with capability telemetry, bounded sessions, evidence, cancellation, profile isolation and learned-workflow handoff to Playwright.

### Phase 3 — Context-engine prototype

Add OpenViking sidecar adapter and run retrieval benchmarks against native Jarvis context. Do not make it default until results justify it and packaging/license strategy is settled.

### Phase 4 — Coding-memory experiment

Add AgentMemory bridge only if native/OpenViking context still leaves a measurable coding-session memory gap.

### Phase 5 — Continuous harness review

Use Awesome Harness Engineering as a recurring source for architectural RFCs/evals, not a dependency.

---

## 16. Definition of done for this integration program

The program is complete when:

- Jarvis has provider interfaces rather than hard-coded external dependencies.
- Native Jarvis remains fully functional with every external component disabled.
- Obsidian-compatible references are editable by humans and retrievable by agents with provenance.
- External Agent Skills can be installed, indexed, lazily loaded, version-pinned, upgraded and removed through the Jarvis Pack subsystem.
- Scientific, Diagram and Cybersecurity repositories install through the same generic path.
- Browser Use operates as a bounded Worker and Playwright remains the deterministic execution path.
- OpenViking can be benchmarked as an optional sidecar without replacing Jarvis task/policy/verification state.
- AgentMemory, if shipped, is scoped to coding-worker memory rather than global authority.
- External content cannot override Jarvis policy or silently execute arbitrary scripts.
- Every external source has source/version/license provenance.
- All new capabilities participate in Worker/Node capability and resource-placement semantics so the design works on the current single host and future swarm nodes.

## 17. Final architectural recommendation

Do **not** turn Jarvis into a thin wrapper around one external framework. Its current separation of Orchestrator, Workers, tools, policy, memory, trajectories, packs and future Node placement is the right backbone.

The highest-value composite design is:

```text
Jarvis control plane
 + Native task/policy/verification state
 + Obsidian-compatible human reference vault
 + Native context by default
 + Optional OpenViking advanced context sidecar
 + Generic Agent Skills pack loader
     + Scientific Agent Skills
     + Diagram Design
     + Cybersecurity Skills
 + Playwright deterministic browser
 + Browser Use exploratory browser worker
 + Optional AgentMemory coding-session bridge
```

This gives Jarvis the useful parts of all eight projects without surrendering architectural control, creating duplicate global state, or coupling the product to one upstream project.
