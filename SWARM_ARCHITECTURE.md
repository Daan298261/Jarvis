# Jarvis Swarm Architecture — Role, Placement, UI & Resource-Control Specification

Status: **separate long-term architecture specification** referenced by `JARVIS_MASTER_PLAN.md`.

Priority mapping:

- **P2 — Swarm-ready foundation:** one-node swarm model; Orchestrator/Leader separation; Node vs Worker distinction; capability registry; role policy; resource budgets and leases; local placement scheduler; dynamic universal UI contract.
- **P3 — Multi-node swarm:** discovery, secure pairing, remote workers, node telemetry, cross-node placement, role recommendations, swarm management UI, universal join/install flow.
- **P4 — Resilience and advanced placement:** standby Orchestrators, failover/state replication, advanced affinity/anti-affinity, service separation/replication, and other fault-tolerance work.

This document is authoritative for swarm role, placement, resource-control, node-management, and universal-UI requirements. The master plan owns overall project priority and implementation status; this file owns the detailed swarm design.

## 0. Terminology and implementation boundaries

The following distinction is mandatory in code and documentation:

- **Node** — a physical or virtual machine/device participating in Jarvis.
- **Worker** — a software execution service or agent that can run on an eligible Node, such as `QwenWorker`, `CursorACPWorker`, `BrowserWorker`, or a multimedia worker.
- **Orchestrator** — the control-plane role that coordinates the swarm.
- **Leader** — the strongest or most capable general-purpose execution Node currently available; it is not inherently the Orchestrator.
- **Senior Worker / Junior Worker / Peripheral** — product-facing node execution classes used by this specification. Implementation SHOULD represent these as Node classes/roles rather than software Worker types, to avoid collision with the existing worker abstraction.
- **Capability** — something a Node or Worker can technically perform.
- **Role assignment** — what Jarvis currently asks a Node/service to perform.
- **Resource budget** — how much host capacity Jarvis may consume.

Jarvis is a **one-node swarm by default**. P2 must introduce the abstractions without requiring a second computer or a networking rewrite. Multi-device transport belongs to P3.

Security, SIEM, Sentinel, and forensic examples in this document define future placement/role requirements only. They are **not current implementation scope** and must not be promoted merely because they appear in this architecture specification. Those subsystems will be separately specified before implementation.

Hardware names in examples (including V100-class examples) are illustrative only and do not establish purchasing requirements.

## 1. Revised Core Role Model

Jarvis must distinguish between **capabilities**, **roles**, and **resource classes**.

A device's hardware determines what it *can* do.

The swarm determines what it *should* do.

The user can influence or force what it *must* do.

The primary logical roles are:

1. Orchestrator
2. Leader
3. Senior Worker
4. Junior Worker
5. Peripheral

These roles are separate from specific capabilities such as:

- Security
- SIEM
- Database
- Scheduling
- Tool execution
- LLM inference
- Image generation
- Web gateway
- Storage
- Browser automation
- Monitoring

A device may hold multiple roles simultaneously.

---

# 2. Orchestrator

The **Orchestrator** is the control-plane authority for the swarm.

Primary responsibilities:

- Scheduler
- Task decomposition
- Tool calling
- Worker selection
- Workflow state
- Task queue
- Agent coordination
- Node registry
- Capability registry
- Health monitoring
- Recovery coordination
- Checkpoint coordination
- Resource allocation
- Role assignment
- Policy enforcement

Initially the Orchestrator may also host:

- Jarvis database
- Long-term memory
- Configuration
- Event store

However these must be designed as separable services.

Example future configuration:

```text
Orchestrator
   │
   ├── Scheduler
   ├── Tool Router
   ├── Agent Coordinator
   │
   ├── Database ──────> Database Node
   │
   └── Memory ────────> Storage Node
```

The Orchestrator should remain relatively lightweight.

It should not require the strongest GPU.

This allows an older laptop, desktop, mini-PC or Raspberry Pi to potentially maintain Jarvis coordination while more powerful machines execute workloads.

---

# 3. Orchestrator Redundancy

Jarvis should eventually support more than one Orchestrator-capable node.

Example:

```text
Primary Orchestrator
       │
       ├──────── Standby Orchestrator
       │
       └──────── Standby Orchestrator
```

Only one should normally act as authoritative scheduler unless the future architecture deliberately implements distributed scheduling.

Standby Orchestrators maintain enough state to assume control.

If the active Orchestrator fails:

