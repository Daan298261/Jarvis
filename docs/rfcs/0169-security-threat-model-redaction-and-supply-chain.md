# RFC-0169: Security baseline — threat model, redaction and supply chain

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Security features exist across RFCs but need one enforceable baseline as Anzu becomes an agent platform.

## Decision
Maintain a versioned threat model covering local attacker, malicious webpage/document, compromised plugin/MCP, poisoned model/package, impersonated node/channel and accidental owner action. Centralize redaction for logs/events/artifacts, dependency/SBOM generation, signature/hash verification and vulnerability policy. Security-sensitive defaults fail closed. Add security regression corpus for prompt injection, confused-deputy and permission-escalation attempts.

## Acceptance criteria
- [ ] Threat model maps threats to controls/tests/owners.
- [ ] Release produces SBOM and dependency provenance.
- [ ] Central redaction prevents known secret/token formats entering logs.
- [ ] Untrusted content cannot grant permissions or change system policy.
- [ ] Supply-chain verification is shared by installer/modules/plugins/model packs.
- [ ] Security regression suite is a release gate.

## Likely files
Security/policy, logging/events, installers/package managers, CI/tests.
