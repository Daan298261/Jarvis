import React, { useState } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { PresenceHost } from "./src/presence/PresenceHost"
import {
  DEFAULT_PRESENTATION_SETTINGS,
  type PresencePhase,
} from "./src/presence/presenceTypes"
import { listPresenceShapes } from "./src/presence/renderers/shapes/catalog"
import "./src/presence/presence.css"

function Check() {
  const shapes = listPresenceShapes()
  const [phase, setPhase] = useState<PresencePhase>("idle")
  const [shapeId, setShapeId] = useState("humanoid_bust")
  const [settings, setSettings] = useState({
    ...DEFAULT_PRESENTATION_SETTINGS,
    requestedPresence: "humanoid" as const,
    performancePreset: "cinematic" as const,
    reducedMotion: "full" as const,
    avatarId: "humanoid_bust",
  })

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "#03070b" }}>
      <div style={{ padding: 12, display: "flex", gap: 20, flexWrap: "wrap", flex: "0 0 auto" }}>
        <label>
          Phase{" "}
          <select
            value={phase}
            onChange={(e) => setPhase(e.target.value as PresencePhase)}
          >
            {["idle", "listening", "thinking", "executing", "speaking", "waiting", "alert", "offline"].map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
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
          Reduce motion{" "}
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
          Efficient{" "}
          <input
            type="checkbox"
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                performancePreset: e.target.checked ? "efficient" : "cinematic",
              }))
            }
          />
        </label>
      </div>
      <div style={{ flex: "1 1 auto", minHeight: 0, display: "flex" }}>
        <PresenceHost
          settings={settings}
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