```text
Heartbeat lost
      ↓
Failover initiated
      ↓
Eligible standby selected
      ↓
Task state recovered
      ↓
Scheduling resumes
```

This is different from Leader failover.

---

# 4. Leader

The **Leader** is the strongest or most capable general-purpose execution machine currently available to the swarm.

Typical example:

```text
Gaming workstation
RTX GPU
High-end CPU
64 GB RAM
Fast NVMe
```

The Leader is primarily an execution role.

It may handle:

- Complex agent workloads
- Large local models
- Desktop control
- Browser control
- Coding agents
- Large compilation jobs
- Multimedia workflows
- GPU workloads
- Tasks requiring multiple capabilities simultaneously

The Leader does NOT necessarily need to be the Orchestrator.

Preferred topology:

```text
          ORCHESTRATOR
        scheduling/control
               │
       ┌───────┼────────┐
       │       │        │
       ▼       ▼        ▼
    LEADER   SENIOR   JUNIOR
```

This separation is intentional.

If the Leader crashes, Jarvis should lose compute capacity rather than lose its control plane.

---

# 5. Senior Worker

A **Senior Worker** is a relatively capable execution node suitable for demanding workloads but not currently designated as Leader.

Examples:

- Secondary GPU workstation
- V100 compute server
- Modern laptop
- High-core-count desktop
- Machine with large RAM
- Dedicated AI inference server

Potential workloads:

- LLM inference
- Embeddings
- Large document processing
- Code compilation
- Video encoding
- Image generation
- TTS
- STT
- Long-running agent workflows
- Batch processing
- Heavy browser automation

There may be multiple Senior Workers.

Example:

```text
Leader
RTX 5070 Ti

Senior Worker #1
V100 32 GB

Senior Worker #2
12-core CPU / 64 GB RAM
```

---

# 6. Junior Worker

A **Junior Worker** is a lower-powered node intended primarily for smaller, background or parallelizable tasks.

Examples:

- Old laptop
- Old desktop
- Raspberry Pi
- Low-power mini-PC
- Older tablet where supported

Potential workloads:

- File hashing
- Downloads
- API calls
- Web scraping
- Log parsing
- Audio conversion
- Image resizing
- Backups
- Git operations
- Monitoring
- Network checks
- Small scripts
- Data preprocessing
- Compression
- OCR preprocessing
- Unit tests
- Lightweight compilation
- Scheduled tasks

A Junior Worker may become temporarily more important if stronger machines disappear.

Worker class is therefore a scheduling hint, not an absolute limitation.

---

# 7. Peripheral

Peripheral nodes expose useful capabilities but may not support arbitrary Jarvis workloads.

Examples:

- Tablet
- Phone
- Browser client
- TV
- Xbox
- Camera device
- Microphone
- Smart display
- IoT hardware

Potential capabilities:

```text
display
camera
microphone
speaker
notifications
controller
location
limited_compute
WebAssembly
WebGPU
GPIO
sensor
```

The same universal Jarvis protocol should be used where technically practical.

---

# 8. Role Selection Is Dynamic

Default behavior:

Jarvis automatically determines appropriate roles based on:

- Hardware
- Operating system
- Reliability
- Power availability
- Network performance
- Installed capabilities
- Current utilization
- Historical uptime
- User configuration

Example:

```text
RTX workstation
→ Leader

V100 server
→ Senior Worker

Old laptop
→ Orchestrator + Junior Worker

Pi
→ Junior Worker + Security
```

These assignments are recommendations, not immutable classes.

---

# 9. User Role Preferences

Users must be able to express preferred placement.

Example:

```text
ASUS Laptop

Preferred roles:

✓ Orchestrator
✓ Scheduling
✓ Database

Preference strength:
Preferred
```

A preference tells Jarvis:

> Use this device for this role when reasonable.

However the scheduler may override it.

Example:

The user prefers the laptop for scheduling.

Laptop reaches 95% CPU.

Another eligible node is idle.

Jarvis may temporarily move supporting scheduling workloads elsewhere if necessary.

Preferences are therefore **soft constraints**.

---

# 10. Forced Role Placement

Users must also be able to create hard role assignments.

Example:

```text
Raspberry Pi 5

Security / SIEM:
FORCED

Jarvis Sentinel:
FORCED
```

Meaning:

> These services must run on this node unless the node becomes unavailable.

Jarvis must not silently move them while the forced node is online.

If the node becomes unavailable, policy determines what happens.

Possible modes:

## Strict

```text
Pi offline
↓
Security role unavailable
↓
Alert user
```

## Failover allowed

