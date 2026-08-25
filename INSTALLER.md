# Windows consumer installer

Status: **separate specification** referenced by `JARVIS_MASTER_PLAN.md` §58 P1. **Not implemented** until a user-facing `.exe` exists. Architect-owned.

This is the **non-technical onboarding** path: a new Windows 11 user downloads Jarvis and double-clicks one installer. It is **not** a second product, **not** P3 swarm, and **not** a replacement for the developer/manual path in [`docs/INSTALL.md`](docs/INSTALL.md).

Implementation **may** live under `installer/windows/` (Inno Setup + bootstrap is the in-flight claim). This spec states **outcomes**. It does **not** prescribe Inno script line-by-line. Architect and other bots **must not** overwrite D1’s in-flight files in that tree.

---

## 1. Who it is for

Someone who should not have to install Python, Node, or llama.cpp by hand, or read a terminal log.

Copy is plain language. Show **progress** (step name + percent or “still working”). Do not dump compiler/pip/npm logs as the primary UI. Advanced log is optional behind a disclosure.

---

## 2. One double-click

- One `.exe` on **Windows 11**.
- Double-click installs (or bundles) what [`docs/INSTALL.md`](docs/INSTALL.md) already requires to run Jarvis on this PC: **Python**, **Node**, **llama.cpp CUDA build**, **start/stop scripts**, **portal**.
- After install, a **Start Menu** item and **desktop shortcut** launch a **working local Jarvis** with the **9B Abliterated** default on this machine (portal up, model load attempted).

Do not require a manual clone + `pip` + `npm` + GGUF dance for this path.

---

## 3. First-run wizard

After files are in place, a wizard (GUI, not a raw console):

1. **Models** — download GGUFs. **Qwen3.5-9B Abliterated Q8** preferred; **Q6** fallback if Q8 is too large or the download fails. **27B Expert** is optional / later, not required to finish first run.
2. **Data directory** — user picks where Jarvis keeps data (and model files if not next to the app). Default is a normal per-user location; do not silently write to a developer checkout.
3. **Private key** — generate and store locally (same rules as `docs/INSTALL.md` / Settings). Show how to copy it when they need the phone later. Never put it in git, chat, or a screenshot-by-default log.
4. **Optional LAN** — off by default (localhost). If they enable LAN, require the existing private-key gate. Bind deliberately.
5. **WAN** — **do not** expose the Leader to the internet from this wizard. Off-LAN reachability is the **Link-device** flow in [`ANDROID_CLIENT.md`](ANDROID_CLIENT.md) (explain WAN, DIY vs Jarvis + router password). The installer must not add a WAN port-forward “for convenience.”

---

## 4. GPU / VRAM

Detect NVIDIA GPU and usable VRAM in plain language.

- If GPU/VRAM is **missing or too small** for a reasonable 9B GPU load: **say so**. Offer **CPU-degraded** (slow, still local) **or stop**. Do not pretend the 16 GB desktop profile succeeded.
- Do not enable WAN as a workaround for a weak GPU.

---

## 5. Out of scope

- P3 multi-node swarm (discovery, pairing, join). Swarm “universal installer” language in `SWARM_ARCHITECTURE.md` is a later, different flow.
- A second Jarvis app or cloud account.
- Shipping Red / offensive capability (see `SECURITY_AGENTS.md`).
- Rewriting `docs/INSTALL.md` into this wizard; that file stays the technical/manual install.

---

## 6. Acceptance (tick when the .exe exists)

- [ ] One Windows 11 `.exe`; double-click; no manual Python/Node/llama.cpp dance
- [ ] Installs or bundles Python, Node, llama.cpp CUDA, start/stop, portal
- [ ] First-run: 9B Q8 preferred / Q6 fallback; 27B optional; data dir; private key; optional LAN; no WAN without Link-device
- [ ] Non-technical progress UI; GPU/VRAM missing → explain and offer CPU-degraded or stop
- [ ] Start Menu / desktop shortcut launches working local 9B Jarvis
- [ ] Not treated as P3 swarm; `installer/windows/` not overwritten by unrelated Architect edits
