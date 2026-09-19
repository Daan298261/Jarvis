import { useState } from "react"
import { applyRuntimeProfile } from "../hud/applyRuntimeProfile"
import { useHexStrikeSuiteActive } from "../hud/hexstrikeSuite"
import { useHudOverlayOptional } from "../hud/hudOverlayContext"
import { updatePresentation } from "../presence/presentationSettings"
import type { PresentationSettings } from "../presence/presenceTypes"
import { SessionPersonalityControls } from "../personality/SessionPersonalityControls"

type AppearanceSettingsPaneProps = {
  settings: PresentationSettings
}

export function AppearanceSettingsPane({ settings }: AppearanceSettingsPaneProps) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const { active: hexStrikeActive, profile: hexstrikeProfile } = useHexStrikeSuiteActive()
  const overlay = useHudOverlayOptional()

  async function apply(patch: Partial<PresentationSettings>, note = "") {
    setBusy(true)
    setMessage("")
    try {
      await updatePresentation(patch)
      setMessage(note)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save presentation settings.")
    } finally {
      setBusy(false)
    }
  }

  async function activateHexStrike() {
    if (!hexstrikeProfile || busy) return
    setBusy(true)
    setMessage("")
    try {
      await applyRuntimeProfile(hexstrikeProfile.id || hexstrikeProfile.name)
      await updatePresentation({ shell: "hud", requestedPresence: "humanoid" })
      overlay?.focusHexSuite()
      setMessage("HexStrike · Daybreak suite active.")
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not activate HexStrike suite.")
    } finally {
      setBusy(false)
    }
  }

  const selected =
    settings.shell === "classic"
      ? "classic"
      : hexStrikeActive
        ? "hexstrike"
        : settings.requestedPresence

  return (
    <div className="settings-appearance-pane">
      <div className="jarvis-presence-mode-row" role="group" aria-label="Jarvis interface">
        <button
          type="button"
          disabled={busy}
          className={selected === "classic" ? "active" : ""}
          onClick={() => apply({ shell: "classic", requestedPresence: "none" })}
        >
          Classic
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "neural" ? "active" : ""}
          onClick={() => apply({ shell: "hud", requestedPresence: "neural" })}
        >
          Neural HUD
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "humanoid" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "humanoid" },
              "Humanoid presence active. Jarvis will fall back to Neural if WebGL is unavailable.",
            )
          }
        >
          Humanoid HUD · built in
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "particle_bust" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "particle_bust" },
              "Particle bust active. Jarvis will fall back to Neural if WebGL is unavailable.",
            )
          }
        >
          Particle bust · experimental
        </button>
        <button
          type="button"
          disabled={busy || !hexstrikeProfile}
          className={selected === "hexstrike" ? "active" : ""}
          title={hexstrikeProfile ? undefined : "HexStrike suite runtime is not installed"}
          onClick={() => void activateHexStrike()}
        >
          HexStrike · Daybreak
        </button>
      </div>

      <SessionPersonalityControls />

      <label>
        Rendering
        <select
          disabled={busy}
          value={settings.performancePreset}
          onChange={(event) =>
            apply({ performancePreset: event.target.value as PresentationSettings["performancePreset"] })
          }
        >
          <option value="auto">Auto</option>
          <option value="efficient">Efficient</option>
          <option value="balanced">Balanced</option>
          <option value="cinematic">Cinematic</option>
        </select>
      </label>

      <label>
        Attention
        <select
          disabled={busy}
          value={settings.attentionMode}
          onChange={(event) =>
            apply(
              { attentionMode: event.target.value as PresentationSettings["attentionMode"] },
              event.target.value === "camera" ? "Camera preference saved. RFC-0050 does not activate a camera." : "",
            )
          }
        >
          <option value="off">Off</option>
          <option value="pointer">Follow pointer</option>
          <option value="camera">Camera preference (not activated here)</option>
        </select>
      </label>

      <label>
        Motion
        <select
          disabled={busy}
          value={settings.reducedMotion}
          onChange={(event) =>
            apply({ reducedMotion: event.target.value as PresentationSettings["reducedMotion"] })
          }
        >
          <option value="system">Follow system</option>
          <option value="reduce">Reduce motion</option>
          <option value="full">Full motion</option>
        </select>
      </label>

      {message && <p className="jarvis-presence-controls-message" role="status">{message}</p>}
    </div>
  )
}
