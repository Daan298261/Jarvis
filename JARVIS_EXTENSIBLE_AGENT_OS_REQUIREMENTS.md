# Jarvis Extensible Agent OS, Specialist Packs, Dashboard & Offline Licensing Requirements

Status: **separate long-term product specification** referenced by `JARVIS_MASTER_PLAN.md`.

This document is the authoritative requirements spec for evolving Jarvis from a single local agent into an extensible autonomous AI operating layer with ZoeyOS-style persistent specialist teams and FounderOS-style business autonomy, departments, workflows, and approval logic — while remaining local-first, model-agnostic, and fully owner-controllable.

Priority mapping (see §41 and §81 in this file):

- **P1 — Owner control / core UX:** Agent Profiles, configuration editor, Systems Registry, modular Home Dashboard, Decision Inbox, Safe Mode, STOP AUTONOMY.
- **P2 — Organization & knowledge:** Workspaces, Departments, Team Chat, Shared Brain, Skill Manager, Goals/KPI engine.
- **P3 — Automation:** Workflow builder, event bus, Away Mode, Morning Brief, temporary agents.
- **P4 — Intelligence:** Specialist Packs, Model Registry, hybrid routing, cost/privacy governor.
- **P5 — Swarm:** multi-node execution, live execution map, resource policies (complements `SWARM_ARCHITECTURE.md`).
- **P6 — Commercial platform:** signed offline licensing, Pack subscriptions, Marketplace, portals.

Do not start P1–P6 implementation ahead of active P0–P3 master-plan work unless the Development Queue or user explicitly promotes it. Implementation tickets should be split into small RFCs under `docs/rfcs/` rather than landing wholesale in the master plan.

Related specifications:

- [`SWARM_ARCHITECTURE.md`](SWARM_ARCHITECTURE.md) — node/worker placement, resource control, multi-node execution.
- [`ADAPTIVE_DOMAIN_ARCHITECTURE.md`](ADAPTIVE_DOMAIN_ARCHITECTURE.md) — adaptive intelligence, domain packs, business workflows.

---

## 1. Product objective

Jarvis shall evolve from a single local AI agent into an extensible autonomous AI operating layer supporting:

- persistent specialist agents;
- multi-agent delegation;
- full user-visible/editable agent configuration;
- local, swarm and cloud inference;
- specialist AI models;
- installable Domain/Specialist Packs;
- recurring autonomous workflows;
- configurable authority and approval levels;
- Decision Inbox;
- Away Mode;
- cost/privacy/resource governance;
- physical multi-node compute scheduling;
- paid first-party add-ons;
- third-party/user-created add-ons;
- online and offline subscription validation;
- cluster-wide entitlement enforcement.

Jarvis shall remain usable as a one-node system.

Additional hardware shall increase available capability rather than being required for basic operation.

---

## 2. Core design principle

Jarvis is not an LLM.

Jarvis is the operating, orchestration and policy layer around:

- models;
- agents;
- workers;
- tools;
- workflows;
- integrations;
- memory;
- physical compute nodes.

Models shall be replaceable resources.

Agent identities and responsibilities shall NOT be permanently tied to one model or one physical machine.

---

## 3. Product layers

Jarvis shall implement four distinct layers.

### 3.1 Jarvis Core

Core functionality includes:

- Orchestrator;
- task engine;
- memory;
- scheduler;
- Decision Inbox;
- Agent Manager;
- tool framework;
- integrations framework;
- workflow engine;
- model router;
- node/resource scheduler;
- audit system;
- permissions;
- cost governor;
- configuration system;
- pack manager.

### 3.2 Specialist Packs

Examples:

- Blue Team
- Ad Studio
- SEO Autopilot
- Developer
- Publishing
- Research
- Social Manager
- Sales
- Forensics Pro

Indicative commercial pricing may be approximately €9.99/month per normal specialist pack, but pricing MUST NOT be hard-coded in the client.

Higher-value packs may use different pricing.

### 3.3 Model Packs

Optional specialized models may be installed.

Examples:

- cybersecurity model;
- coding model;
- marketing model;
- SEO model;
- document model;
- embedding model;
- reranker;
- vision model;
- LoRA/adapter.

A Specialist Pack does NOT require a dedicated model.

A Specialist Pack may use:

- general local model;
- specialist local model;
- remote swarm model;
- customer-provided API;
- commercial cloud model;
- combination of these.

### 3.4 Compute layer

Compute may originate from:

- current machine;
- another Jarvis node;
- dedicated GPU server;
- CPU-only worker;
- Raspberry Pi;
- laptop;
- remote server;
- customer cloud;
- commercial AI API.

---

## 4. Specialist Pack architecture

Every Specialist Pack shall use a standard manifest.

Minimum metadata:

```text
pack_id
name
version
publisher
description
required_core_version
entitlement_id
dependencies
agent_definitions
model_requirements
recommended_models
tool_requirements
integration_requirements
workflow_definitions
memory_schema
UI_extensions
permission_requirements
default_authority
resource_requirements
evaluation_suite
license
commercial_use
redistribution_rights
package_signature
package_hash
```

Jarvis shall reject invalid or tampered signed packages.

User-created local packs do not require a paid entitlement.

Jarvis MUST allow users to build their own agents/packs without paying for a first-party specialist pack.

Paid packs sell curated specialist capability, workflows, models, updates and support rather than restricting basic customization.

---

## 5. Agent Profiles

Jarvis shall introduce first-class persistent Agent Profiles.

Examples:

```text
Alex
Software Lead

Sarah
Publishing Manager

Max
Research Analyst

Emma
Marketing Manager

Sentinel
Blue Team Analyst
```

An Agent Profile contains:

