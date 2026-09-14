# External Agent Infrastructure Integration Specs v2

Status: approved architectural direction  
Date: 2026-09-14  
Supersedes: `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md` where decisions conflict.

## 1. Governing decision

Every external project previously rated **OPTIONAL**, **ADOPT**, **PROTOTYPE**, or stronger SHALL now be integrated into Jarvis in some form.

This does **not** mean replacing working Jarvis systems wholesale. The rule is:

> **Jarvis keeps authority wherever Jarvis is already stronger. External projects contribute only the subsystems, algorithms, data formats, assets, skills, adapters, or execution backends that materially improve Jarvis.**

The resulting architecture is compositional rather than framework-driven.

Jarvis remains the owner of:

- orchestration and task decomposition;
- GoalRun/task state and checkpoints;
- scheduling and swarm/node placement;
- user policy, approvals, budgets, privacy, and permissions;
- canonical operational memory and provenance;
- tool exposure and command execution;
- recovery and retry policy;
- independent verification and completion decisions;
- local-first behavior and offline operation wherever feasible.

External systems MUST NOT become a second equal control plane.

---

## 2. Integration doctrine

### 2.1 Integration modes

Every imported capability is assigned one or more of these modes:

1. **EMBED** — copy or vendor bounded assets/code into Jarvis when licensing and maintenance make this sensible.
2. **ADAPTER** — run an external library/process behind a Jarvis-owned typed interface.
3. **SIDECAR** — run a separately installed service and communicate over HTTP/MCP/stdio. Use this for license isolation or heavyweight dependencies.
4. **EXTRACT** — reproduce a useful algorithm, data model, indexing technique, workflow pattern, or file convention inside Jarvis without adopting the whole framework.
5. **REFERENCE** — use only as architecture/design input. No runtime dependency.

The preferred order is **EXTRACT or EMBED small subsystems > ADAPTER > SIDECAR > wholesale framework adoption**.

### 2.2 Native-superiority gate

Before an external subsystem can replace an existing Jarvis subsystem, it must beat the native implementation on the capability it is replacing.

Minimum comparison dimensions:

- success/accuracy/recall;
- latency;
- token/context cost;
- RAM/VRAM/CPU overhead;
- offline/local compatibility;
- failure recovery;
- observability/debuggability;
- portability across Windows/Linux/Pi nodes;
- dependency weight;
- licensing constraints;
- maintainability;
- compatibility with Jarvis task state, policy, and verification.

Results are capability-specific. An external repo may win retrieval quality while lose lifecycle management. In that case Jarvis SHALL keep its lifecycle and extract only the retrieval subsystem.

### 2.3 No dual authority

Do not create two authoritative versions of the same state.

Examples:

- Jarvis native memory remains canonical; AgentMemory/OpenViking can index, enrich, retrieve, or shadow-test it.
- Jarvis task database remains canonical; external workers return observations/evidence only.
- Jarvis skill registry remains canonical; third-party skill repos are imported sources.
- Obsidian Markdown is canonical for human-curated reference documents, while Jarvis stores indexes/metadata pointing to those files.

### 2.4 External execution contract

External agents/workers may return:

- result payload;
- artifacts;
- evidence;
- logs/trace summary;
- citations/source URIs;
- proposed memory candidates;
- proposed workflow/skill candidates.

They may not directly declare a Jarvis GoalRun complete. The Jarvis verifier makes that decision.

### 2.5 Local-first rule

All integrations must support local execution when the upstream project supports it. Cloud-only features must be optional and explicitly configured. A feature that requires an external service must degrade cleanly when offline.

---

# 3. Target architecture

```text
                         React / Desktop UI
                                |
                                v
+------------------------------------------------------------------+
|                       JARVIS ORCHESTRATOR                         |
| task state | policy | routing | scheduling | recovery | verifier |
+--------+----------------+------------------+----------------------+
         |                |                  |
         v                v                  v
 Context Router       Skill Registry      Worker Registry
         |                |                  |
   +-----+------+      +--+---------+     +--+-------------------+
   | Native     |      | Native     |     | Playwright           |
   | OpenViking |      | Scientific |     | Browser Use          |
   | AgentMem   |      | Diagram    |     | Coding workers       |
   | Ref Store  |      | Cyber      |     | Security workers     |
   +-----+------+      +------------+     +----------------------+
         |
         v
 Obsidian-compatible ReferenceStore
 plain Markdown + links + provenance
```

