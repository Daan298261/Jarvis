# Jarvis capability overview

Jarvis is a **self-hosted local desktop agent** for Windows. A FastAPI backend plus React portal (`http://127.0.0.1:4780` by default) drives planning, tool use, and verification. Inference defaults to **Qwen3.5-9B** via llama.cpp on the local GPU; **27B Expert** is optional for escalation.

## What Jarvis can do

- **Agent loop** — plan → act → verify with native tools: filesystem, terminal, Python, browser (Playwright), desktop UI automation, git, web fetch, screenshot/vision, Office (when installed), Docker (when installed), MCP proxies, and more.
- **Profiles** — model Fast / Balanced / Quality and agent execution modes Fast / Balanced / Reliable are separate knobs.
- **Remote inference** — point `inference.host` / `port` at any OpenAI-compatible `/v1` server (LM Studio, Ollama, vLLM, remote llama.cpp) without rewriting agent code.
- **Queue & voice** — drop tasks in `data/queue/`; voice commands create tasks when Whisper is installed.
- **Phone PWA** — `/phone` on the LAN with private-key auth (see setup pitfalls).
- **Memory & skills** — trajectories, skills, context repos (user workspaces) complement but do not replace this product-self pack.

## What Jarvis cannot do (today)

- **Cloud-by-default** — weights and tool execution stay on your machine unless you explicitly configure remote inference.
- **WAN installer shortcut** — consumer installer must not expose the Leader to the internet; off-LAN access uses Link-device flows (`ANDROID_CLIENT.md`).
- **Windows shell tray** — specified in `WINDOWS_SHELL.md` but not fully implemented everywhere; Stop may still be via `stop-jarvis.ps1` or Start Menu.
- **Linux desktop product** — backend unit tests run on Linux; Office, pywinauto, and GPU model load are Windows desktop sign-off.
- **Offensive / red tooling** — hard guardrail; only named LE workflows may add counter-offensive capability (`SECURITY_AGENTS.md`).
- **Guessing product facts** — when this pack or allowlisted docs lack an answer, the agent should say so instead of inventing APIs, paths, or UI.

## Related pointers

- Manual install: `docs/INSTALL.md`
- Security & private keys: `SECURITY.md`
- Troubleshooting: `TROUBLESHOOTING.md`
- Architecture context: `JARVIS_MASTER_PLAN.md` (architect-owned; not duplicated here)