- name;
- icon/avatar;
- description;
- mission;
- responsibilities;
- domain/workspace;
- system prompt;
- behavioral instructions;
- skills;
- workflows;
- tool permissions;
- integration permissions;
- filesystem access;
- memory access;
- context access;
- model policy;
- cloud policy;
- authority level;
- financial authority;
- resource policy;
- preferred node;
- node restrictions;
- schedules;
- event triggers;
- escalation policy;
- verifier;
- reporting rules;
- notification rules.

Agent identity shall remain independent of the Worker/Node performing execution.

---

## 6. Agent Configuration UI

Jarvis MUST provide a dedicated **Agents** screen.

The user shall be able to see every configured Agent Profile.

Suggested layout:

```text
AGENTS

Alex              Software Lead        ACTIVE
Emma              Marketing Manager    ACTIVE
Sentinel          Blue Team            ACTIVE
Sarah             Publishing           SCHEDULED
Max               Research             ACTIVE

[ + Create Agent ]
[ Import Agent ]
[ Install Specialist Pack ]
```

Selecting an agent opens a complete configuration editor.

---

## 7. Agent Configuration Editor

The editor shall contain the following tabs.

### General

- Name
- Icon
- Description
- Mission
- Workspace/domain
- Enabled/disabled

### Instructions

- Complete agent instructions
- Complete first-party system prompt
- Behavioral instructions
- Output requirements
- Escalation instructions

The first-party Jarvis agent configuration MUST NOT be hidden from the owner.

### Models

- Primary model
- Preferred model
- Specialist model
- Expert escalation model
- Verification model
- Local/cloud preferences
- Context size
- temperature/reasoning settings where supported

### Tools

Every available tool displayed individually:

```text
Filesystem       READ / WRITE / DENY
Terminal         ALLOW / APPROVAL / DENY
Browser          ALLOW
Git              ALLOW
Email            READ / WRITE WITH APPROVAL
Calendar         ALLOW
Desktop          ALLOW
Docker           DENY
```

### Memory

- Workspace memory access
- Global memory access
- Private memory namespaces
- Write permission
- Retention policy
- Retrieval configuration

### Context

Show exactly which information sources the agent may access.

Examples:

- project documents;
- Git repositories;
- email;
- Drive;
- website;
- databases;
- other agents;
- shared Brain memory.

### Authority

Set authority per action/category.

### Integrations

Display every integration accessible to the agent and its exact scopes.

### Automation

- schedules;
- triggers;
- recurring jobs;
- Away Mode eligibility;
- idle-time work;
- event-driven jobs.

### Compute

- preferred node;
- preferred GPU;
- minimum VRAM;
- local-only;
- cloud allowed;
- priority;
- CPU/RAM/GPU caps.

### Costs

- max cost/task;
- daily budget;
- monthly budget;
- purchase authority;
- API authority.

### Verification

- independent verifier;
- acceptance criteria;
- confidence threshold;
- retry count;
- escalation rules.

### Advanced

Full raw configuration editor.

Support:

- JSON;
- YAML;
- schema validation;
- export;
- import.

---

## 8. User/Jarvis configuration authority

The user is the ultimate configuration authority.

Jarvis may also modify its own agent configuration only when explicitly permitted.

Every editable field shall support:

```text
USER CONTROLLED
JARVIS MAY MODIFY
LOCKED BY USER
INHERITED
PACK DEFAULT
```

Users shall be able to lock individual configuration fields against Jarvis modification.

Every Jarvis-created configuration change MUST:

- be logged;
- contain reason;
- contain previous value;
- contain new value;
- identify initiating agent;
- be timestamped;
- support rollback.

The UI shall provide:

- Configuration History
- Restore Previous Version

No first-party Specialist Pack may silently change user overrides.

---

## 9. Authority levels

Implement:

```text
A0 OBSERVE
A1 RECOMMEND
A2 ACT WITH APPROVAL
A3 ACT AND REPORT
A4 AUTONOMOUS WITHIN POLICY
A5 AUTONOMOUS + INDEPENDENT VERIFICATION
```

Authority MUST support per-action overrides.

Hard restrictions override agent autonomy.

---

## 10. Decision Inbox

Jarvis shall aggregate human-required decisions.

Decision records shall contain:

- requesting agent;
- action;
- reason;
- evidence;
- confidence;
- risk;
- estimated cost;
- reversibility;
- recommended action.

Supported controls include:

- Approve
- Reject
- Inspect
- Approve once
- Change limit
- Override recommendation

---

## 11. Guided Agent/Business Interview

Users shall not need to manually write large prompts.

Jarvis shall provide an interview system that asks:

- What are you trying to accomplish?
- What is this agent responsible for?
- What decisions require your approval?
- What may it do autonomously?
- What must it never do?
- What constitutes good work?
- What common mistakes should it avoid?
- What sources should it trust?
- What data is private?
- What may leave the network?
- How much may it spend?
- When should it notify you?
- What tools/accounts belong to this role?

The output shall generate structured:

- Agent Profiles;
- Workspace Profiles;
- policy;
- workflows;
- permissions;
- memory seeds;
- escalation rules;
- authority;
- cost policy.

---

## 12. Multi-agent functionality

Implement functionality comparable where useful to Zoey/FounderOS-style systems:

- named persistent AI specialists;
- agent-to-agent delegation;
- team conversations;
- task decomposition;
- temporary task agents;
- shared project memory;
- independent specialist memory;
- reusable workflows;
- scheduling;
- background work;
- Away Mode;
- approval levels;
- exception escalation;
- decision logging;
- morning briefing;
- live execution visualization;
- integration framework;
- shareable specialist packs;
- eventually marketplace distribution.

Temporary agent spawning must have configurable limits:

```text
Max child agents/task
Max hierarchy depth
Max simultaneous agents
Max runtime
Max compute budget
Max cloud budget
```

---

## 13. Hybrid inference

