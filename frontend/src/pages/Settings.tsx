import { useEffect, useState } from "react"
import { Navigate, useLocation, useParams } from "react-router-dom"
import { api, getPrivateKey, setPrivateKey } from "../api"
import { usePresentationSettings } from "../presence/presentationSettings"
import { AdvancedSettingsPane } from "../settings/AdvancedSettingsPane"
import { AppearanceSettingsPane } from "../settings/AppearanceSettingsPane"
import { IntegrationsSettingsPane } from "../settings/IntegrationsSettingsPane"
import { ModelsSettingsPane } from "../settings/ModelsSettingsPane"
import { NetworkSettingsPane } from "../settings/NetworkSettingsPane"
import { SettingsNav } from "../settings/SettingsNav"
import {
  DEFAULT_SETTINGS_SUBMENU,
  isSettingsSubmenu,
  persistLastSettingsSubmenu,
  readLastSettingsSubmenu,
  resolveSettingsSubmenuFromLocation,
  settingsSubmenuPath,
  SETTINGS_SUBMENU_LABELS,
  type SettingsSubmenu,
} from "../settings/settingsSubmenus"
import { VoiceSettingsPane } from "../settings/VoiceSettingsPane"
import "../settings/settings.css"

export function SettingsPage() {
  const { submenu: routeSubmenu } = useParams<{ submenu?: string }>()
  const location = useLocation()
  const presentation = usePresentationSettings()

  const [settings, setSettings] = useState<Record<string, unknown> | null>(null)
  const [localKey, setLocalKey] = useState<string>(getPrivateKey())
  const [showKey, setShowKey] = useState(false)
  const [authStatus, setAuthStatus] = useState<Record<string, unknown> | null>(null)
  const [queueStatus, setQueueStatus] = useState<Record<string, unknown> | null>(null)
  const [inferenceKeyDraft, setInferenceKeyDraft] = useState("")
  const [msg, setMsg] = useState("")

  const activeSubmenu: SettingsSubmenu | null = isSettingsSubmenu(routeSubmenu) ? routeSubmenu : null

  useEffect(() => {
    if (activeSubmenu) persistLastSettingsSubmenu(activeSubmenu)
  }, [activeSubmenu])

  async function loadData() {
    const [s, a, q] = await Promise.all([
      api<Record<string, unknown>>("/api/settings").catch(() => null),
      api<Record<string, unknown>>("/api/auth/status").catch(() => null),
      api<Record<string, unknown>>("/api/queue").catch(() => null),
    ])
    if (s) {
      const inference = s.inference && typeof s.inference === "object" ? { ...s.inference } : s.inference
      if (inference && typeof inference === "object" && "api_key" in inference) {
        delete (inference as Record<string, unknown>).api_key
      }
      setSettings({ ...s, inference })
    }
    if (a) setAuthStatus(a)
    if (q) setQueueStatus(q)
  }

  useEffect(() => {
    void loadData()
  }, [])

  async function save(patch: Record<string, unknown>) {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) })
    await loadData()
  }

  async function generateKey() {
    const res = await api<{ private_key?: string }>("/api/auth/generate-key", { method: "POST" })
    if (res.private_key) {
      setLocalKey(res.private_key)
      setPrivateKey(res.private_key)
      setMsg("New private key generated and saved to server and browser.")
      await loadData()
    }
  }

  function saveLocalKeyOnly() {
    setPrivateKey(localKey)
    setMsg("Private key saved to this browser session.")
  }

  if (location.pathname === "/settings" && !routeSubmenu) {
    const alias = resolveSettingsSubmenuFromLocation(undefined, location.search, location.hash)
    return <Navigate to={settingsSubmenuPath(alias ?? readLastSettingsSubmenu())} replace />
  }

  if (!activeSubmenu) {
    return <Navigate to={settingsSubmenuPath(DEFAULT_SETTINGS_SUBMENU)} replace />
  }

  const needsApiSettings = activeSubmenu === "models" || activeSubmenu === "network" || activeSubmenu === "advanced"

  function renderPane() {
    switch (activeSubmenu) {
      case "voice":
        return <VoiceSettingsPane />
      case "appearance":
        return (
          <div className="card grid settings-pane-card">
            <h2>Appearance</h2>
            <p className="lede" style={{ margin: "0 0 12px" }}>
              Theme, shell, presence, rendering, attention, and motion — shared with the Daybreak HUD.
            </p>
            <AppearanceSettingsPane settings={presentation} />
          </div>
        )
      case "integrations":
        return <IntegrationsSettingsPane />
      case "models":
        if (!settings) return <div className="card settings-pane-card">Loading settings…</div>
        return (
          <ModelsSettingsPane
            settings={settings}
            inferenceKeyDraft={inferenceKeyDraft}
            setInferenceKeyDraft={setInferenceKeyDraft}
            setSettings={setSettings}
            save={save}
            setMsg={setMsg}
          />
        )
      case "network":
        if (!settings) return <div className="card settings-pane-card">Loading settings…</div>
        return (
          <NetworkSettingsPane
            settings={settings}
            localKey={localKey}
            setLocalKey={setLocalKey}
            showKey={showKey}
            setShowKey={setShowKey}
            authStatus={authStatus}
            save={save}
            saveLocalKeyOnly={saveLocalKeyOnly}
            generateKey={generateKey}
            setMsg={setMsg}
          />
        )
      case "advanced":
        if (!settings) return <div className="card settings-pane-card">Loading settings…</div>
        return <AdvancedSettingsPane settings={settings} queueStatus={queueStatus} save={save} />
      default:
        return null
    }
  }

  return (
    <div className="settings-page">
      <h1>Settings</h1>
      <p className="lede">
        Preferences for this PC. To stop Jarvis entirely, use <strong>Stop</strong> on the Windows tray —
        it is not in this window. License and advanced execution options are under <strong>Advanced</strong>.
      </p>

      {msg && (
        <div className="card settings-flash" style={{ borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}

      <div className="settings-shell">
        <SettingsNav active={activeSubmenu} />
        <div className="settings-content" aria-labelledby="settings-pane-title">
          <h2 id="settings-pane-title" className="settings-pane-heading">
            {SETTINGS_SUBMENU_LABELS[activeSubmenu]}
          </h2>
          {needsApiSettings && !settings ? (
            <div className="card settings-pane-card">Loading…</div>
          ) : (
            renderPane()
          )}
        </div>
      </div>
    </div>
  )
}
