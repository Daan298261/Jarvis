from __future__ import annotations

import re
from pathlib import Path

from .base import RiskLevel

IRREVERSIBLE_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",
    r"remove-item\s+.*-recurse.*(?:[c-z]:\\(?:\s|$)|\\windows\\|\\system32\\|program files)",
    r"rmdir\s+/s\s+/q\s+[c-z]:\\(?:\s|$)",
    r"rm\s+-rf\s+(?:/|~)(?:\s|$)",
    r"rm\s+-rf\s+[c-z]:\\(?:windows|users)(?:\\|\s|$)",
    r"bcdedit",
    r"disable.*(defender|firewall|bitlocker)",
    r"net\s+user\s+\S+\s+\S+",
    r"new-localuser",
    r"set-localuser.*password",
    r"set-adaccountpassword",
    r"(?:^|[;&|]\s*)passwd(?:\s+\S+)?\s*$",
    r"shutdown\s+/s",
    r"Remove-WindowsFeature",
    r"wbadmin\s+delete",
    r"vssadmin\s+delete",
    r"send-mail",
    r"send-mailmessage",
    r"curl\s+.*-d\s+",
    r"invoke-restmethod\s+.*-method\s+post",
    r"\b(paypal\.com|stripe checkout|buy now|send.?money|wire.?transfer|venmo)\b",
    r"\b(make a purchase|complete(?: the)? purchase|purchase now)\b",
]

HIGH_IMPACT_PATTERNS = [
    r"remove-item\s+.*-recurse",
    r"rm\s+-rf\s+",
    r"git\s+push\s+.*--force",
    r"git\s+reset\s+--hard",
    r"drop\s+database",
    r"invoke-webrequest.*\|.*iex",
    r"iwr\s+.*\|\s*iex",
]

PATTERN_REASONS = (
    (r"\bformat\s+[a-z]:|\bdiskpart\b|\bcipher\s+/w", "disk formatting or partition destruction"),
    (r"wbadmin\s+delete|vssadmin\s+delete", "destroying backups"),
    (r"remove-item\s+.*-recurse.*(c:\\|windows|system32)|rmdir\s+/s\s+/q\s+[c-z]:\\|rm\s+-rf\s+(/|~ )", "mass deletion outside task scope"),
    (r"net\s+user|set-localuser.*password|set-adaccountpassword|(?:^|[;&|]\s*)passwd(?:\s+\S+)?\s*$|new-localuser", "credential changes"),
    (r"paypal\.com|stripe checkout|buy now|send.?money|wire.?transfer|venmo|make a purchase|complete(?: the)? purchase|purchase now", "financial transaction or purchase"),
    (r"disable.*(defender|firewall|bitlocker)|bcdedit|Remove-WindowsFeature", "disabling system security controls"),
    (r"send-mail|send-mailmessage|curl\s+.*-d\s+|invoke-restmethod\s+.*-method\s+post", "external send / publish"),
    (r"remove-item\s+.*-recurse|rm\s+-rf\s+", "recursive deletion"),
    (r"git\s+push\s+.*--force|git\s+reset\s+--hard", "destructive git rewrite"),
    (r"drop\s+database", "database drop"),
    (r"invoke-webrequest.*\|.*iex|iwr\s+.*\|\s*iex", "remote code execution"),
)


def classify_command(command: str) -> RiskLevel:
    text = command.lower()
    for pattern in IRREVERSIBLE_PATTERNS:
        if re.search(pattern, text, re.I):
            return RiskLevel.IRREVERSIBLE
    for pattern in HIGH_IMPACT_PATTERNS:
        if re.search(pattern, text, re.I):
            return RiskLevel.HIGH
    return RiskLevel.MEDIUM


def command_reason(command: str | None) -> str | None:
    if not command:
        return None
    text = command.lower()
    for pattern, reason in PATTERN_REASONS:
        if re.search(pattern, text, re.I):
            return reason
    return None


def needs_confirmation(autonomy: str, risk: RiskLevel, command: str | None = None) -> bool:
    from ..agent.autonomy import resolve_autonomy

    if command:
        risk = max(risk, classify_command(command), key=lambda item: list(RiskLevel).index(item))
    mode = resolve_autonomy(autonomy)
    return risk in mode.confirm_risks


def confirmation_detail(autonomy: str, risk: RiskLevel, name: str, command: str | None = None) -> str:
    from ..agent.autonomy import resolve_autonomy

    mode = resolve_autonomy(autonomy)
    reason = command_reason(command)
    if command:
        risk = max(risk, classify_command(command), key=lambda item: list(RiskLevel).index(item))
    parts = [f"{mode.label} mode requires confirmation for {name} ({risk.value})."]
    if reason:
        parts.append(f"Matched: {reason}.")
    return " ".join(parts)


def resolve_allowed_path(path: str, allowed: list[str]) -> Path:
    target = Path(path).expanduser().resolve()
    if not allowed:
        return target
    for root in allowed:
        base = Path(root).expanduser().resolve()
        try:
            target.relative_to(base)
            return target
        except ValueError:
            continue
    raise PermissionError(f"Path {target} is outside allowed directories")
