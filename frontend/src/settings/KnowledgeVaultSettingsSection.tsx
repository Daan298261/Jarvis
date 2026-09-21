import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  bindVault,
  fetchVaultHealth,
  fetchVaultStatus,
  unbindVault,
  type VaultHealthResponse,
  type VaultPublicStatus,
} from "../vault/vaultApi"

export function KnowledgeVaultSettingsSection() {
  const [status, setStatus] = useState<VaultPublicStatus | null>(null)
  const [health, setHealth] = useState<VaultHealthResponse | null>(null)
  const [vaultPath, setVaultPath] = useState("")
  const [initLayout, setInitLayout] = useState(true)
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)

  async function refresh() {
    const [st, h] = await Promise.all([fetchVaultStatus(), fetchVaultHealth()])
    setStatus(st)
    setHealth(h)
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function handleBind(event: React.FormEvent) {
    event.preventDefault()
    const path = vaultPath.trim()
    if (!path) return
    setBusy(true)
    setMessage("")
    try {
      await bindVault(path, initLayout)
      setMessage("Vault bound. Jarvis will watch and index Markdown.")
      await refresh()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Bind failed")
    } finally {
      setBusy(false)
    }
  }

  async function handleUnbind() {
    setBusy(true)
    setMessage("")
    try {
      await unbindVault()
      setVaultPath("")
      setMessage("Vault unbound.")
      await refresh()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unbind failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="knowledge-vault" className="settings-section card grid">
      <h3>Linked Obsidian vault (RFC-0107)</h3>
      <p className="lede">
        A Jarvis-managed vault under this PC’s data folder is bound on first start. Bind a different
        local folder here if you already use Obsidian. Edit notes in the{" "}
        <Link to="/obsidian">Obsidian pane</Link> — the real Obsidian UI inside Jarvis Desktop.
      </p>
      {status && (
        <p className="muted">
          Status: {status.bound ? "bound" : "not bound"}
          {status.bound && status.jarvis_managed_layout ? " · Jarvis-managed default layout" : ""}
          {status.bound && status.note_count > 0 ? ` · ${status.note_count} notes indexed` : ""}
          {status.bound && health?.missing_router ? " · router.md missing" : ""}
          {health && health.broken_links.length > 0
            ? ` · ${health.broken_links.length} broken wiki-link(s)`
            : ""}
        </p>
      )}
      <form className="grid" onSubmit={(e) => void handleBind(e)}>
        <label>
          Vault folder path (this machine)
          <input
            type="text"
            value={vaultPath}
            onChange={(e) => setVaultPath(e.target.value)}
            placeholder="C:\Users\you\Documents\MyVault"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <label className="row" style={{ alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            checked={initLayout}
            onChange={(e) => setInitLayout(e.target.checked)}
          />
          Initialize Jarvis-managed folders (_Config, Projects, …) — on by default for a new vault
        </label>
        <div className="row">
          <button type="submit" className="btn" disabled={busy || !vaultPath.trim()}>
            {busy ? "Working…" : "Bind vault"}
          </button>
          <button
            type="button"
            className="btn secondary"
            disabled={busy || !status?.bound}
            onClick={() => void handleUnbind()}
          >
            Unbind
          </button>
          <Link className="btn secondary" to="/obsidian">
            Open Obsidian pane
          </Link>
        </div>
      </form>
      {message && <p className="muted">{message}</p>}
    </section>
  )
}
