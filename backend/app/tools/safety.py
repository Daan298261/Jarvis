from __future__ import annotations

import re
from pathlib import Path

from .base import RiskLevel

IRREVERSIBLE_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",
    r"remove-item\s+.*-recurse.*(c:\\|windows|system32)",
    r"rmdir\s+/s\s+/q\s+[c-z]:\\",
    r"bcdedit",
    r"disable.*(defender|firewall|bitlocker)",
    r"net\s+user\s+\S+\s+\S+",
    r"shutdown\s+/s",
    r"Remove-WindowsFeature",
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

EXTERNAL_COMMS = [
    r"send-mail",
    r"curl\s+.*-d\s+",
    r"invoke-restmethod\s+.*-method\s+post",
]


def classify_command(command: str) -> RiskLevel:
    text = command.lower()
    for pattern in IRREVERSIBLE_PATTERNS:
        if re.search(pattern, text, re.I):
            return RiskLevel.IRREVERSIBLE
    for pattern in HIGH_IMPACT_PATTERNS:
        if re.search(pattern, text, re.I):
            return RiskLevel.HIGH
    for pattern in EXTERNAL_COMMS:
        if re.search(pattern, text, re.I):
            return RiskLevel.HIGH
    return RiskLevel.MEDIUM


def needs_confirmation(autonomy: str, risk: RiskLevel, command: str | None = None) -> bool:
    if command:
        risk = max(risk, classify_command(command), key=lambda item: list(RiskLevel).index(item))
    autonomy = (autonomy or "trusted").lower()
    if autonomy == "interactive":
        return risk in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.IRREVERSIBLE}
    if autonomy == "trusted":
        return risk in {RiskLevel.HIGH, RiskLevel.IRREVERSIBLE}
    return risk == RiskLevel.IRREVERSIBLE


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
