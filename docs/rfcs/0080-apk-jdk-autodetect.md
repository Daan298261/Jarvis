# RFC-0080: Auto-discover JDK 17 for companion APK builds

**Status:** implemented  
**Queue item:** Companion APK builder fails without JAVA_HOME  
**Author:** Taco request via Cursor  
**Date:** 2026-09-12

## Problem

The owner UI APK build fails immediately with `Set JAVA_HOME to JDK 17 before building` even when JDK 17 (Eclipse Temurin) and the Jarvis Android SDK are already installed. Jarvis is often started from a shortcut that does not inherit those environment variables.

## Decision

`scripts/build_android.py` (and `setup_android.ps1`) auto-discover:

- JDK 17 under common Windows install roots (Eclipse Adoptium, Microsoft, Android Studio JBR as fallback)
- Android SDK at `%LOCALAPPDATA%\Jarvis\android-sdk` or Android Studio’s SDK folder

Explicit `JAVA_HOME` / `ANDROID_HOME` still win. Gradle/keytool subprocesses receive the resolved paths. If nothing is found, the error tells the owner to install Temurin 17 or run `setup_android.ps1`.

**Will not:** download a JDK automatically; change Gradle/AGP; edit Architect spec docs.

## Acceptance criteria

- [x] Missing `JAVA_HOME` still builds when Temurin 17 is installed in Program Files
- [x] Missing `ANDROID_HOME` still finds `%LOCALAPPDATA%\Jarvis\android-sdk` with platform 35
- [x] Unit tests for discovery (`python -m pytest tests/test_companion_apk_build.py`)

## Likely files

| Area | Paths |
| --- | --- |
| Scripts | `scripts/build_android.py`, `scripts/setup_android.ps1` |
| Tests | `tests/test_companion_apk_build.py` |
| Docs | this RFC, `docs/android-companion.md` |

## Out of scope

Live Gradle APK compile (desktop sign-off). Shipping a JDK inside the Jarvis installer.
