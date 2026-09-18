"""Installer owner actions (RFC-0124 clean reinstall).

UX contract (Settings → Advanced danger card — separate PR)
-----------------------------------------------------------

**GET** `/api/installer/clean-reinstall/preview`

Returns the owned-root allowlist and paths the portal should show before the
owner's second confirm. Does not start wipe or force-stop.

Example response::

    {
      "install_root": "C:\\\\Users\\\\owner\\\\AppData\\\\Local\\\\Jarvis",
      "owned_roots": ["C:\\\\Users\\\\owner\\\\AppData\\\\Local\\\\Jarvis"],
      "license_issuer_preserved": "C:\\\\...\\\\Jarvis\\\\license-issuer",
      "setup_exe": "C:\\\\...\\\\JarvisSetup.exe",
      "helper_script": "C:\\\\...\\\\installer\\\\windows\\\\clean-reinstall-jarvis.ps1",
      "force_stop_script": "C:\\\\...\\\\installer\\\\windows\\\\force-stop-jarvis.ps1",
      "windows_only": true,
      "safe_install_dir": true
    }

- `owned_roots` — only these directories are wiped (never `allowed_directories`,
  Documents, Desktop, or whole `%LOCALAPPDATA%`).
- `safe_install_dir` — false when the install tree fails `IsSafeJarvisInstallDir`;
  UX should disable the action and explain.
- `setup_exe` may be empty; portal start still attempts default search paths in the helper.

**POST** `/api/installer/clean-reinstall/start`

Body JSON::

    { "confirm": true, "setup_exe": null }

- `confirm` **must** be `true` (UX implements two-step confirm before calling).
- `setup_exe` optional override when the owner downloaded Setup elsewhere.

Success **202-style semantics**: returns immediately after spawning a **detached**
`clean-reinstall-jarvis.ps1` (backend/portal may be killed by force-stop). Does
not mean wipe completed.

Example success::

    {
      "ok": true,
      "message": "Clean reinstall started in a detached helper. Jarvis will stop shortly.",
      "log_hint": "%TEMP%\\\\Jarvis-clean-reinstall.log",
      "owned_roots": ["..."],
      "preview": { ...same shape as GET preview... }
    }

Errors: **400** with `detail` string when not Windows, missing scripts, no safe
roots, or launch failure. UX must not show a success toast on 400.

Logs: `%TEMP%\\Jarvis-clean-reinstall.log` (survives wipe) and
`{install_root}\\logs\\clean-reinstall.log` until deleted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..installer.clean_reinstall import start_clean_reinstall_detached
from ..installer.owned_paths import owned_paths_preview

router = APIRouter(prefix="/api/installer", tags=["installer"])


class CleanReinstallStartBody(BaseModel):
    confirm: bool = Field(..., description="Owner must pass true after reading owned roots.")
    setup_exe: str | None = Field(
        default=None,
        description="Optional JarvisSetup.exe path; staged to TEMP if under owned roots.",
    )


@router.get("/clean-reinstall/preview")
async def clean_reinstall_preview():
    """Owned roots and safety snapshot for confirm UI (RFC-0124)."""
    return owned_paths_preview()


@router.post("/clean-reinstall/start")
async def clean_reinstall_start(body: CleanReinstallStartBody):
    """Launch detached clean-reinstall helper; does not wait for completion."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    result = start_clean_reinstall_detached(setup_exe=body.setup_exe)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=str(result.get("error") or "start failed"))
    return result
