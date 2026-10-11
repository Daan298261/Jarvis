## Summary

Opening Phone Pairing prepares LAN TLS and produces a QR before any phone is detected. Both compact and full panels show it. Android retains QR/Wi-Fi scanning and desktop fingerprint approval; no WAN mapping is created by pair intent.

More → App access optionally requires the phone PIN/password or strong biometrics. Android authenticates enabling/disabling and unlocking; all app screens are gated, background return locks, screenshots are blocked, and drafts survive locking. Android 10 uses credentials; Android 11+ also offers strong biometrics.

Incremental APKs now retain the Whisper, Pocket TTS and ONNX shared libraries for both ABIs. The local builder and Android CI verify APK contents before publishing, including rejecting missing/empty runtime entries.

## Validation

- Full backend CI: 2,866 passed, 2 skipped. Model/security regression gate: 67 passed. Local affected suites: 76 pairing/mobile/APK/elevation + 42 pack/installer tests passed.
- Frontend build/lint passed (existing warnings).
- Android debug build, lint and all 124 unit tests passed, including PIN success, cancellation, disable authentication and relocking.
- Signed generic release APK built with the existing owner signing identity; signature verified. Both ABIs include llama, Whisper, Pocket TTS and ONNX libraries.
- Windows AtomicFile replacement is corrected in test shadows only. Native clones support long Windows paths. Two stale health assertions now enforce the existing liveness-only response. Pack fixtures require verified markers and assert polling never hashes weights; the startup assertion includes force restart.
- Full local backend run stalled in Windows socketpair/asyncio loop creation; faulthandler evidence retained locally. Full canonical backend CI subsequently passed.
- No physical phone attached. Live QR, biometrics, calls, GGUF and neural audio remain device acceptance; abliterated pack selection awaits the owner's exact model/file.

RFC-0204 S1/S2 were merged in #576; reviewed S3/S4 merged in #575. Codex branch coverage is recorded in docs/codex-branch-android-review.md. Installed Windows artifacts are unchanged.



