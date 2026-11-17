# ANZU quality gates

Run `powershell -File scripts/verify.ps1 -Python <backend-venv-python>` on Windows.
The complete run includes the full backend suite, frontend build, real Manager
startup and browser smoke, dependency/secret scans, and the Windows installer.
The install gate prepares Playwright Chromium in the backend environment.
Tooling and browser caches stay under `.verify/`, outside installer source trees
and shared browser caches.
Gate failures remain failures; `.verify/report.json` records the full result.

The browser smoke starts an isolated Manager with its watchdog disabled and a
single ephemeral test origin. It checks narrow-window rendering, cancels and
then confirms a kill against its own copied Node executable, and verifies
process exit, refreshed inventory and the audit entry. Existing model processes
are never mutation targets. The production origin allowlist is unchanged.

`es_verify.py`, `es_stubs.py`, `es_secrets.py`, and `VERSION` are unchanged copies
from Daan298261/engineering-standards commit
`5755bc79fdc355522072eca719d2473cff2f7151`, `quality/`.
Changes to those upstream tools belong in the standards repository.

Python fatal-error lint is a new baseline using Ruff's E9/F63/F7/F82 rules;
frontend lint and TypeScript checking retain the existing project commands.
Formatting uses the repository's existing Git whitespace check. Broader Python
formatting, typing, and lint adoption requires a separate reviewed legacy baseline.
The static-analysis baseline contains only findings from unchanged
`origin/development` at the commit recorded inside it. It must shrink, never grow.
The secret scanner has no baseline or exclusions. Eight synthetic credential
markers in existing detector/redaction tests have narrow `es:allow-secret`
comments on their exact fixture/assertion lines. Their literal values and test
assertions remain intact; these comments do not permit production credentials.
