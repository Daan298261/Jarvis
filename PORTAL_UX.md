# Portal UX — app shell

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md` §58. Architect-owned. **Not implemented.** For the **Jarvis UX** implementer.

One frontend ticket. **Do not redesign the API.** **Do not overwrite swarm backend.** UX owns `frontend/src` (pages, CSS, layout). Swarm page may be restyled as part of the shell; keep `frontend/src/api.ts` swarm endpoints and payloads.

---

## 1. Keep

**Palette (Jarvis brand).** Current orange/black tokens in `frontend/src/index.css`: `--bg` `#0b0d10`, `--gold` `#d4a017`, `--panel` / `--panel-2`, `--text`. Do **not** invent a new color system.

**Existing destinations** (do not delete Swarm or Phone):

| Label today | Route |
| --- | --- |
| Command | `/`, `/tasks/:id` |
| Phone | `/phone` |
| History | `/history` |
| Guide & Workflows | `/workflows` |
| Memory | `/memory` |
| Model | `/model` |
| Tools | `/tools` |
| MCP | `/mcp` |
| Settings | `/settings` |
| System | `/system` |
| Swarm | `/swarm`, `/swarm/:nodeId` |

Keep it **local-desktop dense**, not a marketing site.

---

## 2. Change — ChatGPT-style app shell

**Home is talk/work**, not Model / Tools / System.

- **Left rail:** **Projects** (named groupings of existing conversations/tasks) + **Recents** (existing task/history list). Selecting a recent or a project task opens that chat in the main pane.
- **Main pane:** the current chat/task (today’s Command surface).
- **Tabs** become a **cleaner secondary nav** or a **settings cluster**, not a stack of equal-weight admin dashboards as the home screen.
  - Secondary / work: History, Guide & Workflows, Memory, Phone
  - Admin cluster (reachable, not first): Settings, Model, Tools, MCP, System, Swarm

Less chrome. A non-technical user should find **Settings** (and understand that **Stop** is on the Windows tray — `WINDOWS_SHELL.md`) without feeling they opened a server console.

**Projects** group existing tasks. Persist grouping as **portal-local state** on the Leader (preferences / local store). **No new public REST resource** unless an existing task field already covers it. Recents = current task list/history APIs.

---

## 3. Out of scope

- New color system
- Removing Swarm or Phone
- Changing swarm **backend** or `api.ts` swarm contracts
- WAN, installer wizard/GPU/no-WAN gaps, voice backend (D1 owns the listen crash fix)

---

## 4. Acceptance

- [ ] Orange/black preserved (`--gold` / `--bg`; no new palette)
- [ ] Left projects + main chat/task (recents in the rail; home is talk/work)
- [ ] Existing destinations still reachable (table in §1)
- [ ] Swarm / Phone not removed
- [ ] Non-technical user can find Stop/settings without feeling they opened a server console
