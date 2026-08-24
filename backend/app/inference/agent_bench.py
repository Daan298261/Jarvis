from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AgentBenchTask:
    id: str
    name: str
    category: str
    prompt: str
    requires: tuple[str, ...] = ()
    success: str = ""


AGENT_TASKS: tuple[AgentBenchTask, ...] = (
    AgentBenchTask(
        "fs-organize",
        "Filesystem organization",
        "filesystem",
        "Create a folder named Jarvis-Bench and move three sample files into category subfolders.",
        success="folder layout exists and files moved",
    ),
    AgentBenchTask(
        "py-diagnose",
        "Broken Python project diagnosis",
        "software engineering",
        "tests/broken_project.py fails. Diagnose the bug, patch it, and run the module to prove it works.",
        success="module runs without exception",
    ),
    AgentBenchTask(
        "git-modify",
        "Git repository modification",
        "software engineering",
        "In an allowed directory, init or use a git repo, edit README.md, and show the diff without committing unless asked.",
        requires=("git",),
        success="working tree shows the intended README change",
    ),
    AgentBenchTask(
        "ps-troubleshoot",
        "PowerShell troubleshooting",
        "shell",
        "Run a PowerShell (or bash) one-liner that prints the current directory and confirm the output is a real path.",
        success="command output is an existing directory",
    ),
    AgentBenchTask(
        "browser-nav",
        "Browser navigation",
        "browser automation",
        "Open https://example.com, snapshot the page, and record the document title.",
        requires=("network", "playwright"),
        success="title contains Example",
    ),
    AgentBenchTask(
        "unfamiliar-site",
        "Unfamiliar website interaction",
        "browser automation",
        "Open https://example.com, follow the More information link if present, and save the visible heading text to a file.",
        requires=("network", "playwright"),
        success="saved file contains heading text from the page",
    ),
    AgentBenchTask(
        "tool-recovery",
        "Deliberate tool failure and recovery",
        "mixed",
        "Try to read a file that does not exist, then recover by creating it and reading it back.",
        success="file exists after recovery and was read",
    ),
    AgentBenchTask(
        "screenshot-interpret",
        "Screenshot interpretation",
        "multimodal",
        "Capture a screenshot of the desktop or a simple page and describe the main visible UI in one paragraph.",
        requires=("gpu",),
        success="description refers to visible on-screen content",
    ),
    AgentBenchTask(
        "multi-research",
        "Multi-step research",
        "research",
        "Fetch https://example.com and write a 5-line briefing of what the page is for into research-brief.md.",
        requires=("network",),
        success="research-brief.md exists and is non-empty",
    ),
    AgentBenchTask(
        "document-process",
        "Document processing",
        "document processing",
        "Write a short markdown document with a title, two headings, and a bullet list, then read it back.",
        success="file contains the expected headings",
    ),
    AgentBenchTask(
        "multi-tool",
        "Multi-tool autonomous task",
        "mixed",
        "Create a Python file that prints hello, run it, and save stdout next to the script.",
        success="script and stdout file both exist",
    ),
    AgentBenchTask(
        "verify-code",
        "Verification after code modification",
        "software engineering",
        "Change a tiny Python function, run it, and independently verify the new return value with a second command.",
        success="verification command output matches the new behavior",
    ),
    AgentBenchTask(
        "csv-parse",
        "CSV data processing",
        "data processing",
        "Write a 4-row CSV of name,score and compute the average score with Python.",
        success="reported average matches the file",
    ),
    AgentBenchTask(
        "markdown-report",
        "Document-style report",
        "document processing",
        "Write a one-page markdown status report covering goal, changes, verification, and leftovers.",
        success="report file exists with those four sections",
    ),
    AgentBenchTask(
        "docker-inspect",
        "Docker inspect when present",
        "shell",
        "If Docker is installed, list images. If it is not, report that clearly without inventing output.",
        success="either docker images listed or missing-capability reported",
    ),
    AgentBenchTask(
        "mcp-graceful",
        "Missing MCP server graceful handling",
        "mixed",
        "Attempt an MCP tool if none are configured and continue the task by writing a note that MCP was unavailable.",
        success="note file exists; process did not crash",
    ),
    AgentBenchTask(
        "rename-copy",
        "Rename and copy files",
        "filesystem",
        "Create sample.txt, copy it to sample-copy.txt, and rename the copy to sample-renamed.txt.",
        success="original and renamed copy exist",
    ),
    AgentBenchTask(
        "compare-files",
        "Compare two files",
        "filesystem",
        "Write two text files that differ by one line and produce a unified diff with the filesystem compare action.",
        success="diff mentions the changed line",
    ),
    AgentBenchTask(
        "python-snippet",
        "Python snippet execution",
        "software engineering",
        "Use the python tool to evaluate 2+2 and write the result to answer.txt.",
        success="answer.txt contains 4",
    ),
    AgentBenchTask(
        "long-horizon-mixed",
        "Long-horizon mixed task",
        "long-horizon autonomous",
        "Research example.com, save a briefing, and keep a local git-style changelog of what changed in that folder.",
        requires=("network",),
        success="briefing and changelog both exist",
    ),
)


def task_catalog() -> list[dict[str, object]]:
    return [asdict(task) for task in AGENT_TASKS]


def tasks_by_category() -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in AGENT_TASKS:
        counts[task.category] = counts.get(task.category, 0) + 1
    return counts
