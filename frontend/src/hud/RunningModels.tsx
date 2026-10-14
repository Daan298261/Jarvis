import { useEffect, useState } from "react"
import { api } from "../api"

type Server = {
  id: string
  model: string
  base_url: string
  choice: string | null
  can_stop: boolean
  active: boolean
  busy?: boolean | null
}
type Inventory = { servers: Server[]; error: string; checked_at: number | null }

export function RunningModels({ showAll = false }: { showAll?: boolean }) {
  const [inventory, setInventory] = useState<Inventory | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  useEffect(() => {
    let mounted = true
    const refresh = () => api<Inventory>("/api/model/running").then(value => {
      if (mounted) setInventory(value)
    }).catch(() => { /* The HUD health rail reports core availability. */ })
    void refresh()
    const timer = window.setInterval(refresh, 5000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [])

  async function scan() {
    setBusy(true)
    setError("")
    try { setInventory(await api<Inventory>("/api/model/running/scan", { method: "POST" })) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function choose(row: Server, action: "use" | "leave" | "stop" | "replace") {
    const confirm = action === "stop" || action === "replace"
    if (confirm && !window.confirm(`Stop ${row.model}? Other apps may be using this server.${action === "replace" ? " ANZU will then load its own model." : ""}`)) return
    setBusy(true)
    setError("")
    try {
      setInventory(await api<Inventory>(`/api/model/running/${row.id}/choice`, {
        method: "POST", body: JSON.stringify({ action, confirm }),
      }))
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  const rows = inventory?.servers.filter(row => showAll || !row.choice) ?? []
  if (!showAll && !rows.length && !error) return null
  return <section className={showAll ? "card" : "running-model-offer"} aria-label="Available local models">
    <strong>Available local models</strong>
    <p>Choose whether ANZU should use another model server or keep its own model.</p>
    {showAll && <button disabled={busy} onClick={scan}>{busy ? "Working…" : "Scan running servers"}</button>}
    {showAll && inventory?.checked_at && !rows.length && <p>No other local model servers found.</p>}
    {rows.map(row => <div key={row.id} className="running-model-row">
      <span><b>{row.model}</b>{row.active ? " · In use by ANZU" : ""}<small>{row.base_url}</small></span>
      <small>{row.busy ? "Another client is working with this model." : row.busy == null ? "Check that your coding agent has finished before switching or stopping." : "Ready to use."}</small>
      <div className="running-model-actions">
        <button disabled={busy || row.active || !!row.busy} onClick={() => choose(row, "use")}>Use model</button>
        <button disabled={busy} onClick={() => choose(row, "leave")}>Leave alone</button>
        <button disabled={busy || !row.can_stop || !!row.busy} onClick={() => choose(row, "stop")}>Stop model</button>
        <button disabled={busy || !row.can_stop || !!row.busy} onClick={() => choose(row, "replace")}>Use ANZU’s model</button>
      </div>
      {!row.can_stop && <small>Stop this server in its own app before loading ANZU’s model.</small>}
    </div>)}
    {(error || inventory?.error) && <p role="alert">{error || inventory?.error}</p>}
  </section>
}
