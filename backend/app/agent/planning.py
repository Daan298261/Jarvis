from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionPolicy:
    name: str
    max_steps: int
    max_verify_tools: int
    force_verify_after: int
    critic_pass: bool
    require_verify_tools: bool
    description: str


POLICIES: dict[str, ExecutionPolicy] = {
    "fast": ExecutionPolicy(
        name="fast",
        max_steps=16,
        max_verify_tools=1,
        force_verify_after=6,
        critic_pass=False,
        require_verify_tools=False,
        description="Minimal planning, deterministic tools, basic verification.",
    ),
    "balanced": ExecutionPolicy(
        name="balanced",
        max_steps=28,
        max_verify_tools=2,
        force_verify_after=8,
        critic_pass=False,
        require_verify_tools=False,
        description="Plan, execute, observe, correct, then independently verify.",
    ),
    "reliable": ExecutionPolicy(
        name="reliable",
        max_steps=40,
        max_verify_tools=3,
        force_verify_after=12,
        critic_pass=True,
        require_verify_tools=True,
        description="Stronger planning, a critic pass, and tool-backed verification.",
    ),
}

TASK_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("filesystem", ("folder", "directory", "rename", "copy files", "organize files", "desktop", "delete file")),
    ("shell", ("powershell", "command", "cmd ", "install", "wsl", "bash", "pip ", "npm ")),
    ("system administration", ("driver", "service", "windows update", "registry", "firewall", "disk")),
    ("software engineering", ("repository", "refactor", "debug", "pytest", "unit test", "compile", "fix this", "source code")),
    ("research", ("research", "compare products", "summarize", "look up")),
    ("browser automation", ("website", "browser", "web page", "login", "cms", "playwright")),
    ("windows gui", ("click", "window", "desktop app", "ui automation", "notepad")),
    ("office", ("word", "excel", "powerpoint", "docx", "xlsx", "manuscript", "spreadsheet")),
    ("document processing", ("pdf", "document", "formatting", "chapter")),
    ("data processing", ("csv", "json", "dataset", "logs", "parse")),
    ("multimodal", ("screenshot", "image", "vision", "screenshot")),
]


def resolve_execution_policy(name: str | None) -> ExecutionPolicy:
    key = (name or "balanced").strip().lower()
    return POLICIES.get(key, POLICIES["balanced"])


def classify_task(prompt: str) -> str:
    text = (prompt or "").lower()
    hits = [name for name, keywords in TASK_CATEGORIES if any(k in text for k in keywords)]
    if len(hits) >= 3:
        return "long-horizon autonomous"
    if len(hits) >= 2:
        return "mixed"
    if hits:
        return hits[0]
    return "mixed"


def parse_plan_block(text: str) -> dict[str, Any]:
    end_state = ""
    criteria: list[str] = []
    plan: list[str] = []
    section: str | None = None
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = re.sub(r"[:\s]+$", "", stripped.upper())
        if upper.startswith("END STATE"):
            section = "end"
            _, _, rest = stripped.partition(":")
            if rest.strip():
                end_state = rest.strip()
            continue
        if "ACCEPTANCE CRITERIA" in upper or upper.startswith("ACCEPTANCE"):
            section = "criteria"
            continue
        if upper.startswith("PLAN"):
            section = "plan"
            continue
        if section == "end":
            end_state = f"{end_state} {stripped}".strip() if end_state else stripped
        elif section == "criteria":
            criteria.append(re.sub(r"^[-*\d.\s]+", "", stripped).strip())
        elif section == "plan":
            plan.append(re.sub(r"^[-*\d.\s]+", "", stripped).strip())
    return {
        "end_state": end_state,
        "acceptance_criteria": [c for c in criteria if c],
        "plan": [p for p in plan if p],
    }


@dataclass
class WorkingState:
    goal: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    current_state: str = ""
    observations: list[str] = field(default_factory=list)
    recent_tool_outputs: list[str] = field(default_factory=list)
    known_failures: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_action: str = ""
    task_class: str = ""
    verified: bool = False

    def note_tool(self, name: str, observation: str, success: bool) -> None:
        snippet = f"{name}: {observation[:400]}"
        self.recent_tool_outputs = (self.recent_tool_outputs + [snippet])[-6:]
        if success:
            self.completed_steps = (self.completed_steps + [name])[-20:]
            self.observations = (self.observations + [snippet])[-8:]
        else:
            self.known_failures = (self.known_failures + [snippet])[-8:]
        self.current_state = snippet

    def apply_plan(self, parsed: dict[str, Any], prompt: str) -> None:
        if parsed.get("end_state"):
            self.goal = parsed["end_state"]
        elif not self.goal:
            self.goal = prompt.strip().splitlines()[0][:240]
        if parsed.get("acceptance_criteria"):
            self.acceptance_criteria = parsed["acceptance_criteria"]
        if parsed.get("plan"):
            self.plan = parsed["plan"]

    def as_prompt_block(self) -> str:
        criteria = "\n".join(f"- {c}" for c in self.acceptance_criteria) or "- (not yet captured)"
        plan = "\n".join(f"{i}. {step}" for i, step in enumerate(self.plan[:10], 1)) or "(in progress)"
        failures = "\n".join(f"- {item}" for item in self.known_failures[-4:]) or "- none"
        return (
            "Compact working state:\n"
            f"Goal: {self.goal or '(same as user request)'}\n"
            f"Task class: {self.task_class or 'mixed'}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Plan:\n{plan}\n"
            f"Current state: {self.current_state or 'starting'}\n"
            f"Known failures:\n{failures}\n"
            f"Next action: {self.next_action or 'continue'}\n"
            f"Verified: {self.verified}"
        )

    def dumps(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def loads(cls, raw: str | None) -> "WorkingState":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)
