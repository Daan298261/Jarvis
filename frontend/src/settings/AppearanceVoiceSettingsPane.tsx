import { useEffect } from "react"
import { useLocation } from "react-router-dom"
import type { PresentationSettings } from "../presence/presenceTypes"
import { AppearanceSettingsPane } from "./AppearanceSettingsPane"
import { VoiceSettingsPane } from "./VoiceSettingsPane"

type AppearanceVoiceSettingsPaneProps = {
  settings: PresentationSettings
}

export function AppearanceVoiceSettingsPane({ settings }: AppearanceVoiceSettingsPaneProps) {
  const location = useLocation()

  useEffect(() => {
    const focus = location.hash.replace(/^#/, "").trim()
    if (focus !== "voice" && focus !== "appearance") return
    const target = document.getElementById(`settings-${focus}`)
    target?.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [location.hash, location.pathname])

  return (
    <>
      <div id="settings-appearance" className="card grid settings-pane-card">
        <h2>Appearance</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Theme, shell, presence, rendering, attention, and motion — shared with the Daybreak HUD.
        </p>
        <AppearanceSettingsPane settings={settings} />
      </div>
      <section id="settings-voice" className="settings-section" aria-labelledby="settings-voice-heading">
        <h2 id="settings-voice-heading">Voice &amp; Speech</h2>
        <VoiceSettingsPane />
      </section>
    </>
  )
}