The Context Router SHALL merge results from multiple bounded backends while keeping provenance and authority visible.

---

# 4. Shared abstractions to add

## 4.1 `ContextBackend`

Create a Jarvis-owned interface, suggested location:

`backend/app/context/base.py`

Required operations:

```python
class ContextBackend(Protocol):
    id: str

    async def health(self) -> BackendHealth: ...
    async def index_resource(self, resource: ContextResource) -> IndexResult: ...
    async def remove_resource(self, resource_id: str) -> None: ...
    async def retrieve(self, query: ContextQuery) -> list[ContextHit]: ...
    async def get(self, uri: str) -> ContextDocument | None: ...
    async def summarize(self, uri: str, level: int) -> ContextSummary | None: ...
    async def commit_session(self, session: SessionDigest) -> list[MemoryCandidate]: ...
```

Backends:

- `NativeContextBackend`
- `OpenVikingContextBackend`
- `AgentMemoryContextBackend` (coding/session memory scope only)
- `ReferenceStoreBackend`

`ContextHit` MUST include backend id, URI, score, source/provenance, authority class, and content hash.

## 4.2 `ReferenceStore`

Suggested location:

`backend/app/reference_store/`

Interface:

```python
class ReferenceStore(Protocol):
    async def list(self, path: str = "") -> list[ReferenceEntry]: ...
    async def read(self, uri: str) -> ReferenceDocument: ...
    async def write(self, doc: ReferenceDocument) -> ReferenceDocument: ...
    async def search(self, query: str, scope: str | None = None) -> list[ReferenceHit]: ...
    async def watch(self) -> AsyncIterator[ReferenceChange]: ...
```

Default provider: `ObsidianVaultStore`.

## 4.3 Agent Skills importer

Extend `backend/app/packs/` so that third-party Agent Skills are imported into Jarvis's existing pack/trust system.

Add `skill` to `RESOURCE_TYPES` in `backend/app/packs/schema.py`.

Suggested modules:

- `backend/app/skills/schema.py`
- `backend/app/skills/importer.py`
- `backend/app/skills/registry.py`
- `backend/app/skills/discovery.py`
- `backend/app/skills/dependencies.py`

The importer SHALL support:

- `agentskills.io` layout;
- `SKILL.md` discovery;
- YAML/frontmatter metadata;
- Agent Plugins `plugin.json` when present;
- pinned repository URL + commit SHA;
- source license metadata;
- content hash;
- dependency declarations;
- trust level;
- category/tags;
- required tools/capabilities;
- lazy loading;
- enable/disable per pack/skill;
- update preview and rollback.

Skills are procedural knowledge. Importing a skill MUST NOT automatically grant tools or permissions.

## 4.4 External subsystem manifest

Each external integration SHALL have a manifest:

```yaml
id: browser-use
source_repo: browser-use/browser-use
source_commit: <sha>
integration_modes: [adapter, extract]
authority: worker-only
license: MIT
enabled: true
capabilities:
  - browser.agentic
native_fallback: browser.playwright
```

Store manifests under a dedicated integration registry so updates are traceable.

---

# 5. Browser Use — integrate and complete

Source: `browser-use/browser-use`  
Decision: **INTEGRATE — ADAPTER + EXTRACT**.

Jarvis already has:

- `backend/app/tools/browser_use.py`
- `backend/app/workers/browser.py`
- deterministic Playwright browser tooling.

That native split is correct and SHALL remain.

## Keep Jarvis-native

- Playwright as deterministic default for known sites/selectors;
- Jarvis policy and credential boundaries;
- task state/checkpointing;
- learned repeatable procedures;
- final verification;
- tool permissions;
- browser resource budgeting.

## Integrate from Browser Use

Use Browser Use for:

- unfamiliar-site exploration;
- semantic element discovery;
- adaptive navigation where selectors are unknown;
- recovering from changing DOM/layout;
- multi-step form/workflow exploration.

## Extracted subsystem behavior

