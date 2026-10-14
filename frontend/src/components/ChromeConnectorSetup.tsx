import { useEffect, useState } from "react"
import { api } from "../api"

type Connector = { registered: boolean; connected?: boolean; shared_url?: string; install_dir: string; instructions: string }

export function ChromeConnectorSetup() {
  const [status, setStatus] = useState<Connector | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  async function refresh() {
    try { setStatus(await api<Connector>("/api/tools/chrome-connector")); setError("") }
    catch (failure) { setError(String(failure)) }
  }
  useEffect(() => { void refresh() }, [])
  async function prepare() {
    setBusy(true)
    try { setStatus(await api<Connector>("/api/tools/chrome-connector/setup", { method: "POST" })); setError("") }
    catch (failure) { setError(String(failure)) }
    finally { setBusy(false) }
  }
  async function download() {
    setBusy(true)
    try {
      const file = await api<{ filename: string; zip_base64: string }>("/api/tools/chrome-connector/package")
      const bytes = Uint8Array.from(atob(file.zip_base64), character => character.charCodeAt(0))
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }))
      const link = document.createElement("a")
      link.href = url; link.download = file.filename; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setError("")
    } catch (failure) { setError(String(failure)) }
    finally { setBusy(false) }
  }
  return <div className="card" style={{ marginTop: 16 }}>
    <h2>Chrome website connector</h2>
    <p className="lede">Let ANZU read and operate a website in your signed-in Chrome session. You choose which tab to share. Embedded websites need their own site access.</p>
    <p role="status">{status?.connected ? `Connected${status.shared_url ? ` — ${status.shared_url}` : ""}` : status?.registered ? "Prepared — load the extension in Chrome, then share a tab." : "Prepare the connector to get started."}</p>
    <div className="row">
      <button className="btn" disabled={busy} onClick={() => { void prepare() }}>{busy ? "Working…" : "Prepare Chrome connector"}</button>
      <button className="btn secondary" disabled={busy} onClick={() => { void download() }}>Download extension</button>
      <button className="btn secondary" disabled={busy} onClick={() => { void refresh() }}>Refresh status</button>
    </div>
    {status?.registered && <p className="lede">{status.instructions}<br /><code>{status.install_dir}</code></p>}
    {error && <p role="alert">{error}</p>}
  </div>
}