```text
Pi offline
↓
Security role temporarily reassigned
↓
User notified
↓
Role returns to Pi when available
```

The user should choose the behavior.

---

# 11. Exclusive Role Mode

A forced role should optionally support:

```text
Dedicated / Exclusive
```

Example:

```text
Pi-Security

Forced:
Security
SIEM
Sentinel

Exclusive Mode:
ON
```

Then Jarvis should avoid assigning unrelated workloads to that device.

This is useful for:

- Security appliances
- Database servers
- Network monitors
- Edge gateways
- Storage nodes

---

# 12. Role Assignment Levels

Every role/capability should support four assignment states:

```text
AUTO
PREFERRED
FORCED
DISABLED
```

Meaning:

## AUTO

Jarvis decides.

## PREFERRED

Jarvis should use this node when practical.

## FORCED

Jarvis must use this node subject to configured failover policy.

## DISABLED

This node must not perform that role.

Example:

```text
Node: Pi-01

Orchestrator       DISABLED
Security           FORCED
SIEM               FORCED
Database           DISABLED
CPU Worker         PREFERRED
Network Monitor    FORCED
```

---

# 13. Negative Preferences

Users should also be able to discourage workloads.

Example:

```text
Gaming-PC

Video generation:
PREFERRED

LLM:
AUTO

Background encoding:
AVOID

Security:
DISABLED
```

Optional scheduling preference model:

```text
FORCED
PREFERRED
AUTO
AVOID
DISABLED
```

`AVOID` means Jarvis may still use the node if necessary.

`DISABLED` means it may not.

---

# 14. Dedicated Database Role

Database functionality must not be permanently embedded into the Orchestrator.

Initially:

```text
Orchestrator
└── Database
```

Later:

```text
Orchestrator
     │
     ▼
Database Node
```

The database service should therefore be exposed through an internal interface from the start.

Possible placement:

```text
Role:
database.primary

Preferred Node:
Server-01

Failover:
Laptop-01
```

Future database replication can be implemented separately.

---

# 15. Dedicated Security / SIEM Role

Security must be a first-class role.

Example:

```text
Node:
pi-security

Roles:

security.sentinel       FORCED
security.siem           FORCED
security.logs           FORCED
security.network        PREFERRED
cpu_worker              AVOID
```

Potential stack:

```text
Wazuh events
Windows Events
Linux logs
Jarvis audit logs
Firewall events
Network telemetry
        │
        ▼
Jarvis Security
        │
        ▼
Rules + AI analysis
        │
        ▼
Response / Alert
```

The user must be able to intentionally create a dedicated security appliance from an old device.

---

# 16. Dedicated Web-Facing / Edge Role

Internet-facing access should also be assignable.

Example:

```text
Node:
old-mini-pc

edge.gateway:
FORCED

web.public:
FORCED

database:
DISABLED

memory:
DISABLED

desktop_control:
DISABLED
```

This allows an expendable/isolated machine to handle public traffic without exposing the primary Jarvis machine directly.

Compromise of the Edge node must not automatically grant control of the swarm.

---

# 17. Universal Dynamic GUI

Jarvis must NOT maintain independent frontends for each operating system.

There should be one primary dynamic Jarvis interface.

Architecture:

```text
                 JARVIS UI
                     │
             Universal frontend
                     │
        ┌────────────┼────────────┐
        │            │            │
     Desktop       Browser      Mobile
     wrapper       browser      wrapper/app
```

The UI should dynamically adapt to:

- Screen size
- Input method
- Operating system
- Available device capabilities
- User permissions
- Current node role

---

# 18. UI Technology Principle

Preferred architecture:

```text
Web frontend
      │
      ├── Desktop wrapper
      ├── Browser
      ├── Mobile wrapper
      └── Embedded device browser
```

Do not create:

```text
Windows UI
Linux UI
Android UI
Pi UI
macOS UI
```

as separate products unless unavoidable.

One frontend should render all supported environments.

---

# 19. Desktop Application

The desktop application should preferably be a thin native shell around the universal frontend.

Preferred candidate:

Tauri.

Alternative:

Electron.

Desktop shell provides native functions such as:

- System tray
- Startup
- Notifications
- File-system integration
- Desktop automation bridge
- Installer
- Local daemon lifecycle
- Device discovery
- OS-specific APIs

Frontend remains shared.

---

# 20. Dynamic UI Capability Detection

The UI should query the current device capabilities.

Example:

