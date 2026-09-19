import { useSessionPersonalityOptional } from "./SessionPersonalityProvider"
import type { SessionPersonalityId } from "./sessionPersonality"

const ORDER: SessionPersonalityId[] = ["default", "coding", "research", "concise"]

export function SessionPersonalityControls() {
  const personality = useSessionPersonalityOptional()
  if (!personality?.state) return null

  const active = personality.state.active_id

  return (
    <div className="settings-session-personality" role="group" aria-label="Session personality">
      <h3 className="settings-subheading">Session personality</h3>
      <p className="lede" style={{ margin: "0 0 10px" }}>
        Adjusts HUD accent and the assistant register for this session. Say &ldquo;start a coding session&rdquo; in chat to
        switch by voice.
      </p>
      <div className="jarvis-presence-mode-row">
        {ORDER.map((id) => {
          const meta = personality.state?.personalities.find((p) => p.id === id)
          const label = meta?.display_name || id
          return (
            <button
              key={id}
              type="button"
              disabled={personality.busy}
              className={active === id ? "active" : ""}
              onClick={() => personality.select(id)}
            >
              {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function HudPersonalityCue() {
  const personality = useSessionPersonalityOptional()
  if (!personality?.state || personality.state.active_id === "default") return null
  return (
    <span className="hud-personality-cue" title="Active session personality">
      {personality.state.display_name}
    </span>
  )
}