Provide four primary routing modes:

```text
LOCAL ONLY
LOCAL FIRST
BEST RESULT
COST OPTIMIZED
```

### LOCAL ONLY

No inference data leaves user infrastructure.

### LOCAL FIRST

Attempt appropriate local/swarm model first. Escalate only when policy permits.

### BEST RESULT

Select best permitted model for task.

### COST OPTIMIZED

Select lowest-cost model likely to satisfy required quality.

---

## 14. Model Router

The router shall consider:

- task type;
- model capability;
- expected quality;
- context requirement;
- latency;
- VRAM;
- available nodes;
- data privacy;
- user preference;
- financial cost;
- current load;
- warm model availability;
- historical success rate.

---

## 15. Specialist Model Registry

Add **Models → Specialist Models**.

Each model record shall contain:

- model ID;
- source;
- architecture;
- quantization;
- parameter count;
- context;
- VRAM requirements;
- recommended roles;
- benchmark results;
- commercial-use permission;
- redistribution permission;
- source license;
- checksum;
- installed nodes;
- current version.

Jarvis MUST NOT redistribute models whose licenses do not permit redistribution.

Adapters/LoRAs shall be supported.

---

## 16. Cost Governor

Autonomous agents MUST NOT have unlimited spending ability.

Implement:

```text
Max inference/task
Max inference/day
Max inference/month
Max purchase/action
Max ad change
Max refund
Max workflow expenditure
```

Hard financial limits cannot be overridden by model reasoning.

---

## 17. Privacy Governor

Per workspace/agent:

```text
Allow cloud prompts               YES/NO
Allow source code                 YES/NO
Allow private documents           YES/NO
Allow PII                         YES/NO
Allow anonymized excerpts         YES/NO
```

A cloud model call shall be blocked if required content violates policy.

---

## 18. Live Execution Map

Create an execution visualization showing:

- parent task;
- child tasks;
- assigned Agent;
- Worker;
- Node;
- model;
- GPU/CPU/RAM;
- duration;
- tokens;
- estimated cost;
- authority;
- tools used;
- evidence;
- current state.

---

## 19. Away Mode

Away Mode shall permit unattended operation within policy.

Configuration includes:

- allowed agents;
- allowed workloads;
- schedule;
- maximum concurrency;
- resource caps;
- cloud spending;
- financial authority;
- notification criteria;
- actions requiring approval.

---

## 20. Morning Brief

Generate a consolidated report containing:

- completed work;
- failures;
- recovered failures;
- decisions waiting;
- business metrics;
- project progress;
- security events;
- infrastructure status;
- API spending;
- estimated human time saved.

Track **Human Time Saved** as a first-class metric.

---

## 21. Specialist Pack examples

### Blue Team — example €9.99/month

May contain:

- Blue Team agent/team;
- security model policy;
- log analysis;
- Wazuh integration;
- Syslog;
- Windows Event Logs;
- IOC enrichment;
- CVE research;
- asset inventory;
- alert correlation;
- incident timeline;
- security briefing;
- defensive recommendations;
- automated triage.

### Ad Studio — example €9.99/month

- Campaign Strategist;
- Copywriter;
- Audience Researcher;
- image generation;
- A/B variants;
- Meta/Google workflows;
- performance analysis;
- brand memory;
- ad budget policy.

### SEO Autopilot — example €9.99/month

- keyword research;
- competitor research;
- content gaps;
- content calendar;
- article generation;
- internal linking;
- SEO scoring;
- metadata;
- schema;
- image generation;
- CMS publishing;
- rank monitoring.

### Developer

- repo analysis;
- issue triage;
- branch creation;
- coding;
- testing;
- PR creation;
- verification;
- deployment approval.

### Publishing

- manuscript management;
- continuity tracking;
- editing workflows;
- translation;
- release management;
- ARC workflows;
- review monitoring;
- marketing coordination.

### Additional future packs

- Social Manager
- Sales
- Research
- Forensics Pro
- Finance
- Home Automation
- Real Estate
- MSP Operations
- Customer Support

---

## 22. Licensing architecture

The subscription system MUST NOT rely solely on the editable operating-system clock.

Use a **Cryptographically Signed Offline Lease**.

The licensing server issues a signed entitlement document.

Suggested fields:

```text
license_id
customer_id
cluster_id
plan
entitlements[]
node_limit
issued_at_utc
last_verified_utc
offline_valid_until_utc
subscription_state
lease_id
nonce
signature
key_id
```

Use modern asymmetric signing such as Ed25519.

Jarvis clients contain only the verification public key.

The private signing key remains exclusively on licensing infrastructure.

---

## 23. Cluster identity

Do not primarily bind licenses to invasive hardware fingerprints.

On installation:

```text
Jarvis Cluster
    ↓
generate cryptographic keypair
    ↓
cluster_id
```

Each Node also generates a keypair.

The licensing service registers:

```text
Customer
License
Cluster
Authorized Node Public Keys
```

Hardware may be replaced without destroying the customer's license.

Lost nodes may be revoked.

---

## 24. Offline subscription lease

Each subscription defines:

```text
offline_grace_days
```

Recommended initial default:

```text
7 days
```

Possible plans:

```text
Normal subscription     7 days
Pro                     14 days
Enterprise              30–90 days
Air-gapped Enterprise   signed manual lease
```

When online, Jarvis should verify approximately daily.

If verification succeeds, a new signed offline lease is issued.

If internet disappears, Jarvis remains functional until `offline_valid_until_utc`.

Warnings should appear before expiry.

---

## 25. Trusted time architecture

Jarvis shall maintain an internal trusted-time high-water mark.

Never rely on timezone/local time.

All licensing calculations use UTC.

Store:

```text
last_trusted_server_utc
last_seen_wall_clock_utc
highest_seen_utc
monotonic_elapsed
boot_id
lease_id
event_hash
```

