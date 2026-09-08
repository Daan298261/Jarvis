# Vendored APEX-UI components

Source: `RubenM1990/APEX-UI` at commit `f9fd176833a39b4634bad23cdc898fac4e0ab6a2`.
License: MIT. See `frontend/third_party/APEX-UI/LICENSE` and `CREDITS.md`.

Jarvis vendors the APEX SVG orb, its animation stylesheet, and the reasoning-web renderer rather than reimplementing those visuals. The files are kept close to upstream; small integration edits are limited to TypeScript declarations, encoding/comment normalization, and Jarvis-side adapters. APEX/Reznikov product branding is not used as Jarvis branding.

Jarvis-specific state, specialist availability, navigation, accessibility, reduced-motion behavior, and capability honesty live outside the vendored files in the Presence Architecture adapter.
