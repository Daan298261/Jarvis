"""Installer owner actions (RFC-0124 clean reinstall).

UX API contract (Settings → Advanced danger card — UX PR only; D1 does not touch frontend)
----------------------------------------------------------------------------------------

### 1) GET owned roots for confirm UI

**Paths (equivalent payload):**

- `GET /api/installer/clean-reinstall/owned-roots`  ← preferred name for UX
- `GET /api/installer/clean-reinstall/preview`      ← alias

**Response** (200): paths + human labels + short-lived confirm token for POST.

```json
{
  "action_available": true,
  "confirm_token": "<signed-token>",
  "confirm_token_expires_at": 1710000000,
  "owned_root_entries": [
    {
      "id": "install_root",
      "path": "C:\\Users\\owner\\AppData\\Local\\Jarvis",
      "label": "Jarvis install folder — application, models, chats, logs, and other Jarvis-owned data"
    }
  ],
  "owned_roots": ["C:\\Users\\owner\\AppData\\Local\\Jarvis"],
  "license_issuer_preserved": "C:\\...\\Jarvis\\license-issuer",
  "preserved_note": "Vendor license-issuer folder is not deleted.",
  "log_paths": {
    "durable": "%TEMP%\\Jarvis-clean-reinstall.log",
    "install": "C:\\...\\Jarvis\\logs\\clean-reinstall.log",
    "status": "%TEMP%\\Jarvis-clean-reinstall.status.json"
  },
  "ux": {
    "requires_two_step_confirm": true,
    "post_start_poll_path": "/api/installer/clean-reinstall/status",
    "never_show_success_on_http_400": true,
    "post_start_means_helper_spawned_not_wipe_complete": true
  }
}
```

UX flow: call GET **immediately before** the first confirm dialog so `owned_root_entries` and
`confirm_token` are fresh. Re-fetch if the token expires (15 minutes) or paths change.

When `action_available` is false, disable the button (`windows_only`, `safe_install_dir`, or empty roots).

### 2) POST start clean-reinstall

**Path:** `POST /api/installer/clean-reinstall/start`

**Body:**

```json
{
  "confirm_token": "<from GET>",
  "acknowledged_roots": ["C:\\Users\\owner\\AppData\\Local\\Jarvis"],
  "final_confirm": true,
  "setup_exe": null
}
```

- `acknowledged_roots` — copy of every `owned_root_entries[].path` from the same GET (order not important; must match set).
- `final_confirm` — must be `true` (UX implements **two-step** confirm before POST).
- `setup_exe` — optional JarvisSetup.exe override.

**Response started** (200 only when helper was spawned):

```json
{
  "status": "started",
  "message": "Clean reinstall helper started detached. Jarvis may stop immediately.",
  "log_paths": { "durable": "...", "install": "...", "status": "..." },
  "poll_path": "/api/installer/clean-reinstall/status"
}
```

**Response aborted** (HTTP 400 — never show success toast):

```json
{
  "status": "aborted",
  "reason": "confirm_token expired; call GET preview again",
  "log_paths": { "durable": "...", "install": "...", "status": "..." }
}
```

HTTP 200 **does not** mean wipe finished — only that the detached helper launched.

### 3) GET status (poll after POST)

**Path:** `GET /api/installer/clean-reinstall/status`

Poll after `status: "started"` until `status` is `succeeded`, `failed`, or remains `running`.
Backend reads `%TEMP%\\Jarvis-clean-reinstall.status.json` written by the PowerShell helper.

```json
{
  "status": "idle|running|succeeded|failed|unknown",
  "exit_reason": "ok|force-stop-failed|wipe-incomplete|setup-not-found|...|null",
  "log_paths": { "durable": "...", "install": "...", "status": "..." },
  "log_tail": ["..."],
  "updated_at": "2026-09-18T15:00:00Z"
}
```

### Danger rules (UX)

- Two-step confirm in the portal; default **No** on the destructive step.
- Never toast “clean install complete” on HTTP 400 or while `status` is `running`.
- Only treat wipe as complete when poll returns `status: "succeeded"` and `exit_reason: "ok"`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..installer.clean_reinstall import read_clean_reinstall_status, start_clean_reinstall_detached
from ..installer.owned_paths import owned_paths_preview

router = APIRouter(prefix="/api/installer", tags=["installer"])


class CleanReinstallStartBody(BaseModel):
    confirm_token: str = Field(..., description="Token from GET owned-roots / preview.")
    acknowledged_roots: list[str] = Field(
        ...,
        description="Exact set of owned_root_entries[].path from the same GET response.",
    )
    final_confirm: bool = Field(
        ...,
        description="Must be true after the owner's second confirmation step in the portal.",
    )
    setup_exe: str | None = Field(
        default=None,
        description="Optional JarvisSetup.exe path; staged to TEMP if under owned roots.",
    )


@router.get("/clean-reinstall/owned-roots")
async def clean_reinstall_owned_roots():
    """Owned paths + labels + confirm token for the Advanced danger card."""
    return owned_paths_preview()


@router.get("/clean-reinstall/preview")
async def clean_reinstall_preview():
    """Alias of owned-roots for backward compatibility."""
    return owned_paths_preview()


@router.get("/clean-reinstall/status")
async def clean_reinstall_status():
    """Poll helper progress after POST start (reads TEMP status file + log tail)."""
    return read_clean_reinstall_status()


@router.post("/clean-reinstall/start")
async def clean_reinstall_start(body: CleanReinstallStartBody):
    """Spawn detached clean-reinstall helper after token + roots validation."""
    result = start_clean_reinstall_detached(
        confirm_token=body.confirm_token,
        acknowledged_roots=body.acknowledged_roots,
        final_confirm=body.final_confirm,
        setup_exe=body.setup_exe,
    )
    if result.get("status") == "started":
        return result
    raise HTTPException(status_code=400, detail=result)
