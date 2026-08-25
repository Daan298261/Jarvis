# Tools

All tools are registered in `backend/app/tools/registry.py` and can be enabled or disabled from the Tools page.

| Tool | What it does |
| --- | --- |
| `filesystem` | list, search, read, write, edit, copy, move, rename, mkdir, delete, hash, stat, compare, recent. `compare` diffs two files (unified diff for text, hashes for binaries). `recent` lists backup copies next to a file (`.bak`, `.bak-<timestamp>`). Backs up files before overwrite when enabled. Restricted to allowed directories. |
| `terminal` | PowerShell, cmd, git, python, WSL/bash when present. Default is PowerShell on Windows and bash on Linux. `run` waits; `start` returns a PID; `inspect` / `wait` / `kill` check whether that process is still alive and collect output. `inspect` also works for other local PIDs. Captures stdout, stderr, exit code, duration. Blocks irreversible commands. Python snippets use the current interpreter with `-c`. |
| `python` | run_code, run_file, create_venv, pip install. Prefer project virtualenvs. Uses `sys.executable` when no venv is given. |
| `browser` | Playwright Chromium: open, accessibility snapshot, click by name/selector, type, evaluate, screenshot, tabs, download, upload, close. `close` does not launch Chromium. Persistent profile in `data/browser-profile`. |
| `desktop` | pywinauto UI Automation first; coordinate click only as fallback. Screenshot via `mss`. |
| `office` | Word/Excel/PowerPoint COM when Office is installed. Writes new files unless in-place edit was requested. |
| `git` | status, diff, branch, log, search, checkpoint, list_checkpoints, restore. `checkpoint` creates a `jarvis-checkpoint-*` backup branch without resetting the working tree. |
| `docker` | ps/images/build/run/logs/inspect when Docker exists. `run`/`logs`/`inspect` require an image or container. |
| `web_fetch` | HTTP GET/POST/HEAD distinct from the browser. POST may send `body` or `json_body` plus optional headers. |
| `screenshot` | Desktop capture for Qwen3.5 vision. Images are attached to the next model turn. |
| `request_tools` | Escape hatch: ask the runtime to expose extra tools for the rest of the task. |
| `mcp_call` | Invokes tools from user-configured MCP servers (stdio or HTTP). |
| `request_tools` | Escape hatch: add more tools for the current task (names or categories: browser, coding, windows, office, mcp, all). |
| `ufo` | Optional Microsoft UFO HostAgent/AppAgent worker. Missing package degrades to the native `desktop` tool. |
| `cua` | Optional Cua computer-use worker. Missing package degrades to the native `desktop` tool. |

The agent does **not** send every tool schema on every model turn. Task classification (filesystem, software engineering, browser, Windows GUI, …) selects a small relevant set plus `filesystem` and `request_tools`. Mixed and long-horizon tasks still receive the full set.

## Memory and skills

Finished tasks write a trajectory: the ordered tools, which step failed and why, which tool worked instead, and the verification result. A later similar task gets those lessons in its system prompt.

When the same task class succeeds three or more times with the same tool sequence, the workflow is promoted to a skill. If the tool arguments were recorded, values that differed across those runs become parameters (`{path}`, `{url}`, `{content}`, …) and the skill can **run itself**: matching later tasks execute the bound steps, then verify. Browser procedures that click named controls, roles/ARIA, or CSS selectors (not snapshot ids like `e12`) promote as BrowserCode-style skills; snapshot/screenshot discovery steps are stripped so the skill can replay. Password-like fields become parameters with no stored examples and do not auto-run. Inspect, promote, enable, disable, or run from the **Memory** page (secret parameters use password inputs), or via `/api/memory/trajectories`, `/api/memory/skills`, and `POST /api/memory/skills/{id}/run`.

Hidden reasoning is never stored — only tool choices, outcomes, and error summaries.

## Swarm placement (future P2+)

The current tool registry is process-local. `SWARM_ARCHITECTURE.md` requires future placement to keep **tool/worker selection** separate from **Node placement**. A software Worker or tool capability may advertise requirements (OS, GPU/VRAM, desktop session, local files, etc.); the Orchestrator then selects an eligible Node subject to role policy, resource budgets/leases, data locality, and current load.

P2 must preserve current one-machine behavior: the only eligible Node may be `localhost`. P3 adds remote execution. Do not rename existing software workers to `SeniorWorker` / `JuniorWorker`; those labels are node execution classes in the swarm spec.

## MCP

Configure servers in the MCP page or `data/settings.json` → `mcp_servers`. Example:

```json
{
  "id": "fs-1",
  "name": "filesystem",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\\\Users\\\\daanv\\\\Desktop"],
  "enabled": true
}
```

HTTP/streamable-http servers use `"transport": "http"` and `"url": "http://127.0.0.1:3000"`.