Successful Browser Use traces SHOULD be distilled into deterministic Jarvis browser procedures when repetition is detected:

```text
unfamiliar workflow
      |
      v
Browser Use discovery
      |
      v
successful trace
      |
      v
trajectory store
      |
      v
procedure compiler
      |
      v
Playwright/Jarvis skill
```

This prevents paying agentic-browser overhead forever for workflows that become known.

## Required implementation

- Register `browser.agentic` capability.
- Add worker health/probe/start/stop lifecycle.
- Add max-step, timeout, token and browser-session budgets.
- Return structured action evidence rather than only free text.
- Add screenshot/final-URL/state evidence.
- Add fallback to Playwright/web fetch.
- Add trace-to-skill candidate generation.
- Surface current browser worker and fallback path in UI.

Acceptance: an unfamiliar workflow can be completed by Browser Use, later repeated deterministically after promotion without changing Orchestrator behavior.

---

# 6. AgentMemory — integrate useful subsystems, do not replace Jarvis memory

Source: `rohitg00/agentmemory`  
Decision: **INTEGRATE — ADAPTER + SHADOW + EXTRACT**.

AgentMemory currently provides useful ideas including BM25 recall, optional local embeddings, graph-aware search, confidence/lifecycle concepts, hooks, MCP/REST integration, and cross-agent memory access.

Jarvis already has stronger ownership semantics:

- versioned ContextRepo state;
- provenance;
- mutations/history;
- conflict detection;
- consolidation;
- trajectories;
- learned skills;
- task-aware injection;
- Jarvis-owned persistence.

These SHALL remain authoritative.

## Integrate AgentMemory as a bounded provider

Add `AgentMemoryContextBackend` with three modes:

- `disabled`
- `shadow`
- `advisory`

`shadow` is the initial default during evaluation. Queries are sent to both native Jarvis retrieval and AgentMemory; results are scored but only native results drive behavior unless explicitly enabled.

`advisory` allows AgentMemory hits to enter the Context Router, tagged with `authority=advisory`.

AgentMemory MUST NOT write directly to canonical Jarvis facts.

## Extract into native Jarvis where superior

Benchmark and, where useful, implement natively:

- BM25/lexical retrieval alongside semantic retrieval;
- local embedding option;
- hybrid lexical + semantic + structural/graph ranking;
- memory confidence score;
- memory lifecycle state;
- automatic coding-session capture hooks;
- cross-coding-agent memory adapters;
- smart search that fuses structural and semantic evidence.

Suggested native retrieval pipeline:

```text
query
 |- lexical/FTS candidate search
 |- embedding candidate search
 |- relationship/graph expansion
 `- recency/confidence/project weighting
          |
          v
      rank fusion
          |
          v
 provenance-aware ContextHit[]
```

## Coding-agent bridge

Use AgentMemory-compatible MCP/REST only as a compatibility bridge for external coding agents when useful. Prefer having those agents query Jarvis through a Jarvis MCP memory facade once feature parity exists.

Acceptance: Jarvis gains hybrid memory retrieval and coding-agent recall without surrendering canonical memory ownership or creating duplicate authoritative facts.

---

# 7. Scientific Agent Skills — full pack integration

Source: `K-Dense-AI/scientific-agent-skills`  
Decision: **INTEGRATE — PACK/EMBED METADATA + LAZY SKILL CONTENT**.

The project follows the open Agent Skills standard and contains a large set of research procedures plus integrations and database workflows.

## Integration design

Create a first-party Jarvis pack descriptor:

`scientific-agent-skills`

Jarvis SHALL import upstream skills by pinned commit rather than manually rewriting them.

Do not inject the entire library into every prompt.

Discovery flow:

```text
Task classification
      |
      v
skill metadata search
      |
      v
shortlist 1..N skills
      |
      v
load SKILL.md + only needed references
      |
      v