Create append-only `trusted_time_events`.

Events shall be written on:

- application start;
- periodic heartbeat;
- license verification;
- license-sensitive actions;
- clean shutdown;
- node join;
- entitlement update.

---

## 26. Tamper-resistant timestamp storage

The trusted high-water mark shall be stored in multiple locations:

1. Jarvis database;
2. operating-system secure storage;
3. encrypted local entitlement cache.

Where possible use:

- TPM;
- Windows DPAPI;
- macOS Keychain;
- Linux secret/keyring mechanisms.

The DB record shall use a hash chain/tamper-evident history.

Do not trust ordinary filesystem modified timestamps.

---

## 27. System-time rollback detection

On application startup and periodically compare current wall time against trusted high-water time.

If:

```text
current_wall_time < trusted_high_water_time - allowed_clock_tolerance
```

enter `TIME_TAMPER`.

Suggested tolerance: 5 minutes.

Timezone/DST changes MUST NOT trigger this because calculations use UTC.

Example user message:

> Tampered system time detected. Jarvis has disabled licensed functionality to protect the subscription state. Please connect this system to the internet for automatic license and secure-time verification, or contact support for offline recovery.

---

## 28. Monotonic-clock protection

During a single boot/session, Jarvis shall additionally use the operating system's monotonic clock.

Store:

```text
startup_wall_time
startup_monotonic
```

Expected wall time can therefore be calculated independently during that boot.

Large divergence triggers time verification.

---

## 29. License state machine

Implement explicit states:

```text
VALID
OFFLINE_GRACE
VERIFY_REQUIRED
TIME_TAMPER
SUBSCRIPTION_INACTIVE
LICENSE_REVOKED
RECOVERY
```

### VALID
All entitled functions operate.

### OFFLINE_GRACE
Functions operate; UI displays remaining offline period.

### VERIFY_REQUIRED
Paid execution stops. License/network/settings/data access remain available.

### TIME_TAMPER
Licensed execution stops cluster-wide. User data and recovery tools remain accessible.

### SUBSCRIPTION_INACTIVE
Paid features disabled.

### LICENSE_REVOKED
Paid execution disabled immediately after receiving valid revocation.

---

## 30. Do not destroy or ransom user data

Even under license failure, users MUST retain:

- read-only access to their data;
- export;
- backups;
- configuration viewing;
- license settings;
- network settings;
- recovery functionality.

Do NOT encrypt or hold customer data hostage because a subscription expired.

"Lockdown" means disabling paid execution capabilities, not making user-owned information inaccessible.

---

## 31. Cluster-wide enforcement

The Orchestrator shall distribute signed entitlement state to Nodes.

Nodes MUST independently validate entitlement signatures.

Before accepting paid work:

```text
Node
 ↓
verify signature
 ↓
verify entitlement
 ↓
verify lease
 ↓
verify trusted time
 ↓
execute
```

If the cluster license becomes invalid, broadcast `LICENSE_LOCK` and stop licensed execution across nodes.

Disconnected Nodes continue only until their locally signed lease expires.

---

## 32. Online recovery flow

When connectivity becomes available:

```text
TIME_TAMPER / VERIFY_REQUIRED
        ↓
Contact licensing server
        ↓
TLS connection
        ↓
Receive signed trusted server time
        ↓
Verify subscription
```

If subscription is active:

- issue new signed lease;
- update trusted time;
- update high-water mark;
- synchronize cluster entitlement;
- attempt OS time synchronization;
- restore functions.

Display an OK screen confirming:

- License verified
- Subscription active
- Secure time verified
- All entitled Jarvis functions restored

If subscription is inactive, enter `SUBSCRIPTION_INACTIVE` and disable paid execution across all Nodes.

---

## 33. Time synchronization

Do not make unauthenticated NTP the sole license authority.

Trusted subscription time comes from a cryptographically authenticated licensing-server response.

When online Jarvis SHOULD also attempt system-clock correction using:

- native OS time service;
- NTS where available;
- trusted configured time servers.

Examples:

```text
Windows Time
systemd-timesyncd
chrony
```

If Jarvis cannot change system time:

- continue using trusted-server-time offset internally;
- display warning that the OS clock remains incorrect;
- do not unnecessarily keep the customer locked after successful paid verification.

---

## 34. Air-gapped/offline customers

Provide a legitimate long-term offline mode.

Workflow:

```text
Jarvis generates Offline License Request
        ↓
User transfers request to internet-connected device
        ↓
License portal verifies subscription
        ↓
Portal generates signed offline activation file
        ↓
User imports file into Jarvis
```

The file may grant 30, 90, 365 days or another plan-defined duration.

This is important for:

- security environments;
- forensic labs;
- isolated networks;
- industrial systems;
- privacy-sensitive businesses.

---

## 35. Licensing UI

Create **Settings → License & Entitlements**.

Display:

```text
Plan
Status
Last online verification
Offline operation permitted until
Offline time remaining
Nodes used / node limit
Installed entitlements
```

Actions:

```text
[Verify Now]
[Sync Time]
[Manage Subscription]
[Export Offline Request]
[Import Offline License]
[View Licensed Nodes]
```

---

## 36. Add-on entitlement enforcement

The signed lease includes `entitlements[]`.

Example:

```text
jarvis.core.pro
pack.blue_team
pack.ad_studio
pack.developer
```

Installed but unlicensed packs remain visible but disabled.

Pack configuration and user data shall NOT be deleted when entitlement expires.

After renewal, functionality resumes.

---

## 37. Marketplace architecture

Future Marketplace should support:

- first-party packs;
- verified third-party packs;
- community/free packs;
- private enterprise packs;
- user-local packs.

Commercial model may support configurable revenue sharing.

Packages require:

