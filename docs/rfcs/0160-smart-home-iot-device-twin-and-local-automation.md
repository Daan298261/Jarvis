# RFC-0160: Smart-home/IoT device twin and local automation

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Home/device control is common assistant functionality, but direct free-form model calls to physical devices are unsafe and hard to reason about.

## Decision
Add an IoT Device Twin registry with typed capabilities/state and adapters for owner-enabled local platforms/protocol bridges. Models interact with semantic actions (set light, read temperature, scene) rather than raw protocol packets. Automations compile through Workflow Studio and policy gates. Safety-critical device classes require stronger confirmation and cannot be silently learned as routines. State reconciliation distinguishes desired vs observed state.

## Acceptance criteria
- [ ] Typed device/capability/state schema and discovery approval.
- [ ] Desired/observed state reconciliation and offline status.
- [ ] Per-device/room permissions and audit trail.
- [ ] Automation integrates with workflows/schedules without bypassing approvals.
- [ ] Raw protocol access is not exposed to general model prompts by default.

## Likely files
`backend/app/iot/`, workflow nodes, Settings/Home UI, tests.
