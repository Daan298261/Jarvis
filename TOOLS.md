# Tools

All tools are registered in `backend/app/tools/registry.py` and can be enabled or disabled from the Tools page.

| Tool | What it does |
| --- | --- |
| `filesystem` | list, search, read, write, edit, copy, move, rename, mkdir, delete, hash, stat. Backs up files before overwrite when enabled. Restricted to allowed directories. |
| `terminal` | PowerShell, cmd, git, python, WSL/bash when present. `run` waits; `start` returns a PID; `inspect` / `wait` / `kill` check whether that process is still alive and collect output. `inspect` also works for other local PIDs. Captures stdout, stderr, exit code, duration. Blocks irreversible commands. Python snippets use `python -c`. |
| `python` | run_code, run_file, create_venv, pip install. Prefer project virtualenvs. |
| `browser` | Playwright Chromium: open, accessibility snapshot, click by name/selector, type, evaluate, screenshot, tabs, download, upload. Persistent profile in `data/browser-profile`. |
| `desktop` | pywinauto UI Automation first; coordinate click only as fallback. Screenshot via `mss`. |
| `office` | Word/Excel/PowerPoint COM when Office is installed. Writes new files unless in-place edit was requested. |
| `git` | status, diff, branch, log, search, stash checkpoint before large edits. |
| `docker` | ps/images/build/run/logs/inspect when Docker exists. |
| `web_fetch` | HTTP GET/POST distinct from the browser. |
| `screenshot` | Desktop capture for Qwen3.5 vision. Images are attached to the next model turn. |
| `mcp_call` | Invokes tools from user-configured MCP servers (stdio or HTTP). |

## Memory and skills

Finished tasks write a trajectory: the ordered tools, which step failed and why, which tool worked instead, and the verification result. A later similar task gets those lessons in its system prompt.

When the same task class succeeds three or more times with the same tool sequence, the workflow is promoted to a skill. If the tool arguments were recorded, values that differed across those runs become parameters (`{path}`, `{content}`, …) and the skill can **run itself**: matching later tasks execute the bound steps, then verify. Inspect, promote, enable, disable, or run from the **Memory** page, or via `/api/memory/trajectories`, `/api/memory/skills`, and `POST /api/memory/skills/{id}/run`.

Hidden reasoning is never stored — only tool choices, outcomes, and error summaries.

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