- manifest;
- permission declaration;
- signature;
- version;
- compatibility;
- license;
- security scan.

---

## 38. Security boundary

Neither Jarvis agents nor normal userspace configuration may directly alter:

- signed entitlement tokens;
- vendor signing keys;
- secure time high-water state;
- license verification results;
- package signatures.

Agent autonomy cannot modify licensing state.

---

## 39. Auditing

Create unified append-only audit events for:

- agent configuration changes;
- authority changes;
- model changes;
- financial limit changes;
- pack installation;
- pack entitlement changes;
- license checks;
- time anomalies;
- node registration;
- node revocation;
- autonomous action;
- approvals;
- denials;
- cloud calls;
- external spending.

Each event includes:

```text
event_id
utc_timestamp
actor
agent
node
action
previous_state
new_state
reason
task_id
hash
```

---

## 40. Required acceptance tests

### Agent configuration

- User can inspect all Agent Profile configuration.
- User can edit all non-security-invariant fields.
- User can lock fields against Jarvis modification.
- Jarvis changes are versioned.
- User can roll back changes.
- Effective configuration shows inheritance/source.

### Specialist Packs

- Pack can install.
- Entitlement controls execution.
- Disabling entitlement does not delete data.
- Pack can specify recommended model.
- Pack functions without specialized model using fallback where supported.
- User-created packs work without commercial entitlement.

### Hybrid inference

- Local Only never transmits inference externally.
- Local First escalates only when permitted.
- Cost limits stop excessive cloud usage.
- Privacy policy prevents forbidden data transmission.

### Offline license

- Valid lease works without internet.
- Application continues normally during permitted grace period.
- After grace expires, verification is required.
- Licensing-server outage does not immediately lock valid leases.

### Time manipulation

- Move system time backward one day → TIME_TAMPER.
- Move timezone → no false positive.
- DST change → no false positive.
- Small clock drift within tolerance → no lock.
- Change clock during running session → monotonic check detects divergence.
- Delete/modify DB while secure high-water state remains → recovery/tamper state.

### Recovery

- Connect valid paid subscription → new lease generated.
- Trusted time restored.
- Cluster entitlement propagated.
- All entitled Nodes resume.
- User receives successful verification screen.

### Unpaid subscription

- Verification reports inactive.
- Licensed execution stops across cluster.
- Data remains accessible/exportable.
- Subscription screen remains usable.
- Renewal immediately restores entitlement after verification.

### Multi-node

- Node independently verifies signed entitlement.
- Disconnected Node can operate only until its lease expiry.
- Revoked/unlicensed Nodes cannot execute paid jobs.
- Adding Nodes beyond subscription limit is rejected.

---

## 41. Initial implementation priority

### P1 — Control and configuration

- Agent Profiles
- Agent Configuration UI
- authority levels
- configuration versioning
- user locks
- Decision Inbox
- cost/privacy governor

### P2 — Specialist platform

- Pack manifest
- Pack Manager
- Model Registry
- specialist model routing
- Blue Team prototype
- Ad Studio prototype
- guided behavior interview

### P3 — Autonomous operation

- Away Mode
- Morning Brief
- Live Execution Map
- agent delegation
- temporary agents
- advanced workflow engine

### P4 — Commercial licensing

- licensing service
- cluster identities
- signed entitlement leases
- secure timestamp store
- offline grace
- time-tamper detection
- entitlement UI
- cluster-wide enforcement
- offline activation files

### P5 — Ecosystem

- third-party Packs
- Marketplace
- developer SDK
- revenue sharing
- shareable portals
- enterprise private repositories

---

## 42. Product principle

Jarvis must provide more control than competing AI operating systems.

The user should always be able to answer:

- Which agent did this?
- Why did it do it?
- Which model was used?
- What information did it see?
- Which tools did it use?
- Which computer performed it?
- What did it cost?
- What authority did it have?
- What exact configuration caused this behavior?
- Can I change that behavior?
- Can I prevent Jarvis from changing it?
- Can I roll it back?

Jarvis should therefore be:

**Autonomous when desired. Transparent by default. Fully controllable by its owner.**

---

## 43. Organizational Hierarchy

Jarvis shall support configurable organizational structures above individual Agent Profiles.

Default hierarchy:

```text
Workspace
    ↓
Department / Team
    ↓
Lead Agent
    ↓
Specialist Agents
    ↓
Temporary Task Agents
```

The user may:

- create/delete departments;
- move agents between teams;
- nominate/change team leads;
- remove hierarchy entirely;
- permit Jarvis to reorganize agents automatically;
- lock organizational structure against Jarvis changes.

Departments are logical structures and MUST NOT dictate physical Node placement.

---

## 44. Team Chat

Jarvis shall support conversations involving multiple persistent agents.

Users may directly address agents, teams or departments.

Jarvis may automatically involve relevant agents when permitted.

Team Chat must show:

- which agent is speaking;
- which agent received a delegated task;
- task relationships;
- conclusions;
- disagreements;
- decisions requiring the user.

Agent-to-agent chatter SHOULD be summarized where raw discussion provides little value.

The user shall be able to inspect detailed execution when desired.

---

## 45. Temporary Agent Spawning

Persistent agents may create temporary specialist agents for individual tasks.

Temporary agents MUST inherit hard restrictions from their parent and may never silently gain broader permissions.

Configurable limits include:

```text
Maximum child agents/task
Maximum simultaneous agents
Maximum hierarchy depth
Maximum runtime
Maximum compute budget
Maximum cloud budget
```

Temporary agents normally terminate when their task is completed.

---

## 46. Skill Manager

Create a dedicated **Skills** screen.

A Skill represents reusable operational knowledge or a proven procedure.

The Skill Manager shall display:

```text
Skill
Version
Owner
Agents using it
Success rate
Executions
Last used
Source
Locked
```

