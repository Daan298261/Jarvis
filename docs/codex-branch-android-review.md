# Codex branches and Android delivery review — 2026-10-10

Reviewed local `codex/*` branches against freshly fetched `origin/development`.
The owner checkout's untracked files and all existing worktrees were preserved.

| Branch group | Current development coverage |
| --- | --- |
| chat-backend-recovery | Equivalent patch already merged |
| db-session-cleanup-dev/main, suite-stability-dev | Equivalent patches already merged |
| installer-151-hotfix, release-151, quote-fix and stop-scope variants | Equivalent patches already merged |
| installer-151-packaging and packaging-main | Payload exclusions superseded by #516/#517 and current explicit payload allowlist; stale sidecar replacement is present in `scripts/build-backend-sidecar.ps1` |
| ui | Administrator/upgrade behavior landed via #465; cinematic persona and routing work landed as `b0859b52`, with later persona/routing upgrades retained |
| rfc-dot-ui-engine | Equivalent RFC patch already merged |
| persona-presence-main/release, review-pr491 | No commits ahead of development |

No unique unfinished product change remains in these Codex branches. Patch-ID
comparison was followed by reviewing current installer, elevation, routing and
presence implementations where older combined patches were superseded.

## Android

- RFC-0204 standalone/chat/voice slices S1/S2 landed in #576. Reviewed and merged
  S3/S4 rename/splash/sponsor changes in #575 (`f2255cf5`).
- RFC-0059, 0064, 0063, 0065, 0074, 0076, 0108, 0123, 0125, 0139 and 0140
  have implementation records. RFC-0039 remains the original parent design;
  its physical calling/audio-route/network-switch acceptance is still separate.
- RFC-0213 closes the first-pair QR preparation gap and adds optional native app access.
- RFC-0204 explicitly leaves the abliterated model's exact repository/file pending
  owner selection. Existing Qwen 1.5B remains the usable fallback; no placeholder
  pack or unverified weights were added.
- No phone was attached according to `adb devices -l`. Camera/QR, live biometrics,
  real-model offline voice and incoming-call acceptance cannot be signed off here.
- Merging source does not update the installed Windows executable.