```text
Desktop PC:
show:
- Desktop Control
- GPU
- Storage
- Models
- System Services

Phone:
show:
- Camera
- Microphone
- Notifications
- Approvals

Pi:
show:
- GPIO
- Security
- Network
- Services
```

Same frontend.

Different capabilities.

---

# 21. Central Node Management UI

Add:

```text
Settings
└── Swarm
    ├── Nodes
    ├── Roles
    ├── Resources
    ├── Security
    ├── Network
    └── Failover
```

Example Node screen:

```text
ASUS GL552VX
────────────────────────

Status: ONLINE
Class: Junior Worker
Orchestrator capable: YES

CPU       18%
RAM       5.1 / 16 GB
Network   1 Gbps

Roles

Orchestrator       PREFERRED
Scheduler          PREFERRED
Database           AUTO
Security           AUTO
CPU Worker         AUTO
Web Edge           DISABLED

Resource allocation

Jarvis may use:
CPU       50%
RAM       40%
GPU       0%
Storage   100 GB
```

---

# 22. Host Resource Budget

Every node must have a configurable Jarvis resource budget.

During installation, user should be asked:

```text
How much of this device may Jarvis use?
```

Options:

```text
Minimal
Balanced
High
Maximum
Custom
```

Advanced users can configure exact values.

---

# 23. Global Percentage Resource Limit

The simplest configuration should expose:

```text
Maximum host resources available to Jarvis:

[ 50% ]
```

Range:

```text
0% – 100%
```

Meaning Jarvis should attempt to keep its combined workload within that proportion of the host's available resources.

Example:

```text
Host:
16 CPU threads
64 GB RAM

Jarvis resource budget:
50%

Approximate maximum:
8 CPU-thread equivalent workload
32 GB RAM
```

This should be treated as a scheduling/resource-control policy rather than assuming every resource scales identically.

---

# 24. Per-Resource Limits

Advanced settings must allow separate limits.

Example:

```text
CPU:
Maximum 60%

RAM:
Maximum 24 GB

GPU utilization:
Maximum 80%

VRAM:
Maximum 12 GB

Disk:
Maximum 250 GB

Network:
Maximum 500 Mbps
```

Support percentage and absolute limits where meaningful.

---

# 25. Dynamic Resource Mode

Support a dynamic allocation mode.

Example:

```text
Jarvis Resource Mode:
DYNAMIC

Minimum:
10%

Normal target:
40%

Maximum:
80%
```

Jarvis may scale usage based on:

- User activity
- Machine idle state
- Foreground applications
- Gaming
- Thermal state
- Battery
- Power status
- Current task priority
- Other available swarm nodes

---

# 26. Idle Resource Harvesting

Optional mode:

```text
Use more resources while this device is idle:
ON
```

Example:

User actively gaming:

```text
Jarvis CPU budget: 15%
Jarvis GPU budget: 5%
```

PC idle overnight:

```text
Jarvis CPU budget: 80%
Jarvis GPU budget: 100%
```

This should be configurable.

---

# 27. Reserved Host Capacity

Users may instead specify how much should remain free.

Example:

```text
Always reserve for local user:

CPU: 25%
RAM: 8 GB
VRAM: 2 GB
```

Scheduler calculates usable Jarvis capacity from this reservation.

---

# 28. Hard Resource Caps

Some limits should support:

```text
HARD CAP
```

Jarvis must not intentionally exceed these values.

Example:

```text
GPU VRAM:
Maximum 10 GB
HARD

RAM:
Maximum 20 GB
HARD
```

This is particularly important when Jarvis runs alongside:

- Games
- Work applications
- Development tools
- Video editing
- Other local services

---

# 29. Soft Resource Targets

Users should also be able to configure soft limits.

Example:

```text
CPU target:
40%

Temporary maximum:
75%
```

Jarvis may exceed the target for important short-lived tasks but should return below it afterward.

---

# 30. Per-Role Resource Budgets

Resources may optionally be allocated by role.

Example:

```text
Node:
Main-PC

Jarvis total CPU:
60%

Of Jarvis allocation:

Orchestrator:
10%

LLM:
30%

Multimedia:
40%

Background:
20%
```

This should remain an advanced feature.

---

# 31. Task Priority

Tasks should carry priorities.

Suggested levels:

```text
CRITICAL
HIGH
NORMAL
BACKGROUND
IDLE
```

Example:

Security incident:

```text
CRITICAL
```

User asks Jarvis a question:

```text
HIGH
```

Scheduled document indexing:

```text
BACKGROUND
```

Long-term archive compression:

```text
IDLE
```

