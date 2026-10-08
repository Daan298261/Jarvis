# ANZU Superassistant — Product North Star

> **Status:** Product-intent document  
> **Role:** Highest-level implementation and UX reference for the Jarvis/ANZU project  
> **Product name:** **ANZU Superassistant**  
> **Repository / engineering project:** Jarvis

## Purpose

ANZU Superassistant is the end-user product being built by the Jarvis project.

This document defines what the finished product is supposed to **be**, rather than prescribing exactly how every component must be implemented.

Individual RFCs, architecture documents and implementation specifications exist to move ANZU toward this goal. They are important, but they are subordinate to the overall intent. An implementation that technically satisfies an RFC while producing a confusing, ugly, fragile, slow or excessively technical product should not be considered successful.

When there is ambiguity, implementation decisions should be judged against this document first:

> **Does this make ANZU feel more like a polished, capable, trustworthy personal superassistant?**

If not, the implementation should be reconsidered even if it technically satisfies the wording of a lower-level specification.

---

## 1. End goal

ANZU should feel like a finished premium consumer product, not an experimental collection of AI tools.

It should combine the capability of an autonomous agent platform, the intelligence of multiple specialized AI systems, the continuity of a personal assistant, the responsiveness of conventional software and the visual quality of a high-end application.

The user should not need to think in terms of models, inference servers, agents, context windows, MCP servers, worker processes, GPU allocation, browser engines or task graphs unless they deliberately open advanced controls.

The normal interaction should be much simpler:

> **Tell ANZU what you want. ANZU figures out how to accomplish it.**

ANZU should understand the desired result, inspect the environment, plan, execute, diagnose failures, change strategy, independently verify the result and only then report completion.

Running a command successfully is not the same as completing the requested task successfully.

ANZU should eventually be capable of receiving requests such as:

- “Fix the application.”
- “Research this subject and make me a report.”
- “Continue writing my book.”
- “Find the bug users are reporting, patch it, test it and prepare the update.”
- “Handle this marketing campaign.”
- “Organize these files.”
- “Check the house before I go to bed.”
- “Watch this project while I am away.”

The user should not have to translate those goals into a sequence of computer operations.

---

## 2. Product character: luxurious, deliberate and visually finished

ANZU should look and feel expensive.

That does not mean filling the screen with animations or visual effects. It means restraint, consistency, smoothness, good typography, high-quality motion, clear hierarchy, excellent spacing, sensible transitions and attention to details that normally distinguish a prototype from a finished commercial product.

Every major screen should look intentionally designed.

There should be no sense that multiple unrelated developer dashboards have been bolted together. Settings, Agents, Skills, Swarm, Security, Projects, Phone, Memory and other subsystems should share one design system and one interaction language.

Technical complexity should progressively reveal itself. The default interface should be simple. Advanced controls should be available when needed rather than permanently competing for attention.

This intent is reflected in the move toward the conversational owner shell and the stronger visual-acceptance requirements in the later presence RFCs, including **RFC-0195**.

ANZU should pass this test:

> Someone should be able to see the application for the first time without knowing anything about the project and assume it is a mature commercial product.

“Technically functional” is not the target.

**Finished is the target.**

---

## 3. ANZU itself should feel alive

ANZU is not merely the text in the chat window.

Its visual presence, voice, motion, state and behaviour should combine into the impression of a persistent intelligence.

The animated presence should clearly communicate states such as idle, listening, thinking, working, speaking, waiting for approval, alert, offline and error without requiring technical status text everywhere.

Relevant specifications include:

- **RFC-0069** — morphable / particle-based presence foundation.
- **RFC-0137** — persona roster and associated identity system.
- **RFC-0175 / 0176 / 0177 / 0178** — continuous presence, appearance, motion and adaptive rendering work.
- **RFC-0195** — higher visual-acceptance bar, including a recognisable viewport-filling presence rather than a small isolated animation.
- **RFC-0138** — custom/generated orb or presence identities.

