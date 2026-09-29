/**
 * Ship Notes–inspired signal orb for OpenMuse session mode (MIT reference UI).
 * Lightweight CSS animation — not the full WebGL particle count from shipnotes-components.
 */
import { useEffect, useState } from "react"

export type SignalOrbState = "idle" | "listening" | "thinking" | "speaking"

type Props = {
  state?: SignalOrbState
  size?: number
}

export function ShipnotesSignalOrb({ state = "idle", size = 120 }: Props) {
  const [pulse, setPulse] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => setPulse((p) => (p + 1) % 360), state === "thinking" ? 40 : 80)
    return () => window.clearInterval(id)
  }, [state])

  const scale = state === "speaking" ? 1.08 : state === "listening" ? 1.04 : 1
  const glow =
    state === "thinking"
      ? "0 0 48px rgba(147, 112, 219, 0.75)"
      : state === "speaking"
        ? "0 0 42px rgba(96, 200, 255, 0.7)"
        : state === "listening"
          ? "0 0 36px rgba(120, 255, 180, 0.55)"
          : "0 0 28px rgba(180, 200, 255, 0.35)"

  return (
    <div
      className="shipnotes-signal-orb"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        transform: `scale(${scale}) rotate(${pulse * (state === "thinking" ? 2 : 0.5)}deg)`,
        boxShadow: glow,
        background:
          "radial-gradient(circle at 30% 28%, rgba(255,255,255,0.95), rgba(140,180,255,0.5) 42%, rgba(40,60,120,0.85) 100%)",
        transition: "transform 0.35s ease, box-shadow 0.35s ease",
      }}
      aria-hidden
    />
  )
}
