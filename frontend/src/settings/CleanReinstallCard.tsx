import { useCallback, useEffect, useState } from "react"
import { api } from "../api"

type CleanReinstallPreview = {
  install_root: string
  owned_roots: string[]
  license_issuer_preserved: string
  setup_exe: string
  helper_script: string
  force_stop_script: string
  windows_only: boolean
  safe_install_dir: boolean
}

export function CleanReinstallCard() {
  const [preview, setPreview] = useState<CleanReinstallPreview | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")

  const load = useCallback(async () => {
    try {
      const data = await api<CleanReinstallPreview>("/api/installer/clean-reinstall/preview")
      setPreview(data)
      setError("")
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not load clean reinstall preview.")
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function onStart() {
    if (!preview) return
    const list = preview.owned_roots.join("\n")
    const first = window.confirm(
      `Clean Install / Reinstall permanently removes Jarvis application files, models, chats, logs, and other Jarvis-owned data on this PC, then runs Setup again.\n\nOwned roots:\n${list}\n\nThis cannot be undone. Continue?`,
    )
    if (!first) return
    const second = window.confirm(
      "Final confirmation: permanently delete the listed Jarvis-owned paths and reinstall?",
    )
    if (!second) return
    setBusy(true)
    setMsg("")
    setError("")
    try {
      const result = await api<{ ok: boolean; message?: string; log_hint?: string }>(
        "/api/installer/clean-reinstall/start",
        { method: "POST", body: JSON.stringify({ confirm: true }) },
      )
      setMsg(result.message || "Clean reinstall helper started.")
      if (result.log_hint) {
        setMsg((m) => `${m} Log: ${result.log_hint}`)
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Clean reinstall could not start.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card grid settings-pane-card" style={{ borderColor: "var(--bad)" }}>
      <h2>Clean Install / Reinstall</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Permanently removes Jarvis-owned application files, models, chats, logs, and local data on this PC,
        then runs Setup again. Vendor license-issuer material is preserved. Owner Documents, Desktop, git
        projects, and allowed directories are never wiped.
      </p>
      {preview && (
        <ul style={{ margin: "0 0 12px", paddingLeft: 20 }}>
          {preview.owned_roots.map((root) => (
            <li key={root}><code>{root}</code></li>
          ))}
        </ul>
      )}
      {!preview?.windows_only && (
        <p className="lede" style={{ color: "var(--bad)" }}>
          This action is only available on Windows with a local Jarvis install.
        </p>
      )}
      {error && <p className="lede" style={{ color: "var(--bad)" }}>{error}</p>}
      {msg && <p className="lede">{msg}</p>}
      <div className="row">
        <button className="btn danger" type="button" disabled={busy || !preview?.safe_install_dir} onClick={onStart}>
          Clean Install / Reinstall
        </button>
      </div>
    </div>
  )
}