execute through Jarvis tools/workers
```

## Useful subsystem extraction

Reuse the upstream conventions for:

- skill schema and frontmatter;
- version-scoped procedural documentation;
- per-skill examples;
- dependency/test metadata;
- deterministic database access guidance;
- provenance-aware research workflows.

Jarvis SHALL own dependency installation and tool execution.

Dependencies should be installed on first use in an isolated skill environment or worker environment, not globally during base Jarvis installation.

## UI

Add pack-level and category-level toggles and a searchable skill catalog. Show dependency/install status per skill.

Acceptance: Jarvis can discover and invoke a relevant scientific skill without loading unrelated skills and without bypassing local tool policy.

---

# 8. Diagram Design — integrate as native diagram capability

Source: `cathrynlavery/diagram-design`  
Decision: **INTEGRATE — SKILL PACK + EMBED/EXTRACT TEMPLATES**.

The useful subsystem is not another agent framework; it is a mature diagram skill, semantic diagram patterns, layout grammars, and self-contained HTML/SVG output.

## Integration

Import it through the Agent Skills importer and expose a Jarvis capability:

`visual.diagram.render`

Supported output SHALL initially include:

- HTML/SVG source;
- SVG artifact;
- raster preview when local renderer is available.

## Extract/retain

Extract the useful visual grammar and semantic-pattern selection logic. Keep Jarvis's artifact system, task state, file paths, verification, and UI preview.

Do not create a separate diagram application/runtime.

## Rendering workflow

```text
user intent
  -> semantic diagram type selector
  -> diagram skill
  -> structured diagram spec
  -> HTML/SVG render
  -> validation
  -> artifact registration
  -> optional export
```

Validation SHOULD check broken labels/links, overflowing text, missing nodes, invalid SVG, and expected artifact existence.

Acceptance: Jarvis can request an architecture/sequence/data-flow/etc. diagram and produce a validated artifact through the normal task pipeline.

---

# 9. Anthropic Cybersecurity Skills — integrate as security skill pack

Source: `mukul975/Anthropic-Cybersecurity-Skills`  
Decision: **INTEGRATE — SECURITY PACK + METADATA EXTRACTION**.

This is a community project, not an Anthropic-owned project. It contains hundreds of Agent Skills across many security domains plus MITRE/NIST mappings.

## Integration boundary

The repository provides **procedural knowledge**, not execution authority.

Jarvis SHALL import:

- skill metadata;
- security-domain taxonomy;
- MITRE ATT&CK mappings;
- NIST CSF mappings;
- MITRE D3FEND/ATLAS/AI RMF/F3 metadata where present;
- step-by-step procedural skill content;
- references.

Actual commands/tools continue to run through Jarvis security workers and the Jarvis command/tool broker.

## Security module linkage

Install as a separately enableable Jarvis pack tied to the existing security module.

Suggested categories:

- blue team / SOC;
- DFIR;
- threat hunting;
- threat intelligence;
- vulnerability management;
- red team / pentest;
- cloud security;
- identity;
- malware analysis;
- AI/agent security;
- mobile;
- OT/ICS;
- DevSecOps;
- compliance/governance.

The skill discovery engine SHALL load only task-relevant skills.

## Useful subsystem extraction

The framework metadata is particularly valuable. Normalize framework IDs into Jarvis security findings so findings can link to:

```text
Finding
 |- ATT&CK techniques
 |- D3FEND countermeasures
 |- NIST CSF controls
 |- AI RMF / ATLAS where relevant
 `- supporting Jarvis skill/procedure
```

Acceptance: the security agent can discover relevant procedures by domain/framework while execution still obeys Jarvis's module/tool boundaries.

---

# 10. OpenViking — integrate as context sidecar and extract its best context ideas

Source: `volcengine/OpenViking`  
Decision: **INTEGRATE — SIDECAR + EXTRACT**.

OpenViking is particularly valuable for hierarchical context organization and retrieval. Its main repository is AGPLv3, so do not copy AGPL implementation code into Jarvis unless the project licensing strategy explicitly changes.

Use a process boundary.

## Sidecar adapter

Add `OpenVikingContextBackend` using the upstream local HTTP/SDK surface.

Responsibilities:

- index selected resources;
- retrieve hierarchical context;
- expose URI-based navigation;
- optional session compilation;
- optional resource summaries.

Jarvis remains authoritative for memory facts, tasks, policy, and skills.

## Extract concepts into native Jarvis

The following concepts are worth adopting independently:

### Hierarchical context URIs

Introduce stable Jarvis context URIs, e.g.:

```text
jarvis://resources/<project>/...
jarvis://reference/<vault>/...
jarvis://memory/<agent>/...
jarvis://skills/<pack>/...
```

### L0/L1/L2 context layers

Adopt layered context loading:

- **L0** — one-line abstract used for fast relevance checks;
- **L1** — overview/structure/usage summary;
- **L2** — complete underlying document/content.

This directly reduces context-window waste on local models.

### Hierarchical retrieval

Search directories/collections first, then descend only into promising areas rather than flat-vector searching every chunk.

### Memory candidate compare/merge/skip

When a session proposes durable memories, compare against current facts and choose create/merge/skip/conflict rather than blindly appending. Jarvis already has conflict/version logic; extend it with this candidate stage instead of replacing it.

### Context compiler

Add a bounded compiler that can turn selected source material into:

- wiki/reference pages;
- structured project summaries;
- relationship graph candidates;
- report drafts.

The output goes into the ReferenceStore or as memory candidates, not directly into hidden state.

## OpenViking + Obsidian relationship

Preferred design:

```text
Obsidian vault = source of truth for human-readable references
        |
        +--> Native lexical/index backend
        |
        `--> OpenViking index/summary sidecar
```

OpenViking may regenerate its index without risking loss of source material.

Acceptance: disabling/removing OpenViking leaves Jarvis and the Obsidian ReferenceStore functional; enabling it improves context retrieval without changing canonical ownership.

---

# 11. Obsidian Brain — integrate as the Jarvis ReferenceStore

Source: `Rob-Morris/obsidian-brain`  
Decision: **INTEGRATE — EXTRACT + COMPATIBLE VAULT + OPTIONAL ADAPTER**.

This is the preferred human-readable reference layer.

The strongest ideas to reuse are:

- plain Markdown local vault;
- living vs temporal artifacts;
- router document;
- taxonomy documents;
- linked graph of projects/decisions/sources;
- lexical search by default;
- optional local semantic search;
- explicit health/check/repair lifecycle;
- workspace-to-vault bindings;
- no proprietary data format.

## Do not make its runtime a hard Jarvis dependency

Jarvis SHALL implement an Obsidian-compatible ReferenceStore natively. Users may point it at:

- a Jarvis-managed vault;
- an existing Obsidian vault;
- an existing Obsidian Brain vault.

The external Brain runtime/MCP server can be supported through an adapter, but Jarvis MUST work directly against the Markdown files.

## Vault layout

Recommended Jarvis-managed layout:

```text
Jarvis Brain/
  _Config/
    router.md
    Taxonomy/
  _Temporal/
    Sessions/
    Research/
    Events/
  Projects/
  Decisions/
  People/
  Systems/
  Sources/
  Books/
  Security/
  Home/
```

Do not hard-code every category. Taxonomies remain extensible.

## Artifact types

Every document SHALL declare or infer:

- artifact id;
- type;
- `living` or `temporal`;
- created/updated timestamps;
- project/workspace links;
- source/provenance links;
- tags;
- optional related entities.

Living documents can be updated in place. Temporal documents are append-oriented historical evidence.

## Router + taxonomy extraction

Jarvis SHALL generate a lightweight router/index that lets local models discover the correct region of the vault without scanning it all. Taxonomy docs are loaded only when a task touches that type.

## Watch/index

Add filesystem watching and incremental reindexing. Human edits made in Obsidian must become visible to Jarvis without manual import.

## Health/repair

Add deterministic checks for:

- broken links;
- duplicate IDs;
- stale generated indexes;
- missing router entries;
- invalid frontmatter;
- orphaned workspace bindings.

Repairs should rebuild generated state without modifying user-authored note bodies unless explicitly requested.

Acceptance: the vault remains readable and useful with Jarvis completely stopped; Jarvis can rebuild all indexes from Markdown alone.

---

# 12. Awesome Harness Engineering — reference and systematic subsystem extraction

Reference candidate: `ai-boost/awesome-harness-engineering` plus relevant upstream projects it catalogs.  
Decision: **REFERENCE + CONTINUOUS EXTRACT**, not a runtime dependency.

This repository is a curated catalog rather than one coherent subsystem. Integrating the repo itself would add little value.

Instead create a design-review process:

1. track promising harness patterns/projects;
2. compare each against current Jarvis architecture;
3. extract only materially superior bounded subsystems;
4. write an ADR for any architecture-level adoption;
5. never replace the Jarvis control plane merely because another framework bundles similar features.

High-value pattern categories to continuously evaluate:

- context engineering;
- agent/tool contracts;
- durable execution;
- tracing and observability;
- evaluation loops;
- verifier patterns;
- retry/recovery strategies;
- capability discovery;
- MCP/tool isolation;
- local coding-agent harnesses;
- task decomposition;
- model routing.

This source should feed Jarvis architecture evolution, not become a dependency.

---

# 13. Unified retrieval architecture

After these integrations, Jarvis retrieval SHOULD use a two-stage process.

## Stage A — resource routing

Determine which stores matter:

- canonical memory;
- project/reference vault;
- skill library;
- trajectories;
- OpenViking hierarchical context;
- AgentMemory advisory coding recall.

Use task class, project/workspace id, entities, recency, and source authority.

## Stage B — ranked retrieval

Fuse bounded result sets rather than passing every source directly to the model.

Suggested score inputs:

```text
final_score =
  semantic_similarity
  + lexical_score
  + structural_relationship_score
  + project_affinity
  + recency_weight
  + confidence_weight
  + authority_weight
  - context_cost_penalty