Resource allocation should consider task priority.

---

# 32. Local User Always Wins

Unless explicitly configured otherwise, active human use of a device should take precedence over background Jarvis processing.

Example:

```text
Jarvis using GPU for image generation
       ↓
User starts game
       ↓
Jarvis detects foreground GPU demand
       ↓
Background generation paused/migrated
       ↓
GPU resources released
```

This behavior should be configurable.

---

# 33. Battery-Aware Scheduling

Portable devices should expose:

```text
battery_level
charging
power_source
```

Possible policy:

```text
Laptop on AC:
Jarvis maximum 80%

Laptop on battery:
Jarvis maximum 20%

Battery below 30%:
Background jobs disabled
```

---

# 34. Thermal-Aware Scheduling

Where sensors are available:

```text
CPU temperature
GPU temperature
thermal throttling
fan state
```

Scheduler should reduce workload when configured thresholds are exceeded.

Example:

```text
GPU > 82°C
↓
Reduce new GPU jobs
↓
Move eligible workload elsewhere
```

---

# 35. Network-Aware Scheduling

Remote task placement should account for data movement.

Example:

Task requires processing 100 GB video.

Junior Worker:

```text
CPU suitable
Network 100 Mbps
```

Leader:

```text
CPU suitable
File already local
```

Scheduler should likely choose Leader despite higher compute cost.

Node scoring must account for transfer cost.

---

# 36. Role and Resource Configuration Precedence

Use explicit policy precedence:

```text
1. Security restriction
2. User FORCED assignment
3. User DISABLED assignment
4. Hard resource cap
5. Capability requirement
6. Failover policy
7. User PREFERRED assignment
8. Resource availability
9. Scheduler optimization
10. AI recommendation
```

The AI may optimize within policy.

It must not silently override hard user restrictions.

---

# 37. AI Role Recommendations

Jarvis should suggest role assignments during setup.

Example:

```text
Raspberry Pi 5 detected

Recommended roles:

✓ Security monitoring
✓ Network monitoring
✓ Junior Worker
✓ Standby Orchestrator

Reason:
Low power consumption and suitable for 24/7 operation.
```

User can:

```text
Accept
Customize
Ignore
```

---

# 38. Automatic Re-Evaluation

Roles should periodically be reconsidered.

Example:

User adds a V100 server.

Before:

```text
RTX PC
Leader + LLM + multimedia
```

After:

```text
RTX PC
Leader + multimedia

V100
Senior Worker + LLM
```

Jarvis can recommend the change.

It must respect forced assignments.

---

# 39. User Intent Must Survive Reboots

All:

- Role preferences
- Forced roles
- Disabled roles
- Resource budgets
- Failover policies
- Device classifications

must persist across:

- Reboots
- Updates
- Orchestrator changes
- Leader changes

These settings belong to swarm configuration, not ephemeral scheduler state.

---

# 40. Revised Example Household Swarm

Example deployment:

```text
ASUS OLD LAPTOP
────────────────────────
Orchestrator        FORCED
Scheduler           FORCED
Database            PREFERRED
Junior Worker       AUTO

Resource budget:
50%


MAIN RTX PC
────────────────────────
Leader              PREFERRED
Senior Worker       AUTO
LLM                  AUTO
Image generation    PREFERRED
Video generation    PREFERRED
Desktop control     FORCED

Resource budget:
Dynamic
20% active
90% idle


V100 SERVER
────────────────────────
Senior Worker       FORCED
LLM inference       PREFERRED
Embeddings          PREFERRED

Resource budget:
95%


RASPBERRY PI
────────────────────────
Security            FORCED
SIEM                FORCED
Sentinel            FORCED
Network Monitor     PREFERRED

Exclusive mode:
ON

Resource budget:
80%


TABLET
────────────────────────
Peripheral          AUTO
Display             PREFERRED
Camera              AUTO
Microphone          AUTO
Notifications       PREFERRED

Resource budget:
20%
```

---

# 41. Revised Scheduling Example

Task:

```text
Generate 30-second promotional video
```

Orchestrator decomposes:

```text
1. Script planning
2. TTS
3. Image generation
4. Video generation
5. Encoding
6. QC
```

Scheduler assigns:

```text
Script planning
→ V100 Senior Worker

TTS
→ Leader

Image generation
→ Leader

Video generation
→ Leader

Encoding
→ Old Desktop Junior Worker

QC metadata
→ Junior Worker
```

The Orchestrator coordinates everything without necessarily performing any heavy computation itself.

---

# 42. Failure Example

