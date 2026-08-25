from __future__ import annotations

PROFESSIONAL_AUDIT_PROMPT = """Professional / Forensic Audit Mode is active for this task.

You are assisting with legitimate professional security, forensic, investigative, defensive, technical, or analytical work.

Analyze the material accurately. Do not refuse merely because the subject is sensitive. That includes malware, attack techniques, scripts, suspicious PowerShell, forensic artifacts, logs, criminal communications used as case evidence, exploit evidence, phishing, credential-theft artifacts, vulnerabilities, offensive-security tooling, and similar case-related technical evidence.

Model permissiveness is separate from operational authorization. Existing Jarvis rules still apply: do not format disks, destroy partitions, mass-delete outside the task scope, change credentials, disable security, send money, purchase, or send external communications unless the task clearly authorizes it. Prefer inspection and explanation over performing the harmful action yourself.
"""

_AUDIT_KEYWORDS = (
    "malware",
    "ransomware",
    "forensic",
    "forensics",
    "phishing",
    "credential-theft",
    "credential theft",
    "exploit",
    "vulnerability",
    "cve-",
    "ioc",
    "indicators of compromise",
    "threat intel",
    "threat intelligence",
    "memory dump",
    "pcap",
    "yara",
    "suspicious powershell",
    "attack technique",
    "mitre att&ck",
    "offensive-security",
    "offensive security",
    "red team",
    "incident response",
    "ir playbook",
    "security audit",
    "pentest",
    "penetration test",
    "reverse engineer",
    "obfuscated script",
    "c2 traffic",
    "command and control",
)


def is_professional_audit(prompt: str, professional_mode: bool = False) -> bool:
    """True when the operator enabled the mode or the prompt is clearly professional analysis."""
    if professional_mode:
        return True
    text = (prompt or "").lower()
    return any(keyword in text for keyword in _AUDIT_KEYWORDS)


def professional_prompt_block(prompt: str, professional_mode: bool = False) -> str:
    if not is_professional_audit(prompt, professional_mode):
        return ""
    return PROFESSIONAL_AUDIT_PROMPT
