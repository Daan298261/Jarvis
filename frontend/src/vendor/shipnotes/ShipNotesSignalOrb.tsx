import React, { useEffect, useRef } from "react"

export type SignalOrbState = "listening" | "thinking" | "searching" | "done"

declare global {
  interface HTMLElementTagNameMap {
    "signal-orb": HTMLElement & { state: SignalOrbState; level: number }
  }
  namespace JSX {
    interface IntrinsicElements {
      "signal-orb": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        state?: SignalOrbState
        level?: number
      }
    }
  }
}

type ShipNotesSignalOrbProps = {
  state: SignalOrbState
  level?: number
  size?: number
}

export function ShipNotesSignalOrb({ state, level = 0.5, size = 120 }: ShipNotesSignalOrbProps) {
  const ref = useRef<HTMLElement & { state: SignalOrbState; level: number }>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.state = state
    el.level = level
  }, [state, level])

  return React.createElement("signal-orb", {
    ref,
    state,
    style: { width: size, maxWidth: "100%", display: "block" },
  })
}