Normal:

```text
Laptop
Orchestrator

RTX PC
Leader

V100
Senior Worker

Pi
Security

Old Desktop
Junior Worker
```

RTX PC fails:

```text
Orchestrator remains alive.

Leader unavailable.

V100 promoted:
Leader or acting heavy-work Leader

Junior workloads continue.

GPU capabilities reduced.

Waiting workloads checkpoint.
```

Laptop fails:

```text
Orchestrator lost.

Standby Orchestrator election occurs.

RTX PC or another eligible node assumes orchestration.

Execution tasks continue/recover.
```

Pi fails:

```text
Security FORCED role unavailable.

Policy = failover allowed.

Temporary Sentinel launches elsewhere.

User receives alert:

"Dedicated security node unavailable.
Temporary security monitoring moved to ASUS-Laptop."
```

---

# 43. Important Distinction

The following concepts must never be conflated:

```text
ORCHESTRATOR
Who coordinates the swarm?

LEADER
Which machine is currently the strongest general executor?

WORKER CLASS
How capable is a device for distributed workloads?

CAPABILITY
What can the device technically perform?

ROLE ASSIGNMENT
What is Jarvis currently asking it to perform?

USER POLICY
What does the user prefer or require?

RESOURCE BUDGET
How much of the machine may Jarvis consume?
```

This distinction should exist in both code and UI.

---

# 44. Universal Installer Requirement

Where technically feasible, every Jarvis installer must perform the same conceptual setup:

```text
Install
   ↓
Detect hardware
   ↓
Detect capabilities
   ↓
Generate node identity
   ↓
Configure resource budget
   ↓
Recommend roles
   ↓
Discover existing Jarvis swarm
   ↓
Pair securely
   ↓
Receive swarm configuration
   ↓
Join
```

Operating-system-specific code may differ.

The setup experience should remain conceptually identical.

---

# 45. Initial Resource Setup UX

Suggested setup page:

```text
How should Jarvis use this device?

○ Minimal
○ Balanced
● Dynamic
○ Maximum
○ Custom
```

Then:

```text
Recommended role:

Senior Worker

Also suitable for:

✓ Leader
✓ LLM inference
✓ Image generation
✓ Desktop automation

Resource usage:

When active:
30%

When idle:
80%

[Advanced Settings]
```

The user should be able to finish setup without understanding CPU scheduling.

---

# 46. Advanced Role Setup UX

Advanced users can select:

```text
ROLE                  POLICY

Orchestrator          AUTO
Leader                PREFERRED
Senior Worker         AUTO
Junior Worker         AUTO

Security              DISABLED
Database              AUTO
Web Edge              DISABLED
LLM                   PREFERRED
Multimedia            PREFERRED
```

Each role may additionally expose:

```text
Failover:
Automatic / Ask / Disabled

Exclusive:
Yes / No

Priority:
0-100
```

---

# 47. Core Product Principle

Jarvis should automatically make sensible decisions while allowing the owner to override them.

Default:

> Jarvis decides.

Preference:

> Jarvis should do this when practical.

Forced:

> Jarvis must do this.

Disabled:

> Jarvis must never do this.

That model should apply consistently to:

- Roles
- Devices
- Services
- Models
- Workers
- Security
- Networking
- Resource allocation

---

# 48. Updated Architecture Target

The long-term architecture should resemble:

```text
                    UNIVERSAL JARVIS UI
                            │
                    JARVIS CORE API
                            │
                     ORCHESTRATOR
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼

           LEADER       SENIOR WORKERS  JUNIOR WORKERS
         strongest      heavy compute   background work
          machine

              │             │             │
              └─────────────┼─────────────┘
                            │
                       PERIPHERALS

                            +
                    SPECIALIZED ROLES

                  Security / Sentinel
                     Database
                       Edge
                      Storage
                     Monitoring
```

All devices use the same underlying Node protocol.

All user interfaces use the same dynamic frontend.

All scheduling operates through capabilities and policies.

No single physical device must permanently define what Jarvis is.

---

# 49. Updated Fundamental Requirement

> **Jarvis is a one-node swarm by default. In a multi-device environment, an Orchestrator coordinates available resources; the strongest execution node acts as Leader; capable systems operate as Senior Workers; lower-powered systems operate as Junior Workers; and specialized or peripheral devices contribute whatever capabilities they can. Users may leave placement automatic, express preferences, or enforce hard role assignments and resource limits.**

This model must remain valid from a single ordinary PC to a large heterogeneous household swarm.
