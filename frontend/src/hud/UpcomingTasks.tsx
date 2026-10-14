import { useEffect, useState } from "react"
import { api } from "../api"

type Item = { id: string; title: string; status: string; kind: string }
type Queue = { items: Item[]; revision: number; away_mode: boolean; can_undo: boolean }
export function UpcomingTasks() {
  const [open, setOpen] = useState(false)
  const [queue, setQueue] = useState<Queue | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [dragged, setDragged] = useState("")
  const pending = queue?.items.filter(item => item.status === "queued") || []
  async function refresh() {
    try { setQueue(await api<Queue>("/api/self-dev/scheduler/upcoming")) }
    catch (error) { setError(error instanceof Error ? error.message : "Could not load upcoming work") }
  }
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 3000); return () => window.clearInterval(timer) }, [])
  async function order(ids: string[], undo = false) {
    if (!queue || busy) return
    setBusy(true); setError("")
    try { await api("/api/self-dev/scheduler/order", { method: "POST", body: JSON.stringify({ ids, revision: queue.revision, undo }) }); await refresh() }
    catch (error) { setError(error instanceof Error ? error.message : "Queue changed; refresh and try again"); await refresh() }
    finally { setBusy(false) }
  }
  function move(id: string, offset: number) {
    const ids = pending.map(item => item.id); const index = ids.indexOf(id); const target = index + offset
    if (index < 0 || target < 0 || target >= ids.length) return
    ids.splice(index, 1); ids.splice(target, 0, id); void order(ids)
  }
  return <div>
    <button className="hud-icon-btn" type="button" aria-label="Upcoming tasks" aria-expanded={open} onClick={() => setOpen(!open)}>☷ {pending.length || ""}</button>
    {open && <aside aria-label="Upcoming tasks" style={{ position: "absolute", right: 16, top: 60, zIndex: 70, width: "min(440px,90vw)", maxHeight: "75vh", overflow: "auto", background: "#081016", border: "1px solid #344854", borderRadius: 14, padding: 16 }}>
      <h2>Upcoming tasks</h2>
      <label><input type="checkbox" checked={queue?.away_mode || false} disabled={busy} onChange={event => {
        setBusy(true); void api("/api/self-dev/scheduler/away", { method: "POST", body: JSON.stringify({ enabled: event.target.checked }) }).then(refresh).catch(error => setError(String(error))).finally(() => setBusy(false))
      }} />Away Mode — develop ANZU</label>
      <p>ANZU will work through the backlog, merge verified improvements into development, and prepare builds.</p>
      {error && <p role="alert">{error}</p>}
      {!queue?.items.length && <p>No upcoming work.</p>}
      <ol>{queue?.items.map(item => <li key={item.id} draggable={item.status === "queued" && !busy} onDragStart={() => setDragged(item.id)} onDragOver={event => event.preventDefault()} onDrop={() => {
        if (busy || !dragged || item.status !== "queued") return
        const ids = pending.map(row => row.id).filter(id => id !== dragged); ids.splice(ids.indexOf(item.id), 0, dragged); setDragged(""); void order(ids)
      }}>
        <strong>{item.title}</strong><p>{item.status}</p>
        {item.status === "queued" && <span><button type="button" disabled={busy || pending[0]?.id === item.id} aria-label={`Move ${item.title} up`} onClick={() => move(item.id, -1)}>↑</button> <button type="button" disabled={busy || pending.at(-1)?.id === item.id} aria-label={`Move ${item.title} down`} onClick={() => move(item.id, 1)}>↓</button></span>}
      </li>)}</ol>
      <button type="button" disabled={busy || !queue?.can_undo} onClick={() => void order([], true)}>Undo ordering</button>
      <button type="button" onClick={() => setOpen(false)}>Close</button>
    </aside>}
  </div>
}
