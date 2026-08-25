from __future__ import annotations

from dataclasses import dataclass, field


ALTERNATES: dict[str, list[str]] = {
    "filesystem": ["python", "terminal"],
    "terminal": ["python", "filesystem"],
    "python": ["terminal", "filesystem", "openhands", "open_interpreter"],
    "browser": ["web_fetch", "screenshot", "browser_use"],
    "browser_use": ["browser", "web_fetch"],
    "web_fetch": ["browser"],
    "desktop": ["screenshot", "ufo", "cua", "browser", "filesystem"],
    "ufo": ["cua", "desktop", "screenshot"],
    "cua": ["desktop", "screenshot"],
    "office": ["python", "filesystem"],
    "screenshot": ["desktop", "browser"],
    "docker": ["terminal", "python"],
    "git": ["terminal", "openhands"],
    "openhands": ["filesystem", "python", "terminal", "git"],
    "open_interpreter": ["python", "terminal", "filesystem"],
}


def classify_error(tool: str, arguments: dict, output: str) -> str:
    text = (output or "").lower()
    if any(s in text for s in ("not exist", "not found", "no such", "cannot find", "missing")):
        return "missing"
    if any(s in text for s in ("permission", "access is denied", "denied", "unauthorized", "outside allowed")):
        return "permission"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(s in text for s in ("not installed", "unavailable", "not available", "no module")):
        return "unavailable"
    if "blocked" in text and "identical" in text:
        return "repeat"
    return "error"


OPTIONAL_WORKERS = {"browser_use", "ufo", "cua", "openhands", "open_interpreter", "docker"}


def alternate_tools(failed: str) -> list[str]:
    names = [name for name in ALTERNATES.get(failed, ["filesystem", "python", "terminal"]) if name != failed]
    try:
        from .routing import get_workers

        workers = get_workers()
        names = [name for name in names if name not in workers or workers[name].available]
    except Exception:
        names = [name for name in names if name not in OPTIONAL_WORKERS]
    return names


@dataclass
class RecoveryPlan:
    failed_tool: str
    classification: str
    avoid_tools: list[str]
    prefer_tools: list[str]
    prompt: str


@dataclass
class RecoveryTracker:
    """After repeated failure, force a different tool or strategy."""

    fail_streak: int = 0
    fail_by_tool: dict[str, int] = field(default_factory=dict)
    last_tool: str = ""
    last_error: str = ""
    last_class: str = ""
    last_action: str = ""
    issued_for: set[str] = field(default_factory=set)
    avoid_tools: set[str] = field(default_factory=set)
    last_plan: RecoveryPlan | None = None
    fail_after_tool: int = 2
    fail_after_streak: int = 3

    def record(self, name: str, arguments: dict, success: bool, output: str, blocked: bool = False) -> RecoveryPlan | None:
        if success and not blocked:
            self.fail_streak = 0
            self.fail_by_tool[name] = 0
            self.avoid_tools.clear()
            return None
        action = str(arguments.get("action") or arguments.get("command") or "")
        kind = classify_error(name, arguments, output)
        self.fail_streak += 1
        self.fail_by_tool[name] = self.fail_by_tool.get(name, 0) + 1
        self.last_tool = name
        self.last_error = (output or "")[:800]
        self.last_class = kind
        self.last_action = action
        if self.fail_by_tool[name] >= self.fail_after_tool or self.fail_streak >= self.fail_after_streak:
            return self.make_plan(name, arguments, kind)
        return None

    def make_plan(self, failed: str, arguments: dict, kind: str) -> RecoveryPlan:
        prefer = alternate_tools(failed)
        avoid = [failed]
        extra = ""
        if kind == "missing":
            extra = (
                "A path was missing. Use the Windows user profile or Desktop from the environment "
                "block. Do not retry the missing path."
            )
        elif kind == "unavailable":
            extra = "That tool or dependency is unavailable. Use a native alternative."
        elif kind == "permission":
            extra = "Write under an allowed directory such as Desktop or the task folder."
        elif kind == "repeat":
            extra = "The identical call was blocked. Change both tool and arguments."
        prompt = (
            f"RECOVERY: `{failed}` failed repeatedly ({kind}). "
            f"Do not call `{failed}` again for this sub-goal.\n"
            f"Switch strategy. Preferred tools: {', '.join(prefer) or 'any other enabled tool'}.\n"
            f"{extra}\n"
            f"Last error:\n{self.last_error[:500]}"
        ).strip()
        plan = RecoveryPlan(
            failed_tool=failed,
            classification=kind,
            avoid_tools=avoid,
            prefer_tools=prefer,
            prompt=prompt,
        )
        self.last_plan = plan
        self.issued_for.add(failed)
        self.avoid_tools.add(failed)
        return plan

    def tools_for_next_round(self, schemas: list[dict]) -> list[dict]:
        if not self.avoid_tools:
            return schemas
        filtered = [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") not in self.avoid_tools
        ]
        return filtered or schemas
