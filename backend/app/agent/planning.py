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
    best_of_n: int = 1


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
        description="Stronger planning, best-of-N plan selection, a critic pass, and tool-backed verification.",
        best_of_n=3,
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
    scored: list[tuple[int, str]] = []
    for name, keywords in TASK_CATEGORIES:
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            scored.append((score, name))
    if not scored:
        return "mixed"
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) >= 3:
        return "long-horizon autonomous"
    if len(scored) >= 2 and scored[0][0] == scored[1][0]:
        return "mixed"
    return scored[0][1]


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


_CANDIDATE_HEADER = re.compile(
    r"^(?:#{1,3}\s*)?(?:PLAN|CANDIDATE|OPTION)\s+([A-Z]|[1-9])\b\s*:?\s*(.*)$",
    re.IGNORECASE,
)
_SELECT_PLAN = re.compile(
    r"(?:SELECTED|CHOICE|PICK(?:ED)?)\s*[:\-]\s*(?:PLAN|CANDIDATE|OPTION)?\s*([A-Z]|[1-9])\b"
    r"|best\s+(?:plan|candidate|option)\s+(?:is\s+)?([A-Z]|[1-9])\b"
    r"|I\s+(?:choose|pick|select)\s+(?:plan|candidate|option)?\s*([A-Z]|[1-9])\b",
    re.IGNORECASE,
)


@dataclass
class PlanCandidate:
    label: str
    end_state: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    raw: str = ""

    def as_parsed(self) -> dict[str, Any]:
        return {
            "end_state": self.end_state,
            "acceptance_criteria": list(self.acceptance_criteria),
            "plan": list(self.plan),
        }


def parse_plan_candidates(text: str) -> list[PlanCandidate]:
    """Split a best-of-N planning reply into labeled PLAN A/B/C candidates."""
    blocks: list[tuple[str, list[str]]] = []
    current_label: str | None = None
    current_lines: list[str] = []
    for raw in (text or "").splitlines():
        match = _CANDIDATE_HEADER.match(raw.strip())
        if match:
            if current_label is not None:
                blocks.append((current_label, current_lines))
            current_label = match.group(1).upper()
            rest = (match.group(2) or "").strip()
            current_lines = [rest] if rest else []
            continue
        if current_label is not None:
            current_lines.append(raw)
    if current_label is not None:
        blocks.append((current_label, current_lines))

    candidates: list[PlanCandidate] = []
    for label, lines in blocks:
        body = "\n".join(lines).strip()
        parsed = parse_plan_block(body)
        if not parsed["plan"] and not parsed["end_state"]:
            steps = [re.sub(r"^[-*\d.\s]+", "", line.strip()) for line in lines if line.strip()]
            parsed["plan"] = [step for step in steps if step]
        candidates.append(
            PlanCandidate(
                label=label,
                end_state=parsed["end_state"],
                acceptance_criteria=parsed["acceptance_criteria"],
                plan=parsed["plan"],
                raw=body,
            )
        )
    return candidates


def score_plan_candidate(candidate: PlanCandidate) -> tuple[int, ...]:
    """Prefer inspect-first, verifiable, deterministic plans when the critic is unclear."""
    text = " ".join(candidate.plan).lower()
    first = (candidate.plan[0] if candidate.plan else "").lower()
    inspect = 1 if any(word in first for word in ("inspect", "read", "list", "check", "look", "stat")) else 0
    visual = 1 if any(word in first for word in ("click", "screenshot", "mouse", "coordinate")) else 0
    verify = 1 if "verif" in text else 0
    backup = 1 if ("backup" in text or first.startswith("copy") or "preserve" in text) else 0
    criteria = min(len(candidate.acceptance_criteria), 6)
    length_penalty = min(len(candidate.plan), 20)
    return (inspect, verify, backup, -visual, criteria, -length_penalty)


def select_best_plan(candidates: list[PlanCandidate], critic_text: str) -> PlanCandidate:
    """Pick the critic's chosen plan, or the highest-scoring candidate if the choice is unclear."""
    if not candidates:
        raise ValueError("no plan candidates")
    by_label = {candidate.label.upper(): candidate for candidate in candidates}
    match = _SELECT_PLAN.search(critic_text or "")
    if match:
        label = next((group for group in match.groups() if group), "").upper()
        if label in by_label:
            return by_label[label]
        if label.isdigit():
            index = int(label) - 1
            if 0 <= index < len(candidates):
                return candidates[index]
    return max(candidates, key=score_plan_candidate)


def best_of_n_plan_prompt(n: int) -> str:
    count = max(2, min(int(n or 3), 5))
    labels = ", ".join(f"PLAN {chr(ord('A') + i)}" for i in range(count))
    return (
        f"Before using tools, propose {count} distinct candidate strategies labeled {labels}.\n"
        "Each candidate MUST use this shape:\n"
        "PLAN A\n"
        "END STATE:\n"
        "...\n"
        "ACCEPTANCE CRITERIA:\n"
        "- ...\n"
        "PLAN:\n"
        "1. ...\n\n"
        "The candidates must differ in strategy (for example library vs CLI vs GUI, "
        "or inspect-first vs change-first). Do not execute yet. Do not call tools yet."
    )


def best_of_n_select_prompt(candidates: list[PlanCandidate]) -> str:
    summaries = []
    for candidate in candidates:
        steps = "; ".join(candidate.plan[:6]) or "(no steps parsed)"
        summaries.append(f"- PLAN {candidate.label}: {candidate.end_state or 'same end state'} | {steps}")
    listed = "\n".join(summaries)
    return (
        "Critique these candidate plans. Prefer the most deterministic path "
        "(API, library, or CLI before GUI or vision). Do not execute several complete attempts.\n"
        f"{listed}\n\n"
        "Then output exactly:\n"
        "SELECTED: <letter>\n"
        "REASON: <one paragraph>\n\n"
        "Do not call tools yet."
    )


def format_selected_plan(candidate: PlanCandidate) -> str:
    criteria = "\n".join(f"- {item}" for item in candidate.acceptance_criteria) or "- (same as the request)"
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(candidate.plan, 1)) or "(execute toward the end state)"
    return (
        f"The selected plan is PLAN {candidate.label}. Execute this plan with tools now. "
        "Do not wait for the user.\n\n"
        f"END STATE: {candidate.end_state or '(same as the user request)'}\n"
        f"ACCEPTANCE CRITERIA:\n{criteria}\n"
        f"PLAN:\n{steps}"
    )


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
    escalated: bool = False

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