The important principle is not “implement particles.”

The principle is:

> **ANZU should have presence.**

Motion should be smooth. Morphing should feel organic. Status changes should be understandable. Different devices may render that presence differently, but they should clearly belong to the same product.

---

## 4. Voice is a primary interface, not an accessory

ANZU should be pleasant enough to talk to that voice interaction is genuinely preferable when typing is inconvenient.

It should not sound like a generic operating-system accessibility voice pretending to be an AI.

Relevant implementation/spec work includes:

- **RFC-0070** — higher-quality local TTS foundation.
- **RFC-0092** — do not silently present fallback/SAPI output as the intended natural voice.
- **RFC-0111** — Kokoro runtime and explicit failure reporting.
- **RFC-0075** — separation of social speech from technical output and earlier speech delivery.
- **RFC-0117** — warm small front responder for fast initial responses while deeper work continues.

The end goal is conversational latency.

ANZU should acknowledge simple requests almost immediately, speak naturally, allow interruption, avoid reading code/URLs/internal state aloud, and continue heavier work without creating the impression that the entire system has frozen.

The user should be able to interrupt ANZU naturally.

ANZU should be able to speak while other workers continue executing.

The voice should belong to the selected ANZU personality and visual presence.

---

## 5. One assistant, many specialists

ANZU should appear to the user as one coherent superassistant while internally being capable of delegating work to specialized intelligences.

The implemented **RFC-0137** persona roster includes:

- **Anzu** — primary identity / main assistant.
- **Mestor** — planning and operations.
- **Nabu** — memory and research.
- **Enki** — coding and engineering.
- **Veles** — Red Team.
- **Themis** — Blue Team.
- **Aegir** — media and communications.
- **Bragi** — writing.
- **Hermes** — browser / web-facing work.
- **Heimdall** — monitoring / watch functions.
- **Eir** — care / support-oriented domain identity.
- **Maia** — assistant/support role.
- **Vulcan** — engineering / build-oriented role.

Those identities should eventually represent useful specialization rather than merely cosmetic skins.

Anzu remains the primary assistant and central identity. Specialists can be manually selected where desirable, but ANZU should normally determine when specialist capability is useful without forcing the user to route every task manually.

The longer-term Agent OS design expands this into persistent Agent Profiles, specialist packs, configurable teams, independent memories, delegation, temporary agents, authority levels, schedules, verification policies and model/node preferences.

Agent identity should remain separate from whichever model or machine happens to perform the work.

The user should think:

> **“ANZU is handling this.”**

Not:

> “I need to choose model 4, worker 7 and tool 12.”

---

## 6. Fast when simple, powerful when difficult

ANZU should not run a large language model and a fifteen-step agent loop merely to perform a trivial action.

Simple operations should feel like conventional software.

Relevant architecture/spec work includes:

- **RFC-0085** — universal fast path.
- **RFC-0117** — tiny/warm front responder.
- **RFC-0127 / RFC-0128** — rapid initial and progressive response behaviour.
- **RFC-0171** — System-One Reflex Lane.
- **RFC-0172** — reflex-first execution for browser/computer-use tasks.

The intended hierarchy is roughly:

**deterministic rule → tiny/reflex decision system → normal code/tool execution → normal model → specialist/expert reasoning only when required**

This is not merely a performance optimization. It is part of making ANZU feel well engineered.

A light switch should behave like a light switch, not like an AI research project.

---

## 7. Autonomous, but not reckless

ANZU should be capable of substantial unattended work.

It should also remain controllable.

The product should distinguish ordinary reversible actions from consequential, destructive, external, financial or security-sensitive actions.

Relevant specifications include:

- **RFC-0002** — per-capability autonomy policies.
- **RFC-0110** — contextual approval prompts.
- **RFC-0031** — reversibility-first action gates, durable undo and approval grants.
- **RFC-0071** — automation circuit breaking for repeatedly failing jobs.

