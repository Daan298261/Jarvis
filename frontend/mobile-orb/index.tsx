import React, { useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import ApexOrb from "../src/vendor/apex-ui/ApexOrb"
import HumanoidPresence from "../src/presence/renderers/HumanoidPresence"
import { supportsHumanoidRuntime } from "../src/presence/renderers/humanoidRuntime"
import type { PresenceSnapshot, PresentationSettings } from "../src/presence/presenceTypes"
import "../src/vendor/apex-ui/apex-orb.css"
import "./orb.css"

type MobilePhase = "idle" | "listening" | "thinking" | "speaking"
type MobileAppearance = "orb" | "humanoid"

declare global {
  interface Window {
    setJarvisPhase?: (next: string) => void
    setJarvisAppearance?: (next: string) => void
  }
}

const humanoidSettings: PresentationSettings = {
  shell: "hud",
  requestedPresence: "humanoid",
  performancePreset: "efficient",
  attentionMode: "pointer",
  reducedMotion: "system",
  avatarId: "jarvis_base",
}

function humanoidSnapshot(phase: MobilePhase): PresenceSnapshot {
  return {
    phase,
    intensity: phase === "speaking" ? 0.92 : phase === "thinking" ? 0.65 : phase === "listening" ? 0.5 : 0.2,
    connected: true,
    runningTaskCount: phase === "thinking" ? 1 : 0,
    decisionCount: 0,
    systemDegraded: false,
    audioLevel: phase === "speaking" ? 0.7 : 0,
  }
}

export function MobilePresence() {
  const [phase, setPhase] = useState<"idle" | "listening" | "thinking" | "speaking">("idle")
  const [appearance, setAppearance] = useState<MobileAppearance>(() =>
    new URLSearchParams(window.location.search).get("appearance") === "humanoid" ? "humanoid" : "orb",
  )
  useEffect(() => {
    window.setJarvisPhase = (next: string) => {
      if (["idle", "listening", "thinking", "speaking"].includes(next)) setPhase(next as typeof phase)
    }
    window.setJarvisAppearance = (next: string) => {
      if (next === "orb" || next === "humanoid") setAppearance(next)
    }
    return () => {
      delete window.setJarvisPhase
      delete window.setJarvisAppearance
    }
  }, [])
  if (appearance === "humanoid" && supportsHumanoidRuntime()) {
    return <HumanoidPresence snapshot={humanoidSnapshot(phase)} settings={humanoidSettings} size={430} />
  }
  return <ApexOrb state={phase} />
}
createRoot(document.getElementById("root")!).render(<MobilePresence />)
