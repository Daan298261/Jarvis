# Presence HUD centering and idle free-float

**Related:** RFC-0175 (lifecycle), RFC-0178 (adaptive framing), RFC-0194 (regression restore)

## Expected look

| Stage | What you should see |
| --- | --- |
| Idle / waiting / offline | Free-floating orbs (dots) that attract to the pointer |
| Engaged (listen / think / speak / …) | Same orbs morph into the winning figure (humanoid bust or persona shape) |
| Galaxy ADD | Extra starfield layer; lifecycle still runs |

## Common regressions

- **Idle shows a crushed bust** — `idle` was removed from free phases (#458). Idle must be free-float again.
- **Off-center avatar** — fit must use AABB center + span, not `2 * max(|min|,|max|)` around the origin.
- **Neural specialist ring misaligned** — keep the presence stage near 680∶480 and center it; do not stretch the WebGL canvas to fill an arbitrary HUD zone while `ReasoningWeb` stays on a fixed viewBox.
