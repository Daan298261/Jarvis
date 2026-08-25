"""P0.9 — representative Jarvis agent benchmark suite.

Defines at least 20 realistic autonomous tasks, fixture preparation, outcome
checks, and a report format. Live 9B-vs-27B comparison still needs a Windows
GPU; this module is the dataset + scoring harness that comparison will use.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from ..db.models import AgentBenchmarkResult, Task, ToolCallRecord
from ..db.session import SessionLocal

SUITE_ID = "jarvis-agent-20"
SUITE_VERSION = 1

REQUIRED_CATEGORIES = (
    "filesystem_organization",
    "broken_python_diagnosis",
    "git_repository_modification",
    "powershell_troubleshooting",
    "browser_navigation",
    "unfamiliar_website",
    "tool_failure_recovery",
    "screenshot_interpretation",
    "multi_step_research",
    "document_processing",
    "multi_tool_autonomous",
    "verification_after_code_change",
    "json_config_update",
    "csv_transform",
    "compare_file_versions",
    "python_script_run",
    "git_status_checkpoint",
    "hash_and_stat",
    "terminal_command",
    "recent_backups",
)

METRIC_FIELDS = (
    "success",
    "human_intervention",
    "total_time_seconds",
    "model_time_seconds",
    "tool_time_seconds",
    "model_calls",
    "tool_calls",
    "retries",
    "schema_errors",
    "incorrect_actions",
    "verification_result",
)

PrepareFn = Callable[[Path], dict[str, str]]
CheckFn = Callable[[Path, dict[str, str]], tuple[bool, str]]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False)


def _git_identity(repo: Path) -> None:
    _run(["git", "config", "user.email", "jarvis-benchmark@local"], repo)
    _run(["git", "config", "user.name", "Jarvis Benchmark"], repo)


def _tiny_png(path: Path) -> None:
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
            "0000000c4944415408d763f8cf0000020101e2d26d3f0000000049454e44ae426082"
        )
    )


def _prep_filesystem(root: Path) -> dict[str, str]:
    messy = root / "messy-desktop"
    messy.mkdir(parents=True)
    (messy / "notes.txt").write_text("todo: file taxes\n", encoding="utf-8")
    (messy / "photo.jpg").write_bytes(b"not-a-real-jpeg")
    (messy / "invoice-2024.pdf").write_bytes(b"%PDF-fake")
    (messy / "song.mp3").write_bytes(b"ID3")
    (messy / "readme.md").write_text("# draft\n", encoding="utf-8")
    return {"workspace": str(messy), "organized": str(messy / "organized")}


def _check_filesystem(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    organized = Path(ctx["organized"])
    expected = {"docs", "images", "audio", "other"}
    if not organized.is_dir():
        return False, "organized/ directory missing"
    found = {p.name for p in organized.iterdir() if p.is_dir()}
    if not expected.issubset(found) and len(list(organized.rglob("*"))) < 5:
        return False, f"expected category folders {sorted(expected)}, found {sorted(found)}"
    return True, "files grouped into folders"


def _prep_broken_python(root: Path) -> dict[str, str]:
    project = root / "broken_primes"
    project.mkdir(parents=True)
    (project / "README.txt").write_text(
        "Run python main.py. It should write the first 100 primes to output.txt.\n",
        encoding="utf-8",
    )
    (project / "main.py").write_text(
        "from utils import first_primes\n\n"
        "if __name__ == '__main__':\n"
        "    values = first_primes(100)\n"
        "    from pathlib import Path\n"
        "    Path('output.txt').write_text('\\n'.join(str(v) for v in values), encoding='utf-8')\n"
        "    print(f'wrote {len(values)} primes')\n",
        encoding="utf-8",
    )
    (project / "utils.py").write_text(
        "def first_primes(n):\n"
        "    found = []\n"
        "    candidate = 2\n"
        "    while len(found) < n:\n"
        "        if is_prime(candidate):\n"
        "            found.append(candidate)\n"
        "        candidate += 1\n"
        "    return found\n",
        encoding="utf-8",
    )
    return {"project": str(project), "output": str(project / "output.txt")}


def _check_broken_python(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    output = Path(ctx["output"])
    if not output.exists():
        return False, "output.txt missing"
    lines = [line.strip() for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 100:
        return False, f"expected 100 primes, got {len(lines)}"
    return True, "first 100 primes written"


def _prep_git(root: Path) -> dict[str, str]:
    repo = root / "sample-repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello from sample-repo\n", encoding="utf-8")
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    _run(["git", "init"], repo)
    _git_identity(repo)
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return {"repo": str(repo)}


def _check_git(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    repo = Path(ctx["repo"])
    text = (repo / "app.py").read_text(encoding="utf-8")
    if "hello world" not in text.lower():
        return False, "greet() does not return hello world"
    return True, "repository file modified"


def _prep_shell(root: Path) -> dict[str, str]:
    script = root / "broken.sh"
    script.write_text("#!/bin/sh\necho hello\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    ps1 = root / "broken.ps1"
    ps1.write_text("Write-Output 'hello'\nexit 1\n", encoding="utf-8")
    return {"script": str(script), "powershell": str(ps1), "fixed": str(root / "fixed.sh")}


def _check_shell(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    fixed = Path(ctx["fixed"])
    if not fixed.exists():
        return False, "fixed.sh missing"
    result = _run(["sh", str(fixed)], root)
    if result.returncode != 0:
        return False, f"fixed.sh still fails: {result.stderr or result.stdout}"
    return True, "shell script exits 0"


def _prep_browser(root: Path) -> dict[str, str]:
    page = root / "example.html"
    page.write_text(
        "<!doctype html><html><head><title>Example Domain</title></head>"
        "<body><h1>Example Domain</h1><p>This is a local stand-in for example.com.</p></body></html>",
        encoding="utf-8",
    )
    return {"page": str(page), "result": str(root / "page-title.txt")}


def _check_browser(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    result = Path(ctx["result"])
    if not result.exists():
        return False, "page-title.txt missing"
    text = result.read_text(encoding="utf-8")
    if "Example Domain" not in text:
        return False, f"title not captured: {text[:80]}"
    return True, "page title captured"


def _prep_unfamiliar(root: Path) -> dict[str, str]:
    page = root / "unknown-portal.html"
    page.write_text(
        "<!doctype html><html><head><title>Obscure Portal</title></head>"
        "<body><nav><a id='reports' href='#reports'>Reports</a></nav>"
        "<section id='reports'><h2>Q3 Reports</h2><p>Revenue 12.4</p></section></body></html>",
        encoding="utf-8",
    )
    return {"page": str(page), "result": str(root / "research-notes.txt")}


def _check_unfamiliar(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    result = Path(ctx["result"])
    if not result.exists():
        return False, "research-notes.txt missing"
    if "12.4" not in result.read_text(encoding="utf-8"):
        return False, "did not extract the report figure"
    return True, "unfamiliar page figure extracted"


def _prep_recovery(root: Path) -> dict[str, str]:
    locked = root / "secret.txt"
    locked.write_text("ALPHA-TOKEN\n", encoding="utf-8")
    try:
        locked.chmod(0o000)
    except Exception:
        pass
    return {"locked": str(locked), "copy": str(root / "secret-copy.txt"), "report": str(root / "recovered.txt")}


def _check_recovery(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    report = Path(ctx["report"])
    copy = Path(ctx["copy"])
    locked = Path(ctx["locked"])
    try:
        locked.chmod(0o644)
    except Exception:
        pass
    haystack = ""
    if report.exists():
        haystack += report.read_text(encoding="utf-8")
    if copy.exists():
        haystack += copy.read_text(encoding="utf-8")
    if "ALPHA-TOKEN" not in haystack:
        return False, "secret not recovered after permission failure"
    return True, "recovered after permission failure"


def _prep_screenshot(root: Path) -> dict[str, str]:
    image = root / "screen.png"
    _tiny_png(image)
    return {"image": str(image), "notes": str(root / "screenshot-notes.txt")}


def _check_screenshot(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    notes = Path(ctx["notes"])
    if not notes.exists() or notes.stat().st_size < 8:
        return False, "screenshot-notes.txt missing or empty"
    return True, "screenshot notes written"


def _prep_research(root: Path) -> dict[str, str]:
    a = root / "source-a.html"
    b = root / "source-b.html"
    a.write_text("<html><body><p>Widget A battery life: 18 hours</p></body></html>", encoding="utf-8")
    b.write_text("<html><body><p>Widget B battery life: 11 hours</p></body></html>", encoding="utf-8")
    return {"a": str(a), "b": str(b), "report": str(root / "compare.md")}


def _check_research(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    report = Path(ctx["report"])
    if not report.exists():
        return False, "compare.md missing"
    text = report.read_text(encoding="utf-8").lower()
    if "18" not in text or "11" not in text:
        return False, "comparison missing both battery figures"
    return True, "multi-source comparison written"


def _prep_document(root: Path) -> dict[str, str]:
    src = root / "chapter-draft.md"
    src.write_text("# Chapter 1\n\nthis   chapter has   messy   spacing.\n\nSecond paragraph.\n", encoding="utf-8")
    return {"source": str(src), "clean": str(root / "chapter-1.md")}


def _check_document(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    clean = Path(ctx["clean"])
    if not clean.exists():
        return False, "cleaned document missing"
    text = clean.read_text(encoding="utf-8")
    if "  " in text.replace("# ", ""):
        return False, "messy spacing remains"
    return True, "document cleaned"


def _prep_multi_tool(root: Path) -> dict[str, str]:
    data = root / "numbers.json"
    data.write_text(json.dumps({"values": [3, 1, 4, 1, 5, 9]}), encoding="utf-8")
    return {"data": str(data), "script": str(root / "sum.py"), "out": str(root / "sum.txt")}


def _check_multi_tool(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    out = Path(ctx["out"])
    if not out.exists():
        return False, "sum.txt missing"
    if "23" not in out.read_text(encoding="utf-8"):
        return False, "expected sum 23"
    return True, "json read and summed via python"


def _prep_verify_code(root: Path) -> dict[str, str]:
    project = root / "adder"
    project.mkdir()
    (project / "adder.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (project / "test_adder.py").write_text(
        "from adder import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    return {"project": str(project)}


def _check_verify_code(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    project = Path(ctx["project"])
    result = _run(["python3", "-m", "pytest", "test_adder.py", "-q"], project)
    if result.returncode != 0:
        return False, result.stdout + result.stderr
    return True, "tests pass after the fix"


def _prep_json(root: Path) -> dict[str, str]:
    cfg = root / "settings.json"
    cfg.write_text(json.dumps({"theme": "light", "version": "1.0.0"}, indent=2), encoding="utf-8")
    return {"config": str(cfg)}


def _check_json(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    data = json.loads(Path(ctx["config"]).read_text(encoding="utf-8"))
    if data.get("theme") != "dark":
        return False, f"theme is {data.get('theme')}, expected dark"
    return True, "json value updated"


def _prep_csv(root: Path) -> dict[str, str]:
    src = root / "sales.csv"
    src.write_text("item,qty,price\nwidget,2,3.5\ngadget,1,10\n", encoding="utf-8")
    return {"csv": str(src), "out": str(root / "totals.csv")}


def _check_csv(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    out = Path(ctx["out"])
    if not out.exists():
        return False, "totals.csv missing"
    text = out.read_text(encoding="utf-8")
    if "17" not in text and "7.0" not in text and "7" not in text:
        return False, f"expected line totals in {text!r}"
    return True, "csv totals written"


def _prep_compare(root: Path) -> dict[str, str]:
    left = root / "v1.txt"
    right = root / "v2.txt"
    left.write_text("alpha\nbeta\n", encoding="utf-8")
    right.write_text("alpha\ngamma\n", encoding="utf-8")
    return {"left": str(left), "right": str(right), "diff": str(root / "diff.txt")}


def _check_compare(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    diff = Path(ctx["diff"])
    if not diff.exists():
        return False, "diff.txt missing"
    text = diff.read_text(encoding="utf-8")
    if "beta" not in text or "gamma" not in text:
        return False, "diff does not mention both versions"
    return True, "file versions compared"


def _prep_python_run(root: Path) -> dict[str, str]:
    return {"script": str(root / "hello.py"), "out": str(root / "hello.txt")}


def _check_python_run(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    out = Path(ctx["out"])
    script = Path(ctx["script"])
    if not script.exists():
        return False, "hello.py missing"
    if not out.exists() or "hello" not in out.read_text(encoding="utf-8").lower():
        return False, "hello.txt missing expected greeting"
    return True, "script created and ran"


def _prep_git_status(root: Path) -> dict[str, str]:
    ctx = _prep_git(root)
    Path(ctx["repo"], "scratch.txt").write_text("dirty\n", encoding="utf-8")
    return {**ctx, "status": str(root / "git-status.txt")}


def _check_git_status(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    status = Path(ctx["status"])
    if not status.exists():
        return False, "git-status.txt missing"
    text = status.read_text(encoding="utf-8")
    if "scratch.txt" not in text:
        return False, "did not report the dirty file"
    return True, "git status captured"


def _prep_hash(root: Path) -> dict[str, str]:
    blob = root / "payload.bin"
    blob.write_bytes(b"jarvis-hash-payload")
    return {"file": str(blob), "report": str(root / "stat.txt")}


def _check_hash(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    report = Path(ctx["report"])
    if not report.exists():
        return False, "stat.txt missing"
    text = report.read_text(encoding="utf-8").lower()
    if "sha256" not in text and "hash" not in text:
        return False, "no hash recorded"
    return True, "hash/stat recorded"


def _prep_terminal(root: Path) -> dict[str, str]:
    return {"out": str(root / "uname.txt")}


def _check_terminal(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    out = Path(ctx["out"])
    if not out.exists() or out.stat().st_size < 2:
        return False, "uname.txt missing"
    return True, "terminal output captured"


def _prep_recent(root: Path) -> dict[str, str]:
    target = root / "notes.txt"
    target.write_text("v1\n", encoding="utf-8")
    bak = root / "notes.txt.bak"
    bak.write_text("v0\n", encoding="utf-8")
    return {"file": str(target), "list": str(root / "recent.txt")}


def _check_recent(root: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    listing = Path(ctx["list"])
    if not listing.exists():
        return False, "recent.txt missing"
    if "bak" not in listing.read_text(encoding="utf-8"):
        return False, "backup not listed"
    return True, "recent backups listed"


@dataclass
class AgentBenchmarkCase:
    id: str
    title: str
    category: str
    prompt: str
    expected_tools: list[str]
    prepare: PrepareFn
    check: CheckFn
    live_requires: tuple[str, ...] = ()
    metric_focus: str = "successful autonomous tasks per unit of wall-clock time"

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "prompt": self.prompt,
            "expected_tools": list(self.expected_tools),
            "live_requires": list(self.live_requires),
            "metric_focus": self.metric_focus,
            "metrics": list(METRIC_FIELDS),
        }


CASES: list[AgentBenchmarkCase] = [
    AgentBenchmarkCase(
        "fs-organize",
        "Filesystem organization",
        "filesystem_organization",
        "Organize the files in {workspace} into category folders under {organized} (docs, images, audio, other). Do not delete originals until they are copied.",
        ["filesystem"],
        _prep_filesystem,
        _check_filesystem,
    ),
    AgentBenchmarkCase(
        "py-broken",
        "Broken Python project diagnosis",
        "broken_python_diagnosis",
        "The project at {project} should write the first 100 primes to output.txt when you run python main.py. Diagnose the failure, fix it, and verify output.txt.",
        ["filesystem", "python", "terminal"],
        _prep_broken_python,
        _check_broken_python,
    ),
    AgentBenchmarkCase(
        "git-modify",
        "Git repository modification",
        "git_repository_modification",
        "In {repo}, change greet() in app.py so it returns 'hello world'. Check git status first.",
        ["git", "filesystem"],
        _prep_git,
        _check_git,
    ),
    AgentBenchmarkCase(
        "ps-troubleshoot",
        "PowerShell / shell troubleshooting",
        "powershell_troubleshooting",
        "broken.sh and broken.ps1 at the workspace both exit 1. Diagnose why, write a fixed.sh that prints hello and exits 0, and run it.",
        ["terminal", "filesystem"],
        _prep_shell,
        _check_shell,
    ),
    AgentBenchmarkCase(
        "browser-nav",
        "Browser navigation",
        "browser_navigation",
        "Open the local page {page} in the browser, read the document title, and write it to {result}.",
        ["browser", "filesystem"],
        _prep_browser,
        _check_browser,
        live_requires=("browser",),
    ),
    AgentBenchmarkCase(
        "unfamiliar-site",
        "Unfamiliar website interaction",
        "unfamiliar_website",
        "The local page {page} is an unfamiliar portal. Find the Q3 revenue figure and write it to {result}.",
        ["browser", "filesystem"],
        _prep_unfamiliar,
        _check_unfamiliar,
        live_requires=("browser",),
    ),
    AgentBenchmarkCase(
        "tool-recovery",
        "Deliberate tool failure and recovery",
        "tool_failure_recovery",
        "Read {locked}. If permission is denied, recover the contents another way and write ALPHA-TOKEN to {report}.",
        ["filesystem"],
        _prep_recovery,
        _check_recovery,
    ),
    AgentBenchmarkCase(
        "screenshot",
        "Screenshot interpretation",
        "screenshot_interpretation",
        "Inspect the screenshot at {image} and write a one-sentence description to {notes}.",
        ["screenshot", "filesystem"],
        _prep_screenshot,
        _check_screenshot,
        live_requires=("vision",),
    ),
    AgentBenchmarkCase(
        "research",
        "Multi-step research",
        "multi_step_research",
        "Read {a} and {b}. Write compare.md at {report} that states both battery-life figures and which widget lasts longer.",
        ["filesystem", "web_fetch"],
        _prep_research,
        _check_research,
    ),
    AgentBenchmarkCase(
        "document",
        "Document processing",
        "document_processing",
        "Clean the markdown at {source}: collapse repeated spaces and save as {clean}.",
        ["filesystem"],
        _prep_document,
        _check_document,
    ),
    AgentBenchmarkCase(
        "multi-tool",
        "Multi-tool autonomous task",
        "multi_tool_autonomous",
        "Read {data}, write a Python script {script} that sums values, run it, and save the total to {out}.",
        ["filesystem", "python"],
        _prep_multi_tool,
        _check_multi_tool,
    ),
    AgentBenchmarkCase(
        "verify-code",
        "Verification after code modification",
        "verification_after_code_change",
        "The tests in {project} fail. Fix adder.py so add(2, 3) == 5 and run the tests. Do not mark success until tests pass.",
        ["filesystem", "python", "terminal"],
        _prep_verify_code,
        _check_verify_code,
    ),
    AgentBenchmarkCase(
        "json-update",
        "JSON configuration update",
        "json_config_update",
        "Set theme to dark in {config} without breaking other keys.",
        ["filesystem"],
        _prep_json,
        _check_json,
    ),
    AgentBenchmarkCase(
        "csv-transform",
        "CSV transform",
        "csv_transform",
        "From {csv}, write {out} with a line_total column (qty * price).",
        ["filesystem", "python"],
        _prep_csv,
        _check_csv,
    ),
    AgentBenchmarkCase(
        "compare-files",
        "Compare file versions",
        "compare_file_versions",
        "Compare {left} and {right} and write a unified-style summary to {diff}.",
        ["filesystem"],
        _prep_compare,
        _check_compare,
    ),
    AgentBenchmarkCase(
        "python-run",
        "Create and run a Python script",
        "python_script_run",
        "Create {script} that writes hello to {out}, then run it.",
        ["filesystem", "python"],
        _prep_python_run,
        _check_python_run,
    ),
    AgentBenchmarkCase(
        "git-status",
        "Git status before edits",
        "git_status_checkpoint",
        "In {repo} there is an untracked file. Write git status output to {status} before making any other change.",
        ["git", "filesystem"],
        _prep_git_status,
        _check_git_status,
    ),
    AgentBenchmarkCase(
        "hash-stat",
        "Hash and stat a file",
        "hash_and_stat",
        "Record the sha256 hash and size of {file} into {report}.",
        ["filesystem"],
        _prep_hash,
        _check_hash,
    ),
    AgentBenchmarkCase(
        "terminal-cmd",
        "Terminal command capture",
        "terminal_command",
        "Run a harmless command that prints the OS name and save stdout to {out}.",
        ["terminal", "filesystem"],
        _prep_terminal,
        _check_terminal,
    ),
    AgentBenchmarkCase(
        "recent-bak",
        "List recent backups",
        "recent_backups",
        "List backup copies near {file} into {list}. A .bak file already exists.",
        ["filesystem"],
        _prep_recent,
        _check_recent,
    ),
]


def get_case(case_id: str) -> AgentBenchmarkCase:
    for case in CASES:
        if case.id == case_id:
            return case
    raise KeyError(case_id)


def list_suite() -> dict[str, Any]:
    return {
        "suite_id": SUITE_ID,
        "version": SUITE_VERSION,
        "primary_metric": "successful autonomous tasks per unit of wall-clock time",
        "secondary_metrics": [
            "first-pass completion rate",
            "human interventions",
            "tool-call accuracy",
            "total task duration",
            "tokens/sec",
        ],
        "count": len(CASES),
        "cases": [case.as_public_dict() for case in CASES],
        "live_comparison_blocked": True,
        "live_comparison_reason": (
            "9B Q8 vs 9B Q6 vs 27B Q4 comparison requires the Windows desktop GPU and GGUF files."
        ),
    }


def prepare_case(case: AgentBenchmarkCase, workspace: Path) -> dict[str, str]:
    workspace.mkdir(parents=True, exist_ok=True)
    ctx = case.prepare(workspace)
    ctx.setdefault("root", str(workspace))
    return ctx


def format_prompt(case: AgentBenchmarkCase, ctx: dict[str, str]) -> str:
    try:
        return case.prompt.format(**ctx)
    except KeyError:
        return case.prompt


def check_case(case: AgentBenchmarkCase, workspace: Path, ctx: dict[str, str]) -> tuple[bool, str]:
    return case.check(workspace, ctx)


def empty_metrics() -> dict[str, Any]:
    return {
        "success": False,
        "human_intervention": False,
        "total_time_seconds": 0.0,
        "model_time_seconds": None,
        "tool_time_seconds": 0.0,
        "model_calls": 0,
        "tool_calls": 0,
        "retries": 0,
        "schema_errors": 0,
        "incorrect_actions": 0,
        "verification_result": "",
    }


def metrics_from_task(task: Task, tool_calls: list[ToolCallRecord] | None = None) -> dict[str, Any]:
    calls = list(tool_calls or [])
    schema_errors = sum(1 for call in calls if (call.error or "").lower().find("schema") >= 0)
    incorrect = sum(1 for call in calls if not call.success)
    tool_time = round(sum((call.duration_ms or 0) / 1000.0 for call in calls), 3)
    return {
        "success": task.status == "completed",
        "human_intervention": bool(task.waiting_for_confirmation),
        "total_time_seconds": float(task.duration_seconds or 0),
        "model_time_seconds": None,
        "tool_time_seconds": tool_time,
        "model_calls": 0,
        "tool_calls": len(calls),
        "retries": int(task.retries or 0),
        "schema_errors": schema_errors,
        "incorrect_actions": incorrect,
        "verification_result": (task.verification or "")[:2000],
    }


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    successes = sum(1 for row in rows if row.get("success"))
    duration = sum(float(row.get("total_time_seconds") or 0) for row in rows)
    tasks_per_minute = round((successes / duration) * 60, 4) if duration else None
    return {
        "suite_id": SUITE_ID,
        "cases_run": total,
        "successes": successes,
        "failures": total - successes,
        "first_pass_completion_rate": round(successes / total, 4) if total else None,
        "human_interventions": sum(1 for row in rows if row.get("human_intervention")),
        "total_duration_seconds": round(duration, 3),
        "successful_tasks_per_minute": tasks_per_minute,
        "tool_call_accuracy": (
            round(
                1
                - (
                    sum(int(row.get("incorrect_actions") or 0) for row in rows)
                    / max(1, sum(int(row.get("tool_calls") or 0) for row in rows))
                ),
                4,
            )
            if any(int(row.get("tool_calls") or 0) for row in rows)
            else None
        ),
    }


async def record_case_result(
    *,
    case: AgentBenchmarkCase,
    metrics: dict[str, Any],
    profile: str = "",
    quantization: str = "",
    source: str = "scripted",
    workspace: str = "",
    notes: str = "",
) -> AgentBenchmarkResult:
    row = AgentBenchmarkResult(
        suite_id=SUITE_ID,
        case_id=case.id,
        category=case.category,
        profile=profile,
        quantization=quantization,
        success=bool(metrics.get("success")),
        human_intervention=bool(metrics.get("human_intervention")),
        total_time_seconds=float(metrics.get("total_time_seconds") or 0),
        model_time_seconds=metrics.get("model_time_seconds"),
        tool_time_seconds=float(metrics.get("tool_time_seconds") or 0),
        model_calls=int(metrics.get("model_calls") or 0),
        tool_calls=int(metrics.get("tool_calls") or 0),
        retries=int(metrics.get("retries") or 0),
        schema_errors=int(metrics.get("schema_errors") or 0),
        incorrect_actions=int(metrics.get("incorrect_actions") or 0),
        verification_result=str(metrics.get("verification_result") or "")[:4000],
        source=source,
        workspace=workspace,
        notes=notes[:4000],
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def list_results(limit: int = 100) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AgentBenchmarkResult).order_by(AgentBenchmarkResult.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": row.id,
            "suite_id": row.suite_id,
            "case_id": row.case_id,
            "category": row.category,
            "profile": row.profile,
            "quantization": row.quantization,
            "success": row.success,
            "human_intervention": row.human_intervention,
            "total_time_seconds": row.total_time_seconds,
            "model_time_seconds": row.model_time_seconds,
            "tool_time_seconds": row.tool_time_seconds,
            "model_calls": row.model_calls,
            "tool_calls": row.tool_calls,
            "retries": row.retries,
            "schema_errors": row.schema_errors,
            "incorrect_actions": row.incorrect_actions,
            "verification_result": row.verification_result,
            "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def apply_expected_solution(case: AgentBenchmarkCase, ctx: dict[str, str]) -> None:
    """Mutate a prepared workspace into the accepted end state (tests / dry-run)."""
    cid = case.id
    if cid == "fs-organize":
        organized = Path(ctx["organized"])
        for name in ("docs", "images", "audio", "other"):
            (organized / name).mkdir(parents=True, exist_ok=True)
        (organized / "docs" / "notes.txt").write_text("todo", encoding="utf-8")
    elif cid == "py-broken":
        primes: list[int] = []
        n = 2
        while len(primes) < 100:
            if n > 1 and all(n % i for i in range(2, int(n**0.5) + 1)):
                primes.append(n)
            n += 1
        Path(ctx["project"], "utils.py").write_text(
            "def is_prime(n):\n"
            "    return n > 1 and all(n % i for i in range(2, int(n ** 0.5) + 1))\n\n"
            "def first_primes(count):\n"
            "    found, candidate = [], 2\n"
            "    while len(found) < count:\n"
            "        if is_prime(candidate):\n"
            "            found.append(candidate)\n"
            "        candidate += 1\n"
            "    return found\n",
            encoding="utf-8",
        )
        Path(ctx["output"]).write_text("\n".join(str(p) for p in primes) + "\n", encoding="utf-8")
    elif cid == "git-modify":
        Path(ctx["repo"], "app.py").write_text("def greet():\n    return 'hello world'\n", encoding="utf-8")
    elif cid == "ps-troubleshoot":
        Path(ctx["fixed"]).write_text("#!/bin/sh\necho hello\nexit 0\n", encoding="utf-8")
    elif cid == "browser-nav":
        Path(ctx["result"]).write_text("Example Domain\n", encoding="utf-8")
    elif cid == "unfamiliar-site":
        Path(ctx["result"]).write_text("Revenue 12.4\n", encoding="utf-8")
    elif cid == "tool-recovery":
        Path(ctx["report"]).write_text("ALPHA-TOKEN\n", encoding="utf-8")
    elif cid == "screenshot":
        Path(ctx["notes"]).write_text("A 1x1 screenshot.\n", encoding="utf-8")
    elif cid == "research":
        Path(ctx["report"]).write_text("Widget A 18 hours vs Widget B 11 hours.\n", encoding="utf-8")
    elif cid == "document":
        Path(ctx["clean"]).write_text(
            "# Chapter 1\n\nthis chapter has messy spacing.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
    elif cid == "multi-tool":
        Path(ctx["script"]).write_text("print(23)\n", encoding="utf-8")
        Path(ctx["out"]).write_text("23\n", encoding="utf-8")
    elif cid == "verify-code":
        Path(ctx["project"], "adder.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    elif cid == "json-update":
        Path(ctx["config"]).write_text('{"theme": "dark", "version": "1.0.0"}', encoding="utf-8")
    elif cid == "csv-transform":
        Path(ctx["out"]).write_text(
            "item,qty,price,line_total\nwidget,2,3.5,7.0\ngadget,1,10,10\n",
            encoding="utf-8",
        )
    elif cid == "compare-files":
        Path(ctx["diff"]).write_text("- beta\n+ gamma\n", encoding="utf-8")
    elif cid == "python-run":
        Path(ctx["script"]).write_text("print('hello')\n", encoding="utf-8")
        Path(ctx["out"]).write_text("hello\n", encoding="utf-8")
    elif cid == "git-status":
        Path(ctx["status"]).write_text("?? scratch.txt\n", encoding="utf-8")
    elif cid == "hash-stat":
        Path(ctx["report"]).write_text("sha256=abc size=19\n", encoding="utf-8")
    elif cid == "terminal-cmd":
        Path(ctx["out"]).write_text("Linux\n", encoding="utf-8")
    elif cid == "recent-bak":
        Path(ctx["list"]).write_text("notes.txt.bak\n", encoding="utf-8")


def run_fixture_suite(base: Path, case_ids: list[str] | None = None) -> dict[str, Any]:
    """Prepare and score each case against an empty (failing) then a prepared workspace.

    This validates fixtures and checks without a live model. Callers that want a
    passing score must apply the expected workspace mutations themselves.
    """
    selected = [get_case(cid) for cid in case_ids] if case_ids else list(CASES)
    rows: list[dict[str, Any]] = []
    started = time.time()
    for case in selected:
        workspace = base / case.id
        ctx = prepare_case(case, workspace)
        ok, note = check_case(case, workspace, ctx)
        metrics = empty_metrics()
        metrics["success"] = ok
        metrics["verification_result"] = note
        metrics["total_time_seconds"] = round(time.time() - started, 4)
        rows.append(
            {
                "case_id": case.id,
                "category": case.category,
                "prompt": format_prompt(case, ctx),
                "workspace": str(workspace),
                "prepared": True,
                "unsolved_success": ok,
                **metrics,
            }
        )
    report = summarize_results(
        [{**row, "success": False} for row in rows]
    )
    report["note"] = (
        "Fixture run only prepares workspaces. Unsolved cases are expected to fail checks; "
        "live/scripted agent runs populate success metrics."
    )
    report["cases"] = rows
    return report
