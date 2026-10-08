# tools/

Repo-root scripts and vendor-only overlays (not `backend/app/tools`).

- **License Manager (RFC-0087):** On vendor release machines, place private GUI source at `tools/license_manager/` (`__main__.py` entry). That tree is gitignored (see `.gitignore`). `installer/windows/build-license-manager.ps1` resolves it after `JARVIS_LICENSE_MANAGER_SRC`, or skips when the overlay is absent.
- **Bootstrap:** `installer/windows/bootstrap.ps1` may clone VoiceStudio into `tools/voicestudio/` on first setup.
