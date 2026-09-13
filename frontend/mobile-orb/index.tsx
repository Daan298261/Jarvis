import React, { useEffect, useMemo, useState } from "react"
import { createRoot } from "react-dom/client"
import ApexOrb from "../src/vendor/apex-ui/ApexOrb"
import HumanoidPresence from "../src/presence/renderers/HumanoidPresence"
import { supportsHumanoidRuntime } from "../src/presence/renderers/humanoidRuntime"
import type { PresenceSnapshot, PresentationSettings } from "../src/presence/presenceTypes"
import "../src/vendor/apex-ui/apex-orb.css"
import "./orb.css"

type MobilePhase = "idle" | "listening" | "thinking" | "speaking"
type MobileAppearance = "orb" | "humanoid"
type OrbPhase = MobilePhase | "offline"

declare global {
  interface Window {
    setJarvisPhase?: (next: string) => void
    setJarvisAppearance?: (next: string) => void
    setJarvisConnected?: (connected: boolean) => void
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

function humanoidSnapshot(phase: MobilePhase, connected: boolean): PresenceSnapshot {
  const effective = !connected && phase === "idle" ? "offline" : phase
  return {
    phase: effective,
    intensity: effective === "speaking" ? 0.92 : effective === "thinking" ? 0.65 : effective === "listening" ? 0.5 : effective === "offline" ? 0.12 : 0.2,
    connected,
    runningTaskCount: phase === "thinking" ? 1 : 0,
    decisionCount: 0,
    systemDegraded: !connected,
    audioLevel: phase === "speaking" ? 0.7 : 0,
  }
}

function orbPhase(phase: MobilePhase, connected: boolean): OrbPhase {
  if (!connected && phase === "idle") return "offline"
  return phase
}

export function MobilePresence() {
  const [phase, setPhase] = useState<MobilePhase>("idle")
  const [connected, setConnected] = useState(true)
  const [appearance, setAppearance] = useState<MobileAppearance>(() =>
    new URLSearchParams(window.location.search).get("appearance") === "humanoid" ? "humanoid" : "orb",
  )
  useEffect(() => {
    window.setJarvisPhase = (next: string) => {
      if (["idle", "listening", "thinking", "speaking"].includes(next)) setPhase(next as MobilePhase)
    }
    window.setJarvisAppearance = (next: string) => {
      if (next === "orb" || next === "humanoid") setAppearance(next)
    }
    window.setJarvisConnected = (next: boolean) => setConnected(!!next)
    return () => {
      delete window.setJarvisPhase
      delete window.setJarvisAppearance
      delete window.setJarvisConnected
    }
  }, [])
  useEffect(() => {
    document.documentElement.dataset.jarvisConnected = connected ? "true" : "false"
  }, [connected])
  const displayPhase = useMemo(() => orbPhase(phase, connected), [phase, connected])
  if (appearance === "humanoid" && supportsHumanoidRuntime()) {
    return <HumanoidPresence snapshot={humanoidSnapshot(phase, connected)} settings={humanoidSettings} size={430} />
  }
  return <ApexOrb state={displayPhase} />
}
createRoot(document.getElementById("root")!).render(<MobilePresence />)
