import { useState } from "react"
import { applyRuntimeProfile } from "../hud/applyRuntimeProfile"
import { isHexStrikeSuiteProfile, useHexStrikeSuiteActive } from "../hud/hexstrikeSuite"
import { useHudOverlayOptional } from "../hud/hudOverlayContext"
import { DAYBREAK_AVATAR_ID, usesDaybreakAppearance } from "./appearanceModes"
import { MYTHIC_LIVING_AVATAR_ID } from "./mythicPersonaVariant"
import { updatePresentation } from "./presentationSettings"
import type { PresentationSettings } from "./presenceTypes"

export function RenderModeButtons({ settings }: { settings: PresentationSettings }) {
  const { active, profiles } = useHexStrikeSuiteActive()
  const suite = profiles.find(isHexStrikeSuiteProfile)
  const overlay = useHudOverlayOptional()
  const [error, setError] = useState("")
  const selected = usesDaybreakAppearance(settings, active) ? "daybreak" : settings.requestedPresence
  async function choose(mode: "daybreak" | "galaxy" | "humanoid" | "particle_bust") {
    setError("")
    try {
      if (mode === "daybreak") {
        if (!suite) throw new Error("Daybreak runtime is not available")
        await updatePresentation({ shell: "hud", requestedPresence: "humanoid", avatarId: DAYBREAK_AVATAR_ID })
        await applyRuntimeProfile(suite.id || suite.name)
        overlay?.focusHexSuite()
      } else {
        overlay?.dismissHexSuiteForOverlay()
        await updatePresentation({ shell: "hud", requestedPresence: mode, avatarId: mode === "humanoid" ? "jarvis_base" : MYTHIC_LIVING_AVATAR_ID })
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      setError(err instanceof Error ? err.message : "Could not save appearance")
    }
  }
  return <>
    <div className="hud-render-modes" role="group" aria-label="Live render mode">
      {([ ["daybreak", "Daybreak"], ["galaxy", "Galaxy"], ["humanoid", "Humanoid"], ["particle_bust", "Persona avatar"] ] as const).map(([mode, label]) =>
        <button key={mode} type="button" aria-pressed={selected === mode} className={selected === mode ? "active" : ""}
          disabled={mode === "daybreak" && !suite} onClick={() => void choose(mode)}>{label}</button>)}
    </div>
    {error && <p role="alert">{error}</p>}
  </>
}
