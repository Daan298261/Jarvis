import React, { useEffect, useRef } from "react"
import type { ApexOrbState } from "../apex-ui/ApexOrb"

declare global {
  interface HTMLElementTagNameMap {
    "voice-orb": HTMLElement & {
      state: ApexOrbState
      connect(source: MediaStream | HTMLMediaElement | AudioNode): Promise<void>
      disconnect(): void
      bands?: number[]
    }
  }
  namespace JSX {
    interface IntrinsicElements {
      "voice-orb": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        state?: ApexOrbState
      }
    }
  }
}

type ShipNotesVoiceOrbProps = {
  state: ApexOrbState
  size?: number
  audioElement?: HTMLMediaElement | null
}

export function ShipNotesVoiceOrb({ state, size = 420, audioElement }: ShipNotesVoiceOrbProps) {
  const ref = useRef<HTMLElement & { state: ApexOrbState }>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.state = state
  }, [state])

  useEffect(() => {
    const el = ref.current as HTMLElement & {
      connect?(source: HTMLMediaElement): Promise<void>
      disconnect?(): void
    }
    if (!el?.connect || !audioElement) return
    let cancelled = false
    void el.connect(audioElement).then(() => {
      if (cancelled) el.disconnect?.()
    })
    return () => {
      cancelled = true
      el.disconnect?.()
    }
  }, [audioElement])

  return React.createElement("voice-orb", {
    ref,
    state,
    style: { width: size, maxWidth: "100%", display: "block", margin: "0 auto" },
  })
}
