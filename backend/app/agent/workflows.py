from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import data_dir

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@dataclass
class WorkflowParameter:
    key: str
    label: str
    default: str = ""
    placeholder: str = ""
    help: str = ""


@dataclass
class WorkflowStep:
    title: str
    prompt: str


@dataclass
class Workflow:
    id: str
    name: str
    description: str
    category: str
    execution_mode: str = "balanced"
    builtin: bool = False
    parameters: list[WorkflowParameter] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "execution_mode": self.execution_mode,
            "builtin": self.builtin,
            "parameters": [asdict(item) for item in self.parameters],
            "steps": [asdict(item) for item in self.steps],
        }


def workflows_dir() -> Path:
    path = data_dir() / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def render_template(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return values[key]
        return match.group(0)

    return PLACEHOLDER.sub(replace, text or "")


def compose_prompt(workflow: Workflow, values: dict[str, str] | None = None) -> str:
    filled = values or {}
    stages: list[str] = []
    for index, step in enumerate(workflow.steps, 1):
        body = render_template(step.prompt, filled).strip()
        title = render_template(step.title, filled).strip() or f"Stage {index}"
        stages.append(f"Stage {index} — {title}\n{body}")
    joined = "\n\n".join(stages) or render_template(workflow.description, filled)
    return (
        f"You will execute this workflow as one autonomous task. Complete every stage in order. "
        f"Do not stop between stages unless you are genuinely blocked.\n\n"
        f"Workflow: {workflow.name}\n"
        f"{workflow.description}\n\n"
        f"{joined}\n\n"
        "After the last stage, independently verify the end state and report what was done, "
        "what changed, what was verified, and anything unresolved."
    )


def _param(key: str, label: str, default: str = "", placeholder: str = "", help: str = "") -> WorkflowParameter:
    return WorkflowParameter(key=key, label=label, default=default, placeholder=placeholder, help=help)


def _step(title: str, prompt: str) -> WorkflowStep:
    return WorkflowStep(title=title, prompt=prompt)


def builtin_workflows() -> list[Workflow]:
    return [
        Workflow(
            id="debug-project",
            name="Debug a project",
            description="Find why a project fails, fix it, and verify the fix without being told the cause.",
            category="engineering",
            execution_mode="reliable",
            builtin=True,
            parameters=[
                _param("path", "Project path", placeholder="C:\\Users\\...\\project", help="Folder that contains the broken project."),
                _param("command", "How to run it", default="pytest", placeholder="pytest / npm test / python app.py"),
            ],
            steps=[
                _step("Inspect", "Inspect {{path}}. Identify the project type, how it is supposed to run, and the current error. Do not assume the cause."),
                _step("Reproduce", "Run `{{command}}` (or the project's real test/start command) and capture the failure."),
                _step("Fix", "Fix the root cause in {{path}}. Prefer the smallest correct change. Create a git checkpoint before large edits."),
                _step("Verify", "Re-run `{{command}}` and confirm the original failure is gone. Only then report completion."),
            ],
        ),
        Workflow(
            id="research-spreadsheet",
            name="Research to spreadsheet",
            description="Research a topic, compare findings, and save a structured spreadsheet.",
            category="research",
            execution_mode="balanced",
            builtin=True,
            parameters=[
                _param("topic", "Topic", placeholder="Compare local LLM inference servers"),
                _param("output", "Output workbook path", placeholder="C:\\Users\\...\\Documents\\research.xlsx"),
                _param("criteria", "Compare on", default="price, quality, Windows support, local-only operation"),
            ],
            steps=[
                _step("Research", "Research {{topic}}. Prefer primary sources. Capture facts, not marketing copy."),
                _step("Compare", "Compare the findings on: {{criteria}}. Drop anything you cannot verify."),
                _step("Save", "Save a useful spreadsheet to {{output}} with headers, one row per item, and a short notes column. Use the office tool (app=excel). It uses COM when Office is installed and openpyxl otherwise."),
                _step("Verify", "Reopen {{output}}, confirm it parses, and check that the requested columns and rows are present."),
            ],
        ),
        Workflow(
            id="organize-files",
            name="Organize files",
            description="Batch-organize files in a folder using filesystem tools, not Explorer GUI.",
            category="filesystem",
            execution_mode="balanced",
            builtin=True,
            parameters=[
                _param("path", "Folder to organize", placeholder="C:\\Users\\...\\Downloads"),
                _param("scheme", "Organization scheme", default="by type into subfolders, keep names, do not delete"),
            ],
            steps=[
                _step("Inspect", "List {{path}} and summarize what is there (counts by type, obvious clutter)."),
                _step("Plan folders", "Choose destination folders for scheme: {{scheme}}. Do not delete anything unless the scheme explicitly says so."),
                _step("Move", "Create the folders and move files with the filesystem tool. Preserve originals if a name would collide."),
                _step("Verify", "Re-list {{path}} and confirm files landed where the scheme required. Report what moved."),
            ],
        ),
        Workflow(
            id="browser-extract",
            name="Open a site and extract",
            description="Open a public website, extract requested information, and save it to a file.",
            category="browser",
            execution_mode="balanced",
            builtin=True,
            parameters=[
                _param("url", "URL", default="https://example.com", placeholder="https://example.com"),
                _param("extract", "What to extract", default="the page title"),
                _param("output", "Save to", placeholder="C:\\Users\\...\\Desktop\\page-title.txt"),
            ],
            steps=[
                _step("Open", "Open {{url}} in the browser. Confirm the page actually loaded."),
                _step("Extract", "Extract: {{extract}}. Prefer the accessibility snapshot or page title over screenshots."),
                _step("Save", "Write the extracted information to {{output}}."),
                _step("Verify", "Read {{output}} back and confirm it contains the extracted information."),
            ],
        ),
        Workflow(
            id="browser-form",
            name="Fill a web form",
            description="Open a page, fill named fields, submit, and save confirmation.",
            category="browser",
            execution_mode="balanced",
            builtin=True,
            parameters=[
                _param("url", "Form URL", placeholder="https://example.com/contact"),
                _param("fields", "Fields to fill", default="name, email, message — use the values given in the task"),
                _param("submit", "Submit control name", default="Submit"),
                _param("output", "Confirmation notes", placeholder="C:\\Users\\...\\Desktop\\form-result.txt"),
            ],
            steps=[
                _step("Open", "Open {{url}} in the browser. Wait until the form is visible."),
                _step("Fill", "Fill these fields using accessible names or CSS selectors, not snapshot element ids: {{fields}}."),
                _step("Submit", "Click the control named {{submit}}. Confirm the page responded."),
                _step("Save", "Write what was submitted and the resulting page title/URL to {{output}}."),
                _step("Verify", "Re-read {{output}} and reopen {{url}} only if confirmation is missing."),
            ],
        ),
        Workflow(
            id="browser-procedure",
            name="Repeat a known browser procedure",
            description="Replay a structured web procedure (named clicks and fills) instead of rediscovering the UI.",
            category="browser",
            execution_mode="balanced",
            builtin=True,
            parameters=[
                _param("url", "Starting URL", placeholder="https://example.com/app"),
                _param("procedure", "Procedure", default="open the editor, fill title and body, publish"),
                _param("title", "Title / name", placeholder="Weekly notes"),
                _param("content", "Body / payload", placeholder="The text to publish or save"),
                _param("output", "Result notes", placeholder="C:\\Users\\...\\Desktop\\browser-procedure.txt"),
            ],
            steps=[
                _step("Open", "Open {{url}}. If a matching browser skill exists, run that skill instead of exploring."),
                _step("Replay", "Carry out: {{procedure}}. Use title={{title}} and content={{content}}. Click by accessible name or CSS selector. Do not rediscover the layout if named controls work."),
                _step("Confirm", "Read the resulting page and confirm the procedure actually completed."),
                _step("Save", "Write URL, what changed, and how it was verified to {{output}}."),
                _step("Verify", "Re-read {{output}} and, if possible, reopen the result page to confirm the change is still there."),
            ],
        ),
        Workflow(
            id="web-scrape-save",
            name="Collect pages into notes",
            description="Fetch several related pages and save a structured notes file.",
            category="research",
            execution_mode="balanced",
            builtin=True,
            parameters=[
                _param("urls", "URLs (comma or newline separated)", placeholder="https://example.com, https://example.org"),
                _param("question", "What to collect", default="title and a 3-sentence summary of each page"),
                _param("output", "Notes file", placeholder="C:\\Users\\...\\Documents\\notes.md"),
            ],
            steps=[
                _step("Fetch", "Read these pages (web_fetch when enough, browser when the page needs rendering): {{urls}}"),
                _step("Extract", "For each page collect: {{question}}. Skip pages that fail and note why."),
                _step("Save", "Write a markdown notes file to {{output}} with one section per URL."),
                _step("Verify", "Re-read {{output}} and confirm every successful URL has a section."),
            ],
        ),
        Workflow(
            id="maintenance-job",
            name="Multi-step maintenance",
            description="Inspect, update, test, and report on a local project in one run.",
            category="engineering",
            execution_mode="reliable",
            builtin=True,
            parameters=[
                _param("path", "Project path", placeholder="C:\\Users\\...\\project"),
                _param("update", "Update action", default="install dependencies and run the test suite"),
                _param("report", "Report path", placeholder="C:\\Users\\...\\Desktop\\maintenance-report.txt"),
            ],
            steps=[
                _step("Inspect", "Inspect {{path}}: git status, dependency files, and how tests are run."),
                _step("Update", "Perform: {{update}}. Stay inside the project. Do not push or publish."),
                _step("Test", "Run the project's tests or a basic functional check. Capture pass/fail."),
                _step("Report", "Write {{report}} covering what was inspected, what changed, test result, and leftovers."),
            ],
        ),
    ]


GUIDE_SECTIONS: list[dict[str, str]] = [
    {
        "id": "command",
        "title": "Command bar",
        "body": (
            "On Command, describe the end state you want — not the clicks. "
            "Jarvis plans, uses tools, recovers from errors, and verifies before it reports done. "
            "\"Command executed\" is not success; the file, site, or project must actually be in the requested state."
        ),
    },
    {
        "id": "modes",
        "title": "Execution modes",
        "body": (
            "Fast: short loop, basic verification. Balanced (default): plan, act, correct, verify. "
            "Reliable: three candidate plans, critic picks one, and verification must use a tool. "
            "These are agent modes. Model profiles Fast/Balanced/Quality only change quantization, thinking, and context."
        ),
    },
    {
        "id": "auth",
        "title": "Private key",
        "body": (
            "When LAN or remote access is on, every API call needs X-Jarvis-Key, "
            "Authorization: Bearer, or ?key=. Generate or paste the key on Settings. "
            "The portal stores the client copy in this browser only. "
            "On a phone, open /phone, Add to Home screen, and paste the same key there."
        ),
    },
    {
        "id": "queue",
        "title": "Launch queue",
        "body": (
            "Drop a .json or .prompt file into data/queue/pending/ and Jarvis picks it up. "
            "start-jarvis.ps1 -Prompt \"...\" -Wait runs one task at boot. "
            "Use this for unattended jobs instead of babysitting the Command box."
        ),
    },
    {
        "id": "voice",
        "title": "Voice",
        "body": (
            "Command has a Speak button. Audio is transcribed locally with Whisper when installed "
            "(faster-whisper, whisper.cpp, or a model in models/whisper/). "
            "Spoken results use Windows SAPI, espeak-ng, or pyttsx3. "
            "Nothing is sent to a cloud speech API. If STT is missing, type the command as usual."
        ),
    },
    {
        "id": "memory",
        "title": "Memory and skills",
        "body": (
            "Finished tasks store a trajectory (tools, failures, recovery) — never hidden reasoning. "
            "A workflow is promoted to a skill only after the same task class succeeds three or more times "
            "with the same tool sequence. Browser procedures that click named controls or CSS selectors "
            "(not snapshot ids like e12) become BrowserCode-style skills and replay instead of rediscovering the page. "
            "Enable, disable, or run skills on Memory."
        ),
    },
    {
        "id": "workflows",
        "title": "This tab",
        "body": (
            "Load a template, fill the parameters, edit or chain stages, then Run. "
            "That dispatches one autonomous task with every stage in order. "
            "Save your edited version as a local preset under data/workflows/ for one-click reuse."
        ),
    },
]


def workflow_from_dict(payload: dict[str, Any], *, builtin: bool | None = None) -> Workflow:
    parameters = [
        WorkflowParameter(
            key=str(item.get("key") or "").strip(),
            label=str(item.get("label") or item.get("key") or "").strip(),
            default=str(item.get("default") or ""),
            placeholder=str(item.get("placeholder") or ""),
            help=str(item.get("help") or ""),
        )
        for item in (payload.get("parameters") or [])
        if str(item.get("key") or "").strip()
    ]
    steps = [
        WorkflowStep(title=str(item.get("title") or "").strip(), prompt=str(item.get("prompt") or "").strip())
        for item in (payload.get("steps") or [])
        if str(item.get("prompt") or "").strip()
    ]
    workflow_id = str(payload.get("id") or "").strip() or str(uuid.uuid4())
    return Workflow(
        id=workflow_id,
        name=str(payload.get("name") or "Untitled workflow").strip() or "Untitled workflow",
        description=str(payload.get("description") or "").strip(),
        category=str(payload.get("category") or "custom").strip() or "custom",
        execution_mode=str(payload.get("execution_mode") or "balanced").strip() or "balanced",
        builtin=builtin if builtin is not None else bool(payload.get("builtin")),
        parameters=parameters,
        steps=steps,
    )


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()
    return slug[:80] or str(uuid.uuid4())


def load_saved_workflows() -> list[Workflow]:
    items: list[Workflow] = []
    root = workflows_dir()
    if not root.exists():
        return items
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        workflow = workflow_from_dict(payload, builtin=False)
        if not workflow.id:
            workflow.id = path.stem
        items.append(workflow)
    return items


def list_workflows() -> list[Workflow]:
    saved = {item.id: item for item in load_saved_workflows()}
    items: list[Workflow] = []
    for builtin in builtin_workflows():
        items.append(saved.pop(builtin.id, builtin))
    items.extend(saved.values())
    return items


def get_workflow(workflow_id: str) -> Workflow | None:
    for item in list_workflows():
        if item.id == workflow_id:
            return item
    return None


def save_workflow(payload: dict[str, Any]) -> Workflow:
    workflow = workflow_from_dict(payload, builtin=False)
    if any(item.id == workflow.id and item.builtin for item in builtin_workflows()):
        workflow.id = f"{workflow.id}-custom"
    if not workflow.steps:
        raise ValueError("A workflow needs at least one step")
    root = workflows_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_safe_slug(workflow.id)}.json"
    path.write_text(json.dumps(workflow.to_dict(), indent=2), encoding="utf-8")
    return workflow


def delete_workflow(workflow_id: str) -> bool:
    if any(item.id == workflow_id and item.builtin for item in builtin_workflows()):
        raise PermissionError("Built-in templates cannot be deleted")
    root = workflows_dir()
    if not root.exists():
        return False
    path = root / f"{_safe_slug(workflow_id)}.json"
    if not path.exists():
        for candidate in root.glob("*.json"):
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("id") == workflow_id:
                candidate.unlink()
                return True
        return False
    path.unlink()
    return True


def merge_parameter_values(workflow: Workflow, values: dict[str, str] | None) -> dict[str, str]:
    merged = {item.key: item.default for item in workflow.parameters}
    for key, value in (values or {}).items():
        if value is None:
            continue
        merged[str(key)] = str(value)
    return merged
