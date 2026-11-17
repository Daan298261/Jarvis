import { useEffect, useRef, useState } from "react"
import { api } from "../api"
import { isUnavailableError, pruneUnavailableServers, unansweredOfferIds } from "./runningModelsUi"

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
  const revision = useRef(0)
  const working = useRef(false)
  useEffect(() => {
    let mounted = true
    const controller = new AbortController()
    let timer: number | undefined
    const refresh = async () => {
      const started = revision.current
      try {
        if (!working.current) {
          const value = await api<Inventory>("/api/model/running", { signal: controller.signal })
          if (mounted && started === revision.current && !working.current) setInventory(value)
        }
      } catch { /* The HUD health rail reports core availability. */ }
      if (mounted) timer = window.setTimeout(refresh, 5000)
    }
    void refresh()
    return () => { mounted = false; controller.abort(); window.clearTimeout(timer) }
  }, [])

  async function scan() {
    if (working.current) return
    working.current = true
    revision.current += 1
    setBusy(true)
    setError("")
    try { setInventory(await api<Inventory>("/api/model/running/scan", { method: "POST" })) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { working.current = false; setBusy(false) }
  }

  function applyUnavailable(rowId: string, message: string) {
    if (!isUnavailableError(message)) {
      setError(message)
      return
    }
    setInventory((prev) => {
      if (!prev) return prev
      return { ...prev, servers: pruneUnavailableServers(prev.servers, rowId, message), error: "" }
    })
    setError("")
  }

  async function choose(row: Server, action: "use" | "leave" | "stop" | "replace") {
    const confirm = action === "stop" || action === "replace"
    if (confirm && !window.confirm(`Stop ${row.model}? Other apps may be using this server.${action === "replace" ? " ANZU will then load its own model." : ""}`)) return
    if (working.current) return
    working.current = true
    revision.current += 1
    setBusy(true)
    setError("")
    try {
      setInventory(await api<Inventory>(`/api/model/running/${row.id}/choice`, {
        method: "POST", body: JSON.stringify({ action, confirm }),
      }))
    } catch (err) {
      applyUnavailable(row.id, err instanceof Error ? err.message : String(err))
    } finally { working.current = false; setBusy(false) }
  }

  async function dismissCard() {
    const ids = unansweredOfferIds(inventory?.servers ?? [])
    if (!ids.length) {
      setInventory((prev) => prev ? { ...prev, servers: prev.servers.filter((row) => !!row.choice) } : prev)
      setError("")
      return
    }
    if (working.current) return
    working.current = true
    revision.current += 1
    setBusy(true)
    setError("")
    try {
      let latest: Inventory | null = inventory
      for (const id of ids) {
        try {
          latest = await api<Inventory>(`/api/model/running/${id}/choice`, {
            method: "POST", body: JSON.stringify({ action: "leave", confirm: false }),
          })
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err)
          if (isUnavailableError(message)) {
            latest = latest
              ? { ...latest, servers: pruneUnavailableServers(latest.servers, id, message), error: "" }
              : latest
            continue
          }
          throw err
        }
      }
      if (latest) setInventory(latest)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { working.current = false; setBusy(false) }
  }

  const rows = inventory?.servers.filter(row => showAll || !row.choice) ?? []
  if (!showAll && !rows.length && !error) return null
  return <section className={showAll ? "card" : "running-model-offer"} aria-label="Available local models">
    <details open={showAll || undefined}>
    <summary>Available local models{!showAll && ` (${rows.length})`}</summary>
    <p>Choose whether ANZU should use another model server or keep its own model.</p>
    {showAll && <button type="button" disabled={busy} onClick={scan}>{busy ? "Working…" : "Scan running servers"}</button>}
    {showAll && inventory?.checked_at && !rows.length && <p>No other local model servers found.</p>}
    {rows.map(row => <div key={row.id} className="running-model-row">
      <span><b>{row.model}</b>{row.active ? " · In use by ANZU" : ""}<small>{row.base_url}</small></span>
      <small>{row.busy ? "Another client is working with this model." : row.busy == null ? "Check that your coding agent has finished before switching or stopping." : "Ready to use."}</small>
      <div className="running-model-actions">
        <button type="button" disabled={busy || row.active || !!row.busy} onClick={() => choose(row, "use")}>Use model</button>
        <button type="button" disabled={busy} onClick={() => choose(row, "leave")}>Leave alone</button>
        <button type="button" disabled={busy || !row.can_stop || !!row.busy} onClick={() => choose(row, "stop")}>Stop model</button>
        <button type="button" disabled={busy || !row.can_stop || !!row.busy} onClick={() => choose(row, "replace")}>Use ANZU’s model</button>
      </div>
      {!row.can_stop && <small>Stop this server in its own app before loading ANZU’s model.</small>}
    </div>)}
    {!showAll && (rows.length > 0 || error) && (
      <div className="running-model-dismiss">
        <button type="button" disabled={busy} onClick={dismissCard}>Dismiss</button>
      </div>
    )}
    {(error || inventory?.error) && <p role="alert">{error || inventory?.error}</p>}
    </details>
  </section>
}
