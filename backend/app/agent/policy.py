from __future__ import annotations

import re

PROFESSIONAL_ANALYSIS_POLICY = """
Professional analysis policy:
Jarvis may be used for legitimate professional security, forensic, investigative, defensive, technical, or analytical work.
Analyze sensitive material accurately rather than refuse merely because the subject is sensitive.
Examples of analysis that must proceed: malware, attack techniques, scripts, suspicious PowerShell, forensic artifacts, logs, exploit evidence, phishing, credential-theft artifacts, vulnerabilities, offensive-security tooling, and other case-related technical evidence.

Model permissiveness is separate from operational authorization.
- Permitted by default: read, classify, explain, reconstruct, summarize, and recommend defenses.
- Still forbidden unless the task clearly authorizes it: sending exploits, changing credentials, disabling security, purchasing, sending external communications, deploying offensive tools against a live system the user does not own, formatting disks, or mass-deletion outside the task scope.
If asked only to analyze, do the analysis. If asked to operationalize an unauthorized attack, refuse the operational step and offer analysis or defense instead.
""".strip()

_ANALYSIS_MARKERS = (
    "analy",
    "forensic",
    "malware",
    "phishing",
    "exploit",
    "vulnerabilit",
    "incident",
    "ioc",
    "artifact",
    "log review",
    "triage",
    "investigate",
    "reverse",
    "disassembl",
    "yara",
    "siem",
    "credential-theft",
    "suspicious powershell",
    "offensive-security",
)

_UNAUTHORIZED_OPERATIONS = (
    r"\bdeploy (the )?(exploit|payload|ransomware)\b",
    r"\bsend (the )?(exploit|payload|malware)\b",
    r"\bdisable (defender|firewall|security|av)\b",
    r"\bchange (the )?(password|credentials|admin)\b",
    r"\bformat (the )?(disk|drive|partition)\b",
    r"\bpurchase\b",
    r"\bwire money\b",
    r"\battack (a |the )?(live |production )?(system|server|host)\b",
)

_AUTHORIZATION_MARKERS = (
    "authorized",
    "i own",
    "my machine",
    "this computer",
    "lab environment",
    "engagement",
    "scope includes",
    "written permission",
)


def professional_policy_block() -> str:
    return PROFESSIONAL_ANALYSIS_POLICY


def is_professional_analysis(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(marker in text for marker in _ANALYSIS_MARKERS)


def has_operational_authorization(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(marker in text for marker in _AUTHORIZATION_MARKERS)


def unauthorized_operational_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    if not text or has_operational_authorization(text):
        return False
    return any(re.search(pattern, text) for pattern in _UNAUTHORIZED_OPERATIONS)


def policy_guidance(prompt: str) -> str:
    parts = [PROFESSIONAL_ANALYSIS_POLICY]
    if is_professional_analysis(prompt):
        parts.append(
            "This request looks like professional analysis. Prefer accurate technical examination over refusal."
        )
    if unauthorized_operational_request(prompt):
        parts.append(
            "This request also asks for an operational action that is not clearly authorized. "
            "Analyze if asked, but do not perform the unauthorized operational step."
        )
    return "\n\n".join(parts)
