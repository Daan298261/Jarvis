import { useState } from "react"
import { applyRuntimeProfile } from "../hud/applyRuntimeProfile"
import { useHexStrikeSuiteActive } from "../hud/hexstrikeSuite"
import { useHudOverlayOptional } from "../hud/hudOverlayContext"
import { NamedPersonaControls } from "../persona/NamedPersonaControls"
import { PersonaVisualSliders } from "../persona/PersonaVisualSliders"
import { SessionPersonalityControls } from "../personality/SessionPersonalityControls"
import { CustomPresencePanel } from "../presence/CustomPresencePanel"
import { PresenceModePreview } from "../presence/PresenceModePreview"
import { updatePresentation } from "../presence/presentationSettings"
import type { PresentationSettings } from "../presence/presenceTypes"
import { MUSCULAR_HUMANOID_AVATAR_ID } from "../presence/renderers/HumanoidPresence"
import {
  MYTHIC_LIVING_AVATAR_ID,
  MYTHIC_LIVE_B_AVATAR_ID,
  MYTHIC_PORTRAIT_A_AVATAR_ID,
} from "../presence/mythicPersonaVariant"

type AppearanceSettingsPaneProps = {
  settings: PresentationSettings
  /** HUD Appearance menu hides persona editors (those live under Persona). */
  showPersona?: boolean
}

const APEX_ASSISTIVE =
  "Public MIT APEX-UI orb and reasoning graph, adapted for Jarvis. Jarvis does not include APEX's separately hosted private humanoid figure."

export function AppearanceSettingsPane({ settings, showPersona = true }: AppearanceSettingsPaneProps) {
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
      setMessage(error instanceof Error ? error.message : "Appearance changed locally; the saved setting could not be confirmed.")
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
        : settings.requestedPresence === "humanoid" && settings.avatarId === MUSCULAR_HUMANOID_AVATAR_ID
          ? "muscular_humanoid"
          : settings.requestedPresence === "particle_bust" && settings.avatarId === MYTHIC_LIVING_AVATAR_ID
            ? "mythic_living_b"
          : settings.requestedPresence === "particle_bust" && settings.avatarId === MYTHIC_LIVE_B_AVATAR_ID
            ? "mythic_live_b"
          : settings.requestedPresence

  return (
    <div className="settings-appearance-pane">
      <p className="jarvis-presence-mode-lede" id="jarvis-presence-mode-help">
        Presence modes are style and profile controls on one shared renderer. Previews match the live look for each profile.
      </p>
      <div className="jarvis-presence-mode-row" role="group" aria-label="Jarvis interface" aria-describedby="jarvis-presence-mode-help">
        <button
          type="button"
          disabled={busy}
          className={selected === "classic" ? "active" : ""}
          onClick={() => apply({ shell: "classic", requestedPresence: "none" })}
        >
          <PresenceModePreview mode="classic" />
          Classic portal
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "neural" ? "active" : ""}
          title={APEX_ASSISTIVE}
          aria-describedby="jarvis-apex-ui-help"
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "neural" },
              "APEX UI · orb + graph active on the shared presence stage.",
            )
          }
        >
          <PresenceModePreview mode="neural" />
          APEX UI · orb + graph
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "humanoid" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "humanoid", avatarId: "jarvis_base" },
              "Humanoid profile active on the shared presence stage. Jarvis falls back to APEX UI · orb + graph if WebGL is unavailable.",
            )
          }
        >
          <PresenceModePreview mode="humanoid" />
          Humanoid HUD · built in
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "muscular_humanoid" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "humanoid", avatarId: MUSCULAR_HUMANOID_AVATAR_ID },
              "Muscular humanoid restored from the original Jarvis showcase artwork.",
            )
          }
        >
          <PresenceModePreview mode="muscular_humanoid" />
          Muscular humanoid · showcase
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "particle_bust" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "particle_bust", avatarId: MYTHIC_PORTRAIT_A_AVATAR_ID },
              "Mythic portrait cloud A active. Persona selections morph immediately on the shared particle stage.",
            )
          }
        >
          <PresenceModePreview mode="particle_bust" />
          Mythic persona A · portrait cloud
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "mythic_live_b" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "particle_bust", avatarId: MYTHIC_LIVE_B_AVATAR_ID },
              "Mythic persona B active: detailed particle artwork with live gaze.",
            )
          }
        >
          <PresenceModePreview mode="mythic_live_b" />
          Mythic persona B · live gaze
        </button>
        <button type="button" disabled={busy}
          className={selected === "mythic_living_b" ? "active" : ""}
          onClick={() => apply({ shell: "hud", requestedPresence: "particle_bust", avatarId: MYTHIC_LIVING_AVATAR_ID },
            "Anzu and Nabu emerge from the window edge with breathing bodies and settling wings. Other personas retain their detailed B avatars.")}
        >
          <PresenceModePreview mode="mythic_live_b" />
          Living body · Anzu / Nabu
        </button>
        <button
          type="button"
          disabled={busy || !hexstrikeProfile}
          className={selected === "hexstrike" ? "active" : ""}
          title={hexstrikeProfile ? undefined : "HexStrike suite runtime is not installed"}
          onClick={() => void activateHexStrike()}
        >
          <PresenceModePreview mode="hexstrike" />
          HexStrike · Daybreak
        </button>
        <button
          type="button"
          disabled={busy}
          className={selected === "galaxy" ? "active" : ""}
          onClick={() =>
            apply(
              { shell: "hud", requestedPresence: "galaxy" },
              "Galaxy starfield ADD active on the shared presence stage. Jarvis falls back to APEX UI · orb + graph if WebGL is unavailable.",
            )
          }
        >
          <PresenceModePreview mode="galaxy" />
          Galaxy
        </button>
      </div>
      <p className="jarvis-presence-mode-apex-help" id="jarvis-apex-ui-help">
        {APEX_ASSISTIVE}
      </p>

      {!showPersona && <PersonaVisualSliders />}
      {showPersona && (
        <>
          <SessionPersonalityControls />
          <NamedPersonaControls />
        </>
      )}
      <CustomPresencePanel settings={settings} />

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
              event.target.value === "camera" ? "Camera tracking will ask for permission when the humanoid presence is open. Video stays on this device and is never stored." : "",
            )
          }
        >
          <option value="off">Off</option>
          <option value="pointer">Follow pointer</option>
          <option value="camera">Camera: head, eyes & hand energy</option>
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
