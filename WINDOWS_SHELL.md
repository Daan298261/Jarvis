# Windows shell — tray, Stop, Uninstall

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md` §58. Architect-owned. **Not implemented.**

This is the Windows **running-app** shell for the consumer install (`INSTALLER.md`). It is **not** P3 swarm, **not** a WAN feature, and **not** an Inno tutorial.

**Do not** edit `installer/windows/` product files from Architect PRs. D1 owns the in-tree installer; CoS will assign this ticket later (D1 is on voice P0). Wizard copy, GPU fork, and no-WAN first-run stay as specified in `INSTALLER.md` and are **not** this ticket.

Today **Stop** lives on the Start Menu. Non-technical users must be able to stop Jarvis from **Windows** without hunting a Start Menu shortcut.

---

## 1. System tray (required while Jarvis is running)

While backend and/or `llama-server` are running, a **system tray** icon is required.

Menu (plain language):

- **Open portal** — open `http://127.0.0.1:4780` (or the installed local URL). Does **not** expose WAN.
- **Start** — same as Start Jarvis (portal up, model load attempted).
- **Stop** — stop backend **and** `llama-server`. Must **not** leave `llama-server` orphaned.
- **Quit** — Stop **plus** exit the tray helper. Same process rule: no orphaned `llama-server`.

---

## 2. Stop from Windows, not only Start Menu

All of these must leave **no** Jarvis backend / `llama-server` / tray helper running:

- Tray **Stop**
- Tray **Quit**
- **Settings → Apps → Jarvis**: **Uninstall** and **Modify** must stop those processes first (or as part of the operation). Do not leave orphans after the user removes or changes the app.

If there is a **Startup** (run at Windows login) toggle: it must match master plan §48 — obvious, easy to disable, never silent.

---

## 3. Out of scope

- Extra Inno knowledge in the user UI
- WAN / port-forward / Link-device
- P3 swarm join
- Voice crash fix (D1; do not touch voice backend files from this ticket)
- First-run wizard / GPU fork / no-WAN installer gaps (`INSTALLER.md`)

---

## 4. Acceptance

- [ ] Tray present while running: Open portal, Start, Stop, Quit
- [ ] Stop and Quit kill backend + `llama-server` (no orphan) + Quit exits the tray helper
- [ ] Uninstall / Modify from Settings → Apps → Jarvis do not leave those processes running
- [ ] Startup toggle (if any) is obvious and easy to disable
- [ ] Non-technical copy; no WAN; not P3