The longer-term authority model allows agents to range from observation-only to autonomous-with-independent-verification, with per-action overrides and a Decision Inbox for genuinely human decisions.

The product principle is:

> **ANZU should eliminate unnecessary approvals without eliminating meaningful control.**

Routine work should simply happen.

Important decisions should be surfaced clearly.

Emergency controls such as **STOP AUTONOMY** and **Safe Mode** should always be understandable and reachable.

---

## 8. ANZU must verify its own work

A defining property of ANZU is that it should not confuse activity with success.

The runtime/master-plan direction includes a mandatory verification loop, and **RFC-0026** adds explicit execution phases and verification outcomes such as:

- VERIFIED
- VERIFICATION_FAILED
- PARTIALLY_VERIFIED
- NOT_VERIFIED

Every major autonomous workflow should have a concept of acceptance criteria.

ANZU should inspect what it produced.

A coding agent should build and test.

A browser worker should verify that the target state changed.

A document worker should verify that the requested content exists.

A file operation should verify the resulting filesystem state.

An autonomous workflow should be able to say what it could and could not verify.

Confidence should come from evidence rather than cheerful completion messages.

---

## 9. Local-first intelligence, with optional escalation

ANZU is fundamentally owner-controlled infrastructure.

Its identity, orchestration, memory, policies and core operation should not depend on one cloud provider.

The current architecture supports local inference and OpenAI-compatible alternatives through an abstraction layer, and the hardware-aware design is intended to move inference between the main PC, another LAN machine or a dedicated GPU system without redesigning the application.

The long-term user-facing policies are:

- **LOCAL ONLY**
- **LOCAL FIRST**
- **BEST RESULT**
- **COST OPTIMIZED**

The router can then consider capability, context size, latency, VRAM, available nodes, privacy policy, user preferences, cost, load, model warmth and historical success.

The user chooses intent and policy.

**ANZU chooses infrastructure.**

---

## 10. Swarm computing should be invisible unless inspected

The long-term system is not one AI running on one PC.

It is an owner-controlled compute fabric.

Existing foundations distinguish Node identity from software workers and separate roles such as Orchestrator, Leader, Senior Worker and Junior Worker. The design includes capability registration, role-placement policies, resource budgets, scheduling and a Swarm UI foundation.

Role placement should support both preference and force modes. A user may prefer a device for a role without requiring it, or explicitly force a role when necessary.

Resource usage should also be owner-configurable, including dynamic host-resource availability or fixed percentage caps.

The planned step is true multi-node execution: discovery, secure pairing, remote workers and cross-node networking.

Eventually a desktop, GPU server, old laptop, Raspberry Pi and other machines can contribute different capabilities.

ANZU should decide where work belongs.

Adding hardware should increase capability rather than increase user configuration burden.

---

## 11. Persistent memory, projects and learning

ANZU should accumulate useful continuity rather than repeatedly starting from zero.

Existing foundations include persistent task state, trajectory memory, reusable skills, project/chat persistence, context compaction and recovery.

Relevant specifications include:

- **RFC-0121** — project-folder/chat/database/media placement foundations.
- **RFC-0173** — Skill Forge: successful traces can become reviewed reusable skills rather than being rediscovered indefinitely.

The longer-term memory goal is more sophisticated.

Memory should have provenance, confidence, reinforcement and lifecycle rather than becoming an uncontrolled prompt dump.

ANZU should get better because it learns useful procedures and context.

It should not get worse because it accumulates junk.

---

## 12. Multi-agent work should be real parallelism

**RFC-0174** implements Multi-Agent Rooms with participants, bounded shared blackboard state, private histories, task structure, deadlock governance, supervisor synthesis and an owner-facing portal.

The end goal goes beyond several chatbots talking to each other.

ANZU should use multi-agent execution when it provides actual value: parallel research, competing hypotheses, independent verification, specialist handoffs, map/reduce work, code/review separation or simultaneous project tasks.