```

The exact formula should be benchmark-driven.

Return L0 by default, L1 for shortlisted resources, and L2 only for the final selected context.

This is especially important for the local 9B/27B model profiles where context quality matters more than brute-force context length.

---

# 14. Skill execution architecture

Third-party skills SHALL compile into a Jarvis-native `ResolvedSkill` descriptor:

```python
class ResolvedSkill(BaseModel):
    id: str
    pack_id: str
    version: str
    source_commit: str
    summary: str
    instructions_uri: str
    reference_uris: list[str]
    required_tools: list[str]
    optional_tools: list[str]
    dependencies: list[SkillDependency]
    trust: str
    categories: list[str]
    metadata: dict[str, Any]
```

The agent receives only the selected skill's short metadata first. Full instructions load after selection.

Scripts shipped by a skill MUST execute through Jarvis workers/tool brokers and return evidence like any other tool action.

---

# 15. Dependency isolation

External integrations must not make the base installer fragile.

Use three dependency classes:

- **core** — required by Jarvis itself;
- **optional integration** — installed only when feature is enabled;
- **skill runtime** — installed on first use into an isolated environment or eligible worker node.

The installer/UI SHALL expose status:

```text
Available
Installed
Enabled
Healthy
Update available
Broken dependency
Unsupported on this node
```

A missing optional integration must never prevent Jarvis from starting.

---

# 16. Swarm behavior

All new capabilities register node requirements.

Examples:

```text
browser.agentic        -> desktop/browser capable node
reference.index        -> low/medium CPU worker
context.openviking     -> node hosting OpenViking sidecar
skill.scientific       -> node with requested Python/tool dependencies
visual.diagram.render  -> ordinary worker; browser renderer optional
security.skills        -> knowledge capability; execution depends on security worker
```

Node placement remains Jarvis-owned.

Heavy indexing can be placed on a Senior Worker, while the Obsidian Markdown vault can reside on the Orchestrator/storage node.

---

# 17. UI requirements

Add an **Integrations / Knowledge** surface showing:

- Obsidian/ReferenceStore location and health;
- indexed document count;
- OpenViking sidecar status;
- AgentMemory mode (`disabled`, `shadow`, `advisory`);
- installed skill packs;
- per-pack update/source commit;
- number of available/installed skills;
- dependency status;
- last index/update time;
- retrieval backend used for a task;
- context sources selected for a task.

Advanced diagnostics should allow a query to be run against each backend side-by-side to compare hits and latency.

---

# 18. Observability and provenance

Every external contribution to a task must be attributable.

Log:

- backend/provider id;
- source repo and pinned commit where applicable;
- skill id/version;
- context URI;
- retrieval score;
- authority class;
- tool/worker invoked;
- execution duration;
- failure/fallback;
- artifact hashes.

This is mandatory for debugging weaker local models: the system must make it possible to determine whether a bad result came from routing, retrieval, instructions, model quality, or tool execution.

---

# 19. Implementation order

## Phase 1 — common foundations

1. Add `ContextBackend` and Context Router.
2. Add `ReferenceStore` abstraction.
3. Add Obsidian-compatible native vault implementation.
4. Add `skill` resource type and Agent Skills importer.
5. Add source manifests, commit pinning, licensing metadata, health checks.

## Phase 2 — low-risk capability imports

6. Import Diagram Design.
7. Import Scientific Agent Skills.
8. Import Cybersecurity Skills as separately enabled security pack.
9. Complete Browser Use worker lifecycle and trace-to-procedure pipeline.

## Phase 3 — memory/context upgrades

10. Add native lexical/BM25 retrieval and rank fusion.
11. Add optional local embedding backend.
12. Add relationship/graph-aware retrieval.
13. Add L0/L1/L2 context summaries.
14. Add hierarchical context routing and stable `jarvis://` URIs.
15. Add memory candidate compare/merge/skip stage.

