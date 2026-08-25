# Tools

All tools are registered in `backend/app/tools/registry.py` and can be enabled or disabled from the Tools page.

| Tool | What it does |
| --- | --- |
| `filesystem` | list, search, read, write, edit, copy, move, rename, mkdir, delete, hash, stat, restore. Backs up files to `.bak-*` before overwrite/delete when enabled (last 3 kept); restore copies the newest sidecar back. Restricted to allowed directories. |
| `terminal` | PowerShell, cmd, git, python, WSL/bash when present. Captures stdout, stderr, exit code, duration. Risk is MEDIUM for ordinary commands; HIGH/irreversible patterns still escalate. Irreversible commands are blocked. |
| `python` | run_code, run_file, create_venv, pip install. Prefer project virtualenvs. |
| `browser` | Playwright Chromium: open, accessibility snapshot, click by name/selector, type, evaluate, screenshot, tabs, download, upload. Persistent profile in `data/browser-profile`. |
| `desktop` | pywinauto UI Automation first; coordinate click only as fallback. Screenshot via `mss`. |
| `office` | Word/Excel/PowerPoint COM when Office is installed. Writes new files unless in-place edit was requested. |
| `git` | status, diff, branch, log, search, checkpoints, checkpoint, restore. Checkpoint creates a `jarvis-checkpoint-*` branch (including uncommitted work) without changing the working tree. Restore reverts files from those checkpoint refs only. |
| `docker` | ps/images/build/run/logs/inspect when Docker exists. |
| `web_fetch` | HTTP GET/POST distinct from the browser. |
| `screenshot` | Desktop capture for Qwen3.5 vision. Images are attached to the next model turn. |
| `mcp_call` | Invokes tools from user-configured MCP servers (stdio or HTTP). |

## MCP

Optional. Nothing is enabled by default. Configure servers on the **MCP** page (documented presets or a custom stdio/HTTP server) or in `data/settings.json` → `mcp_servers`.

Documented presets (add from the portal; they are not auto-started):

| Preset | Command | Notes |
| --- | --- | --- |
| filesystem | `npx -y @modelcontextprotocol/server-filesystem {desktop} {documents}` | Desktop + Documents. No secrets. |
| memory | `npx -y @modelcontextprotocol/server-memory` | Local memory graph. No secrets. |
| git | `uvx mcp-server-git --repository {repo}` | This Jarvis repo. No secrets. |
| fetch | `uvx mcp-server-fetch` | HTTP fetch to markdown. No secrets. |
| time | `uvx mcp-server-time` | Time / timezone. No secrets. |
| github | `npx -y @modelcontextprotocol/server-github` | Needs `GITHUB_PERSONAL_ACCESS_TOKEN` in the **user environment**. |
| whatsapp | `npx --yes wappmcp@0.4.0 mcp --headless` | Pair once with `npx wappmcp@0.4.0 configure`; session stays in `~/.wappmcp`. |
| email | `npx --yes @codefuturist/email-mcp@0.2.3 stdio` | Configure once with `npx @codefuturist/email-mcp@0.2.3 account add`; use an app password. |

Placeholders `{desktop}`, `{documents}`, `{downloads}`, `{home}`, `{repo}`, `{data}` are expanded at runtime.

**Do not put tokens in git, `config/default.json`, or the MCP form.** Store `env_from: ["GITHUB_PERSONAL_ACCESS_TOKEN"]` or `"env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}" }`. Jarvis copies the value from the process environment when the server starts. Raw `ghp_…` values are rejected.

```json
{
  "name": "github",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env_from": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
  "enabled": true
}
```

HTTP/streamable-http servers use `"transport": "http"` and `"url": "http://127.0.0.1:3000"`.

API: `GET /api/mcp/presets`, `POST /api/mcp/presets/{id}`, `GET/POST /api/mcp`, `POST /api/mcp/refresh`.
