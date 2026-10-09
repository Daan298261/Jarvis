import { useEffect, useState, type CSSProperties } from "react"
import { galaxyStatusText } from "../galaxyPresence"
import type { PersonaCloudVisual, PresencePhase, PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { readVoiceMeter } from "../../tts/voiceAnalyser"
import { MorphablePresenceStage } from "./MorphablePresenceStage"
import { preparePortraitCloud } from "./shapes/portraitCloud"
import {
  SETTINGS_CLOUD_SHAPE_ID,
  usesMythicLiveVariantB,
} from "../mythicPersonaVariant"
import "./humanoid-presence.css"

// The default is the locked production humanoid. Keep its asset and fallback
// behavior stable; the README-era broad-shouldered figure is opt-in.
const CURRENT_HUMANOID_ARTWORK = "/presence/jarvis-original/humanoid.webp"
const MUSCULAR_HUMANOID_ARTWORK = "/presence/jarvis-original/humanoid-muscular.png"
export const MUSCULAR_HUMANOID_AVATAR_ID = "humanoid_muscular"

type HumanoidPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
  /** Optional override for harness / morph demos; defaults from settings.avatarId. */
  shapeId?: string
  personaVisual?: PersonaCloudVisual
}

function phaseLabel(phase: PresencePhase): string {
  if (phase === "executing") return "WORKING"
  return phase.toUpperCase()
}

export function HumanoidPresence({ snapshot, settings, shapeId, personaVisual }: HumanoidPresenceProps) {
  const galaxy = settings.requestedPresence === "galaxy"
  const mythic = settings.requestedPresence === "particle_bust"
  const settingsCloud = shapeId === SETTINGS_CLOUD_SHAPE_ID
  const liveVariantB = usesMythicLiveVariantB(settings.avatarId)
  const muscular = !mythic && settings.avatarId === MUSCULAR_HUMANOID_AVATAR_ID
  const portraitUrl = mythic && personaVisual?.portraitUrl
    ? personaVisual.portraitUrl
    : muscular
      ? MUSCULAR_HUMANOID_ARTWORK
      : CURRENT_HUMANOID_ARTWORK
  const portraitId = mythic
    ? personaVisual?.personaId || "anzu"
    : muscular
      ? MUSCULAR_HUMANOID_AVATAR_ID
      : "humanoid"
  const volumetric = mythic && liveVariantB
  const artworkKey = `${portraitId}:${portraitUrl}:${volumetric}`
  const [artwork, setArtwork] = useState<{ key: string; shapeId: string }>()
  const [failedArtworkKey, setFailedArtworkKey] = useState<string>()
  const portraitBacked = !galaxy && !settingsCloud
  const preparing = portraitBacked && mythic && artwork?.key !== artworkKey && failedArtworkKey !== artworkKey
  const prepareError = portraitBacked && mythic && failedArtworkKey === artworkKey
  useEffect(() => {
    let cancelled = false
    if (!portraitBacked) return () => { cancelled = true }
    preparePortraitCloud(portraitUrl, portraitId, volumetric)
      .then(shapeId => {
        if (cancelled) return
        setArtwork({ key: artworkKey, shapeId })
        setFailedArtworkKey(undefined)
      })
      .catch(error => {
        if (cancelled) return
        setFailedArtworkKey(artworkKey)
        console.warn("Presence artwork unavailable; retaining the current particle figure", error)
      })
    return () => { cancelled = true }
  }, [artworkKey, portraitBacked, portraitId, portraitUrl, volumetric])
  const [meter, setMeter] = useState({ level: 0, attached: false })

  useEffect(() => {
    const live = galaxy && (snapshot.phase === "speaking" || snapshot.phase === "listening")
    if (!live) {
      setMeter({ level: 0, attached: false })
      return
    }
    const expected = snapshot.phase === "speaking" ? "tts" : "mic"
    let frame = 0
    let last = 0
    const tick = (time: number) => {
      frame = window.requestAnimationFrame(tick)
      if (time - last < 80) return
      last = time
      const reading = readVoiceMeter()
      const attached = reading.attached && reading.kind === expected
      setMeter({ level: attached ? reading.level : 0, attached })
    }
    frame = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(frame)
  }, [galaxy, snapshot.phase])

  return (
    <MorphablePresenceStage
      snapshot={snapshot}
      settings={settings}
      shapeId={settingsCloud
        ? SETTINGS_CLOUD_SHAPE_ID
        : galaxy
            ? shapeId
            : portraitBacked
              ? artwork?.shapeId || "humanoid_bust"
              : shapeId || "humanoid_bust"}
      personaVisual={personaVisual}
      className={`jarvis-presence jarvis-presence-stage jarvis-presence-humanoid${mythic ? " jarvis-presence-particle" : ""}${galaxy ? " galaxy" : ""}`}
      ariaLabel={`${mythic ? personaVisual?.personaLabel || "ANZU mythic" : muscular ? "ANZU muscular humanoid" : "ANZU particle"} presence is ${snapshot.phase === "executing" ? "working" : snapshot.phase}`}
    >
      {snapshot.phase === "offline" && <span className="jarvis-presence-broken-ring" aria-hidden="true" />}
      {snapshot.phase === "approval" && <span className="jarvis-presence-lock-ring" aria-hidden="true" />}
      {preparing && (
        <span className="jarvis-presence-fallback-note" role="status">
          Forming {personaVisual?.personaLabel || "avatar"}…
        </span>
      )}
      {prepareError && mythic && (
        <span className="jarvis-presence-fallback-note" role="status">
          Avatar artwork unavailable · retaining the previous figure
        </span>
      )}
      {galaxy ? (
        <p
          className="jarvis-galaxy-status"
          role="status"
          style={personaVisual?.accentColor ? { "--galaxy-accent": personaVisual.accentColor } as CSSProperties : undefined}
        >
          {galaxyStatusText(snapshot.phase, {
            analyser: meter.attached,
            level: meter.level,
            bust: true,
          })}
        </p>
      ) : (
        <>
          <div className="jarvis-humanoid-hud" aria-hidden="true">
            <span className="jarvis-humanoid-hud-tl" />
            <span className="jarvis-humanoid-hud-tr">
              TEM // PRESENCE
              <br />
              {phaseLabel(snapshot.phase)}
            </span>
            <span className="jarvis-humanoid-hud-bl" />
          </div>
          <div className="jarvis-humanoid-label" aria-hidden="true">
            <span>{(mythic ? personaVisual?.personaLabel || "ANZU" : "ANZU").toUpperCase()}</span>
            <i />
            <span>{mythic ? liveVariantB ? "MYTHIC PRESENCE B · LIVE GAZE" : "MYTHIC PRESENCE A" : muscular ? "MUSCULAR PRESENCE" : "NEURAL PRESENCE"}</span>
          </div>
        </>
      )}
    </MorphablePresenceStage>
  )
}

export default HumanoidPresence