## Phase 4 — external comparison providers

16. Add AgentMemory sidecar adapter in shadow mode.
17. Benchmark native vs AgentMemory retrieval and extract any winning subsystem.
18. Add OpenViking sidecar adapter.
19. Index the Obsidian vault through OpenViking.
20. Benchmark hierarchical retrieval against native Jarvis retrieval.
21. Promote only demonstrably superior features into default routing.

## Phase 5 — continuous harness extraction

22. Add a tracked harness-engineering reference document.
23. Evaluate new patterns periodically during architecture work.
24. Implement each accepted pattern as a small RFC/ADR-bounded change.

---

# 20. Release gates

An integration cannot become default until:

- it has deterministic health/probe behavior;
- it has a native fallback when replacing/augmenting core behavior;
- failure does not corrupt canonical state;
- it respects local-first configuration;
- it records provenance;
- it is covered by automated tests;
- it passes dependency/install/uninstall/upgrade tests;
- it passes one-node operation tests;
- it does not bypass Jarvis policy/tool boundaries;
- benchmark evidence shows that its default-enabled portion materially improves Jarvis.

---

# 21. Non-negotiable invariants

1. **Jarvis remains the orchestrator.**
2. **Canonical memory remains Jarvis-owned.**
3. **Obsidian Markdown is the durable human-readable reference source, not hidden external DB state.**
4. **OpenViking and AgentMemory are replaceable context providers, not control planes.**
5. **Third-party skills provide knowledge; Jarvis provides execution and authority.**
6. **Playwright remains the deterministic browser path; Browser Use handles discovery/adaptation.**
7. **Successful agentic workflows should be promoted into cheaper deterministic procedures where possible.**
8. **External frameworks are decomposed. Only superior subsystems survive integration.**
9. **No optional integration may make base Jarvis unavailable when missing.**
10. **Every result must remain traceable to source, backend, skill, and evidence.**

---

# 22. Final repository decisions

| Project | Integration status | What Jarvis takes | What Jarvis keeps |
|---|---|---|---|
| Browser Use | integrate | adaptive browser discovery + agentic navigation | Playwright, policy, task state, verifier |
| AgentMemory | integrate bounded | hybrid retrieval ideas, hooks/adapters, optional advisory backend | canonical memory, versioning, provenance, conflicts, consolidation |
| Scientific Agent Skills | integrate | skills + metadata + tested procedures | Jarvis tool execution, dependency isolation, routing |
| Diagram Design | integrate | diagram grammars, skill, HTML/SVG templates | Jarvis artifact lifecycle and verification |
| Cybersecurity Skills | integrate | procedural library + security/framework mappings | Jarvis security module, tools, workers, policy |
| OpenViking | integrate | optional sidecar + hierarchical context concepts | canonical memory/reference authority and orchestrator |
| Obsidian Brain | integrate | vault/reference conventions, router/taxonomy, health patterns | Jarvis runtime; direct Markdown compatibility |
| Awesome Harness Engineering | reference/extract | superior individual harness patterns discovered through review | Jarvis architecture and control plane |

The intended result is not “Jarvis plus seven frameworks.” It is **one Jarvis architecture containing the best bounded pieces of each project behind Jarvis-owned interfaces**.
