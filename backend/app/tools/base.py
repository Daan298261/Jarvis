from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IRREVERSIBLE = "irreversible"


@dataclass
class ToolResult:
    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    truncated: bool = False

    def text(self, limit: int = 12000) -> str:
        payload = self.output if self.output else json.dumps(self.data, indent=2, default=str)
        if self.error:
            payload = f"ERROR: {self.error}\n{payload}"
        if len(payload) > limit:
            self.truncated = True
            payload = payload[:limit] + "\n...[truncated]..."
        return payload


class Tool:
    """Executable agent tool. Registered tools override execute()."""

    name: str
    description: str
    parameters: dict[str, Any]
    risk: RiskLevel = RiskLevel.MEDIUM
    enabled: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            False,
            "",
            error=f"Tool {getattr(self, 'name', type(self).__name__)} has no execute implementation",
        )