Parallelism should shorten completion time or improve quality.

**Agent theatre is not a feature.**

---

## 13. Phone companion and grid-down operation

The phone should become another surface of the same ANZU system rather than a separate assistant.

Relevant work includes:

- **RFC-0074** — phone pairing improvements.
- **RFC-0108** — offline phone model-pack path.
- **RFC-0123** — reachability / anti-impersonation foundations.
- **RFC-0139** — animated ANZU presence on Android.
- **RFC-0140** — on-device STT/TTS fallback and grid-down voice capability.

The wider planned experience includes smooth LAN/WAN/4G reachability, secure pairing, graceful movement between PC-hosted intelligence and phone-local operation, offline maps/knowledge/tools where appropriate, and a coherent **Grid Down Mode**.

The phone should not become useless because the Leader PC or internet connection disappeared.

Capability may degrade.

The product should remain understandable and useful.

---

## 14. ANZU should extend into the physical home

The desktop application is the beginning, not the boundary.

Home IoT, Household Vision and household security are planned first-class capabilities.

**Household Vision** is intended as an always-on local perception service that maintains lightweight physical-world state, combines camera and IoT signals, understands configurable routines and can verify that real-world tasks have actually been completed.

ANZU should eventually understand enough about the home to provide useful proactive assistance rather than only responding to text prompts.

This must remain privacy-conscious, local-first and configurable.

The result should feel like the same ANZU intelligence extending into the environment—not a collection of unrelated smart-home dashboards.

---

## 15. Security should be part of the platform

ANZU should be capable of protecting its own infrastructure and the household network.

The planned security architecture includes a defensive Blue capability for monitoring, alerting, containment and evidence; Purple for explicitly authorized testing of owned systems; and a separately gated Red capability that is not part of ordinary consumer autonomy.

The user-facing goal is straightforward:

ANZU should know whether its own systems are healthy, notice important security events, explain what happened and take permitted defensive action.

Security should be integrated into ANZU's overall world state rather than existing as an unrelated security application.

---

## 16. Away Mode is a defining end-state capability

Away Mode is where the project becomes substantially more than an assistant application.

The roadmap includes event-driven intake, retries and deduplication, autonomous software-engineering workers, policy/authority enforcement, production monitoring, self-healing, marketing management, SEO operations, NovelProject, multimedia workers and autonomous bug-fixing workflows.

The intended experience is that ANZU can continue productive work while the owner is elsewhere.

For example, a software project could receive a bug report, classify it, reproduce it, create an isolated workspace, patch it, run tests, request review if necessary and prepare the change for release.

The important concept is not “background agents.”

It is:

> **ANZU can responsibly carry a goal forward without requiring the user to supervise every intermediate action.**

---

## 17. Specialist packs and an extensible AI operating layer

The eventual platform is broader than a fixed set of built-in features.

The long-term Agent OS design provides persistent Agent Profiles, Specialist Packs, Model Packs, configurable workflows, shared and private memory, integration permissions, authority controls, cost/privacy governors, model routing, multi-node placement and eventual third-party packages.

Potential specialist areas include development, publishing, research, marketing, SEO, sales, media, defensive security and forensics.

ANZU itself remains the stable operating layer.

Models, agents and tools are replaceable resources underneath it.

That distinction is critical.

A new model should make ANZU smarter. It should not require rebuilding ANZU.

A new computer should make ANZU more capable. It should not create a second ANZU.

A new specialist pack should extend ANZU. It should not fragment the experience into another application.

---

## 18. Major planned capabilities

Important unfinished goals include:

- True multi-node swarm execution.
- Production-quality Windows installation, lifecycle and tray behaviour.
- Rich secure phone/WAN connectivity.
- Full custom presence generation.
- Final visual acceptance under **RFC-0195**.
- Remaining natural-voice quality and latency work.
- Durable project knowledge and richer artifact handling.
- Event-driven durable goals.
- Semantic action firewalling.
- Transactional durable execution.
- Selectable inference offload.
- Adaptive intelligence and learned routing.
- Home IoT.
- Household Vision.
- Defensive household/infrastructure security.
- Specialist/Domain Packs.
- Full Agent Profiles.
- Workflow composition.
- Decision Inbox expansion.
- Cost/privacy governance.
- Live execution maps.
- Morning Brief.
- Away Mode.
- Autonomous software maintenance.
- Marketing and SEO workers.
- NovelProject.
- Multimedia production.
- Wider plugin/integration/commercial ecosystem.
- Grid-down mobile companion capability.

These should not be treated as unrelated feature requests.

They are parts of the same end state:

> **A persistent, owner-controlled intelligence capable of understanding goals, allocating resources, using specialized capabilities, operating software and physical systems, learning useful procedures, working autonomously and remaining understandable to the person who owns it.**

---

## 19. Rules for interpreting specifications

When implementing an RFC, preserve its underlying requirement rather than copying its proposed implementation mechanically.

A later implementation may use a different library, model, architecture or UI mechanism if it achieves the intent more reliably and cleanly.

- Do not remove useful capability merely to simplify the codebase.
- Do remove unnecessary complexity from the user's experience.
- Do not expose architecture simply because the architecture exists.
- Do expose state when the user needs confidence in what ANZU is doing.
- Do not optimize benchmarks while damaging perceived responsiveness.
- Do use fast deterministic mechanisms where they are superior to AI reasoning.
- Do not create several interfaces where one adaptive interface can work.
- Do not allow specialists, models or nodes to fracture ANZU into unrelated products.
- Do not mark something finished merely because its backend exists.
- Do not preserve an inferior implementation solely because an older specification happened to describe it.
- Do preserve the behavioural requirement, safety property or product intent that specification was trying to guarantee.

A feature is finished when its complete user experience is coherent, reliable, visually appropriate and tested in the environment where it will actually be used.

---

## 20. The ANZU quality test

Every significant implementation should be judged against these questions:

1. Does it reduce the amount of technical knowledge required from the user?
2. Does it make ANZU faster, more capable, more reliable or easier to trust?
3. Does it look and behave like part of the same premium product?
4. Would a normal user understand what is happening without reading documentation?
5. Does it hide complexity by default while preserving owner control?
6. Can ANZU recover intelligently when the happy path fails?
7. Does ANZU verify the result rather than merely execute steps?
8. Does the implementation work gracefully when optional models, workers, nodes or network connections disappear?
9. Does it preserve privacy and local operation wherever practical?
10. Does it avoid unnecessary approval prompts and configuration?
11. Does it feel responsive during both simple commands and long-running work?
12. Would this still make sense when ANZU spans five machines, a phone and the house rather than only one Windows PC?
13. Is the implementation aesthetically good enough that it should actually ship?
14. Does it move ANZU toward being a coherent superassistant rather than simply adding another feature?

If the answer to the final question is no, the implementation is probably moving in the wrong direction.

---

## 21. Definition of the finished product

The finished **ANZU Superassistant** is an elegant, local-first, multi-device autonomous intelligence that can be installed and used with minimal configuration; communicates naturally through text, voice and a distinctive visual presence; understands high-level goals instead of requiring sequences of commands; selects models, tools, agents and machines automatically; performs simple operations almost instantly; handles complex work autonomously; delegates to specialists where useful; remembers projects and proven procedures; verifies its own results; asks for human decisions only when genuinely necessary; remains transparent and reversible; protects its own infrastructure; continues useful operation when cloud services or the main PC are unavailable; extends into the phone and home; and becomes more capable as additional hardware, models and specialist modules are added.

It should simultaneously have the depth of a professional automation platform and the simplicity of a premium personal assistant.

The user should never feel that they are operating the underlying swarm.

They are operating **ANZU**.

And ideally, most of the time, they should not feel that they are operating software at all.

They should simply tell ANZU what they need done.
