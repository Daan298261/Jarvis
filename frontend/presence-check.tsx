import React, { useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { PresenceHost } from "./src/presence/PresenceHost"
import {
  DEFAULT_PRESENTATION_SETTINGS,
  type PresencePhase,
  type PresentationSettings,
} from "./src/presence/presenceTypes"
import { listPresenceShapes } from "./src/presence/renderers/shapes/catalog"
import { PERSONA_LABELS, PERSONA_VISUALS, ROSTER_IDS } from "./src/persona/namedPersonas"
import { personaPortraitForId } from "./src/persona/personaPortraits"
import "./src/presence/presence.css"

export function Check() {
  const shapes = listPresenceShapes()
  const [phase, setPhase] = useState<PresencePhase>("idle")
  const [shapeId, setShapeId] = useState("humanoid_bust")
  const [personaId, setPersonaId] = useState("anzu")
  const [dotAppearance, setDotAppearance] = useState({ pointScale: 1, depthSoftness: 0 })
  const [settings, setSettings] = useState<PresentationSettings>({
    ...DEFAULT_PRESENTATION_SETTINGS,
    requestedPresence: "humanoid" as const,
    performancePreset: "cinematic" as const,
    reducedMotion: "full" as const,
    avatarId: "humanoid_bust",
  })
  const [summary, setSummary] = useState("Waiting for renderer…")
  const visual = PERSONA_VISUALS[personaId as keyof typeof PERSONA_VISUALS] || PERSONA_VISUALS.anzu
  const personaVisual = {
    personaId,
    personaLabel: PERSONA_LABELS[personaId] || personaId,
    portraitUrl: personaPortraitForId(personaId),
    orbColor: visual.orbColor,
    accentColor: visual.accentColor,
    glow: 0.82,
    animation: 0.72,
    scale: 1,
    ...dotAppearance,
  }

  useEffect(() => {
    const timer = window.setInterval(() => {
      const stage = document.querySelector<HTMLElement>("[data-presence-samples]")
      if (!stage) return
      setSummary(
        `${stage.dataset.presenceFps ?? "—"} fps · ${stage.dataset.presenceFrameMs ?? "—"} ms avg · ${stage.dataset.presenceSamples ?? "—"} points · morph ${stage.dataset.morph ?? "—"} · rest ${stage.dataset.restTightness ?? "—"}`,
      )
    }, 500)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div style={{ width: "100vw", height: "100vh", minHeight: 0, display: "flex", flexDirection: "column", background: "#03070b", overflow: "hidden" }}>
      <div style={{ padding: 12, display: "flex", gap: 20, flexWrap: "wrap", flex: "0 0 auto" }}>
        <label>
          Phase{" "}
          <select
            value={phase}
            onChange={(e) => setPhase(e.target.value as PresencePhase)}
          >
            {["idle", "listening", "thinking", "executing", "speaking", "waiting", "alert", "approval", "error", "offline"].map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          Presence{" "}
          <select
            value={settings.requestedPresence}
            onChange={(e) => setSettings((s) => ({
              ...s,
              requestedPresence: e.target.value as "humanoid" | "particle_bust",
            }))}
          >
            <option value="humanoid">Restored humanoid</option>
            <option value="particle_bust">Mythic persona</option>
          </select>
        </label>
        <label>
          Persona{" "}
          <select
            value={personaId}
            onChange={(e) => {
              const id = e.target.value
              setPersonaId(id)
              setShapeId(PERSONA_VISUALS[id as keyof typeof PERSONA_VISUALS]?.shapeId || "stormbird")
            }}
          >
            {ROSTER_IDS.map((id) => <option key={id} value={id}>{PERSONA_LABELS[id]}</option>)}
          </select>
        </label>
        <label>
          Shape{" "}
          <select
            value={shapeId}
            onChange={(e) => {
              const id = e.target.value
              setShapeId(id)
              setSettings((s) => ({ ...s, avatarId: id }))
            }}
          >
            {shapes.map((shape) => (
              <option key={shape.id} value={shape.id}>{shape.label}</option>
            ))}
          </select>
        </label>
        <label>
          Attention{" "}
          <select
            value={settings.attentionMode}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                attentionMode: e.target.value as typeof s.attentionMode,
              }))
            }
          >
            <option value="pointer">pointer</option>
            <option value="camera">camera</option>
            <option value="off">off</option>
          </select>
        </label>
        <label>
          Reduced motion{" "}
          <input
            type="checkbox"
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                reducedMotion: e.target.checked ? "reduce" : "full",
              }))
            }
          />
        </label>
        <label>
          Quality{" "}
          <select
            value={settings.performancePreset}
            onChange={(e) => setSettings((s) => ({ ...s, performancePreset: e.target.value as typeof s.performancePreset }))}
          >
            {["auto", "efficient", "balanced", "cinematic"].map((preset) => (
              <option key={preset} value={preset}>{preset}</option>
            ))}
          </select>
        </label>
        <label>
          Point size{" "}
          <input type="range" min="0.5" max="1.5" step="0.05" value={dotAppearance.pointScale}
            onChange={(e) => setDotAppearance((v) => ({ ...v, pointScale: Number(e.target.value) }))} />
        </label>
        <label>
          Depth softness{" "}
          <input type="range" min="0" max="1" step="0.05" value={dotAppearance.depthSoftness}
            onChange={(e) => setDotAppearance((v) => ({ ...v, depthSoftness: Number(e.target.value) }))} />
        </label>
        <output aria-live="polite">{summary}</output>
      </div>
      <div style={{ flex: "1 1 auto", minHeight: 0, display: "flex" }}>
        <PresenceHost
          settings={settings}
          shapeId={shapeId}
          personaVisual={personaVisual}
          snapshot={{
            phase,
            intensity: 0.7,
            connected: phase !== "offline",
            runningTaskCount: 0,
            decisionCount: 0,
            systemDegraded: phase === "alert",
            audioLevel: phase === "speaking" ? 0.6 : 0,
          }}
        />
      </div>
    </div>
  )
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Check />
    </BrowserRouter>
  </React.StrictMode>,
)