Users may:

- inspect skills;
- edit skills;
- create skills;
- duplicate skills;
- disable skills;
- export/import skills;
- assign skills to agents;
- view execution history;
- restore older versions.

Jarvis may suggest/create/improve skills where authorized.

User-locked Skills cannot be modified by Jarvis.

---

## 47. Workflow / State-Machine Builder

Jarvis shall provide a visual workflow builder.

Supported workflow elements:

- trigger;
- action;
- agent task;
- deterministic tool action;
- condition;
- branch;
- timer;
- delay;
- human approval;
- loop;
- retry;
- parallel branch;
- join;
- exception handler;
- verifier;
- notification;
- completion state.

Workflows shall be:

- editable by the user;
- generatable by Jarvis;
- versioned;
- exportable/importable;
- testable in simulation mode.

Jarvis-generated workflows MUST remain fully editable.

---

## 48. Goals and KPI Engine

Workspaces, Departments and Agents may have Goals.

Each Goal may contain:

```text
goal_id
description
owner
metric
target
baseline
deadline
priority
status
progress
allowed_actions
budget
```

Jarvis may autonomously generate tasks intended to advance Goals when permitted.

The user must be able to see:

- current value;
- target;
- trend;
- responsible agents;
- recent actions;
- blockers;
- forecast.

---

## 49. Agent Team Templates

Specialist Packs may contain complete Agent Teams rather than only one agent.

Examples include Publishing Team and Blue Team templates.

Users may:

- install entire team;
- install selected agents;
- delete pack agents;
- change prompts;
- change models;
- change tools;
- move them between teams;
- replace agents with user-created agents.

First-party packs do NOT override owner control.

---

## 50. Shared Brain / Knowledge Manager

Create a dedicated **Knowledge** screen exposing what Jarvis believes it knows.

Categories:

```text
Facts
Preferences
People
Organizations
Projects
Business Rules
Decisions
Terminology
Locations
Assets
Policies
Brand Information
Historical Events
Learned Procedures
```

Every knowledge object should expose:

```text
Content
Source
Created
Last confirmed
Confidence
Agents with access
Workspace
Locked
Expiry/retention
```

Users may edit, correct, delete, lock, move, restrict, expire and confirm knowledge.

Jarvis may propose knowledge changes.

High-impact changes SHOULD require approval.

---

## 51. Cross-Agent Shared Objects

Agents should preferably collaborate through canonical structured objects rather than passing large conversation histories.

Supported shared objects should eventually include:

- Task
- Project
- Document
- Manuscript
- Campaign
- Customer
- Lead
- Issue
- Pull Request
- Security Incident
- Research Report
- Decision
- Goal
- Asset
- Calendar Event
- Order
- Website Article

---

## 52. Proactive Agent Suggestions

Agents may identify useful work without an explicit user request.

Suggestion policies shall support:

```text
DISABLED
SILENT LOG
HOME DASHBOARD
NOTIFY
AUTOMATIC ACTION
```

The user may configure these per Agent/System.

---

## 53. Event-Driven Automation

Jarvis shall support events in addition to scheduled automation.

Examples:

```text
Email received
GitHub issue opened
Pull request failed
Order received
New review discovered
Website traffic anomaly
Security alert generated
File changed
Device joins network
Node becomes unavailable
Campaign exceeds budget
Goal falls behind schedule
```

Generic architecture:

```text
Event
  ↓
Event Bus
  ↓
Policy
  ↓
Workflow
  ↓
Agent / Tool / Decision Inbox
```

Events MUST contain normalized timestamps and source metadata.

---

## 54. Workspace Manager

Create first-class isolated Workspaces.

Each Workspace maintains independent:

- context;
- Brain/knowledge;
- Agents;
- Departments;
- files;
- workflows;
- goals;
- integrations;
- permissions;
- budgets;
- dashboards;
- automation.

Cross-workspace access is denied unless explicitly permitted.

Create a persistent Workspace Switcher in the UI.

---

## 55. Client and Team Portals

Future Jarvis versions should allow restricted portals containing selected project status, reports, approvals, documents, agent outputs and messages.

Portal users MUST NOT automatically gain access to:

- Jarvis administration;
- other Workspaces;
- system configuration;
- infrastructure;
- internal agent memory;
- private tools.

Access uses explicit roles/scopes.

---

## 56. Pack Marketplace UX

Create a **Marketplace** supporting categories such as Security, Marketing, Development, Publishing, Research, Sales, Finance, Home Automation, Productivity, Models, Skills and Workflows.

Every Pack page shows:

- included Agents;
- included Skills;
- included workflows;
- included models;
- required integrations;
- requested permissions;
- hardware requirements;
- cloud requirements;
- subscription price;
- publisher;
- ratings;
- update history.

Before installation show an explicit permission summary.

Support:

- free packs;
- subscriptions;
- one-time purchases;
- trials;
- private packs;
- enterprise packs.

---

## 57. Pack Trial Mode

Commercial Packs should support configurable trials such as:

```text
7 days
10 executions
30 generated advertisements
1 completed project
```

Trial state is represented through the existing signed entitlement architecture.

Pack data survives trial expiry.

---

## 58. Home Dashboard System Modules

The Jarvis Home screen shall be modular.

Every major Jarvis subsystem may expose a **System Module Card**.

A System Module is different from an Agent. A System represents a functional capability or service.

Examples:

```text
Publishing
Translation
Marketing
Blue Team
SEO
Developer
Research
Infrastructure
Memory
Automations
Swarm
Website
Social Media
Orders
Licensing
```

Each system may register a Home Dashboard Module.

---

## 59. System Module Registry

Create a central `SystemRegistry`.

Each System registers:

```text
system_id
name
description
icon
category
enabled
runtime_state
home_visible
home_position
home_size
metrics[]
outputs[]
actions[]
dependencies[]
agents[]
nodes[]
entitlement
health
last_activity
```

System Cards MUST use this registry rather than bespoke hard-coded dashboard implementations.

---

## 60. Home Dashboard Customization

The user shall have complete control over the Home screen.

Support:

- show system;
- hide system;
- enable system;
- disable system;
- pause system;
- resume system;
- rearrange system cards;
- resize cards;
- pin priority cards;
- collapse detail;
- select displayed metrics.

Example metrics:

```text
Publishing
ACTIVE
English words: 82,413
Dutch translated: 100%
Manuscripts active: 2

Translation
ACTIVE
EN → NL: 82,413 / 82,413
Completion: 100%
Errors requiring review: 3

Blue Team
ACTIVE
Alerts today: 12
Critical: 0
Auto-resolved: 9
Needs review: 3
```

---

## 61. Standard System States

All systems shall expose standardized states:

```text
ENABLED
RUNNING
IDLE
PAUSED
DISABLED
STARTING
STOPPING
DEGRADED
ERROR
WAITING_APPROVAL
LICENSE_REQUIRED
OFFLINE
NOT_INSTALLED
UPDATE_AVAILABLE
DEPENDENCY_ERROR
```

---

## 62. Enable / Disable Semantics

Hide and Disable MUST be distinct concepts.

### Hide

Hides the system from Home. The system continues operating.

### Disable

Stops the functional system. Historical data remains accessible.

### Pause

Temporarily suspends new autonomous work.

### Emergency Stop

For critical systems provide `STOP NOW`, cancelling eligible active work immediately.

---

## 63. User and Jarvis System Control

Every System shall support a control policy:

```text
USER ONLY
JARVIS MAY ENABLE
JARVIS MAY PAUSE
JARVIS FULL CONTROL
LOCKED ENABLED
LOCKED DISABLED
```

Jarvis may recommend state changes but cannot override user locks.

---

## 64. Dashboard Metrics Framework

Systems shall expose metrics through a standard interface.

Metric types:

```text
COUNTER
GAUGE
PERCENTAGE
RATE
DURATION
CURRENCY
STATUS
PROGRESS
TIMESTAMP
TREND
```

Example Publishing metrics:

```text
English words written
Dutch words written
English manuscript words
Translated words
Translation completion %
Chapters complete
Chapters requiring review
Books active
Books published
```

Example Development metrics:

```text
Issues resolved
Commits generated
Tests executed
Test success %
PRs created
PRs awaiting approval
Lines changed
Build failures
```

Example Marketing metrics:

```text
Posts generated
Posts published
Campaigns active
Spend today
Spend month
Conversions
Cost/conversion
Human approvals waiting
```

Example Blue Team metrics:

```text
Events processed
Alerts generated
Alerts resolved
Critical alerts
Devices monitored
CVEs discovered
Incidents open
Mean time to resolution
```

Example Swarm metrics:

```text
Nodes online
Nodes offline
GPUs available
VRAM available
Active workers
Queued tasks
Tasks/hour
Power estimate
Cloud usage
```

---

## 65. Output Feed

System Modules may expose recent outputs.

The Home screen may show:

```text
Latest output
Latest 3 outputs
Summary only
Metrics only
```

configurable per card.

Outputs should link back to the responsible task/artifact where possible.

---

## 66. Progress Metrics

Systems dealing with projects should expose project progress.

Example:

```text
SEVEN DAYS BEFORE

English manuscript        100%
Dutch translation          96%
Editorial review           61%
Publishing readiness       72%
```

These values MUST derive from defined metrics rather than fabricated LLM estimates unless explicitly marked `AI ESTIMATE`.

---

## 67. Custom User Metrics

Users may create custom Dashboard Metrics.

Metrics can define:

- data source;
- numerator;
- denominator;
- filter;
- aggregation;
- unit/display type;
- refresh interval;
- historical retention.

Jarvis may assist in creating these.

---

## 68. Agent Metrics

Individual Agents may optionally expose Home metrics including:

- tasks today;
- completed;
- failed;
- waiting approval;
- human time saved;
- cloud cost;
- success rate;
- average task duration.

---

## 69. Department Metrics

Departments may aggregate child Agent metrics.

Examples:

- agents online;
- tasks completed;
- pending approvals;
- failures;
- spend;
- human time saved;
- goal progress.

---

## 70. Goal Widgets

Goals may be pinned directly to Home and show:

- current;
- target;
- expected value by current date;
- ahead/behind status;
- forecast;
- recommended action.

---

## 71. Home System Manager

Create **Customize Home** screen.

For each system allow configuration of:

```text
Visible on Home
Enabled
Card size
Metrics shown
Show recent outputs
Allow Jarvis changes
Position/order
Pinned state
```

---

## 72. System Details Screen

Clicking a System Card opens the System Details screen.

Tabs:

```text
Overview
Agents
Metrics
Activity
Outputs
Automation
Configuration
Permissions
Resources
Logs
Dependencies
License
```

---

## 73. System Dependency Graph

Systems may depend on other systems.

If disabling a system impacts another, Jarvis must show a dependency warning and ask the user whether to cancel or disable anyway.

Jarvis should not silently disable dependent functionality.

---

## 74. Global Systems Screen

Create a complete **Systems** management screen.

Columns include:

```text
SYSTEM
STATE
HOME VISIBILITY
CONTROL POLICY
HEALTH
LAST ACTIVITY
LICENSE
```

Actions:

```text
Enable
Disable
Pause
Restart
Configure
Open Dashboard
View Logs
```

---

## 75. Global Safe Mode

Jarvis shall provide **Safe Mode**.

Safe Mode disables autonomous external actions while retaining inspection capabilities.

Examples:

```text
Email sending               BLOCKED
Social posting              BLOCKED
Purchases                   BLOCKED
Production deployment       BLOCKED
Filesystem read             ALLOWED
Analysis                    ALLOWED
Local inference             ALLOWED
Monitoring                  ALLOWED
Decision Inbox              ALLOWED
```

This is separate from licensing lockout.

---

## 76. Emergency Autonomous Stop

Provide a prominent **STOP AUTONOMY** control.

This shall:

- stop creation of new autonomous tasks;
- stop eligible running tasks;
- disable child-agent spawning;
- block external write actions;
- retain system monitoring;
- retain UI and data access.

The user can later resume manually.

---

## 77. Notification Center

Create a unified Notification Center for:

```text
Information
Completed work
Warnings
System errors
Decisions
Security alerts
Goal alerts
License warnings
Node failures
Budget events
```

Individual Systems/Agents may define notification thresholds.

---

## 78. Activity Timeline

Create a global chronological activity view.

Filters:

- Workspace;
- Department;
- System;
- Agent;
- Node;
- severity;
- action type;
- date.

Each activity should link to underlying task/output/evidence when available.

---

## 79. Command Center Home Design

The default Jarvis Home should function as an owner/operator command center rather than a chat homepage.

Suggested structure:

```text
GOOD MORNING

3 decisions require you
18 tasks completed overnight
All 5 nodes healthy
€0.82 cloud spend today

--------------------------------

GOALS

Book sales             43 / 100
Dutch translation      96%
Jarvis P3              64%

--------------------------------

SYSTEMS

Publishing     ACTIVE
Translation    ACTIVE
Development    ACTIVE
Blue Team      ACTIVE

--------------------------------

RECENT ACTIVITY

Chapter translated
PR completed
Security alert resolved
Campaign prepared

--------------------------------

JARVIS

What would you like done?
[Command input]
```

Chat remains available but is one interaction mechanism rather than the entire product.

---

## 80. Required Dashboard Acceptance Tests

### Visibility

- System can be shown on Home.
- System can be hidden without disabling it.
- Hidden system continues operating.
- Visibility persists after restart.

### Enable/Disable

- User can disable a System.
- Related autonomous schedules stop.
- Associated agents stop receiving new work.
- Existing data remains available.
- User can re-enable the System.

### User Locks

- User can lock a System enabled.
- Jarvis cannot disable it.
- User can lock a System disabled.
- Jarvis cannot enable it.
- Jarvis may still recommend changes.

### Metrics

- Systems expose standardized metrics.
- User selects metrics shown on Home.
- Metrics update without page refresh where practical.
- Historical metric data can be queried.
- AI-estimated values are marked explicitly.

### Outputs

- Systems expose recent meaningful outputs.
- Outputs link to source task/artifact.
- User can select output visibility.

### Progress

- Project progress can appear as Dashboard widgets.
- Metrics use authoritative underlying data.
- Translations can show source/translated word counts and completion percentage.

### Dependencies

- Disabling a dependency produces warning.
- No dependent service silently fails.

### Safety

- STOP AUTONOMY prevents new autonomous external actions.
- Safe Mode preserves monitoring and local analysis.
- Neither mode destroys state.

---

## 81. Revised Implementation Priority

### P1 — Owner Control / Core UX

- Agent Profiles
- complete Agent Config Editor
- Systems Registry
- Systems screen
- modular Home Dashboard
- show/hide systems
- enable/disable/pause
- Dashboard metrics
- outputs/activity feed
- user configuration locks
- Decision Inbox
- Safe Mode
- STOP AUTONOMY

### P2 — Organization & Knowledge

- Workspaces
- Departments
- Agent hierarchy
- Team Chat
- Shared Brain UI
- Skill Manager
- canonical shared objects
- Goals/KPI engine

### P3 — Automation

- Workflow builder
- event bus
- event-driven automations
- proactive suggestions
- temporary agents
- Agent Team templates
- Away Mode
- Morning Brief

### P4 — Intelligence

- Specialist Packs
- Specialist Model Registry
- hybrid model routing
- cost/privacy governor
- model escalation
- evaluation suites

### P5 — Swarm

- multi-node execution
- hardware-aware placement
- live execution map
- resource policies
- role policies
- workload migration
- failover

### P6 — Commercial Platform

- signed subscription entitlements
- secure offline licensing
- time-tamper detection
- Pack subscriptions
- Pack trials
- Marketplace
- third-party Pack SDK
- portals

---

## 82. Final Product Principle

Jarvis shall expose its operation rather than hide it.

The owner should be able to open Home and immediately understand:

```text
What is running?
What is disabled?
What has Jarvis accomplished?
What is currently being worked on?
What needs my attention?
What is failing?
What does each Agent know?
Which system is responsible?
Which computer is doing the work?
How much has it cost?
What progress has been made?
How much human work has been avoided?
```

The owner must also be able to say:

```text
Show this.
Hide this.
Start this.
Stop this.
Pause this.
Change this Agent.
Change its model.
Change its tools.
Change its authority.
Never let Jarvis change this setting.
```

The Home screen should therefore behave as the **command center for the entire autonomous system**, not merely as an AI chat interface.

---

## 83. Overall Product Positioning

Jarvis should combine:

- Zoey-style usability and persistent AI teams;
- FounderOS-style business autonomy, departments, workflows and approval logic;
- Sintra-style specialist packaging and shared business context;
- local-first/private operation;
- model-agnostic intelligence routing;
- installable Specialist Packs;
- full owner visibility and configuration;
- physical multi-device compute orchestration;
- offline-capable commercial licensing.

Core positioning:

**Jarvis is not the AI model. Jarvis runs the AI workforce.**

Product principles:

**Local when desired. Cloud when useful. Autonomous when allowed. Transparent by default. Fully controllable by the owner.**
