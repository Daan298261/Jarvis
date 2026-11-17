import { useCallback, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../api"
import "./upcoming-tasks.css"

type Upcoming = {
  id: string; title: string; kind: string; status: string; priority: number
  depends: string[]; pinned: boolean; reason: string; next: boolean
}
type HistoryEntry = { id: string; actor: "owner" | "anzu"; reason: string; at: number; order: string[] }
type OwnerTask = { id: string; title: string; status: string; stage: string }
type QueueView = {
  revision: number; automatic: boolean; upcoming: Upcoming[]; next_eligible: string
  active: { id: string; title: string; stage: string } | null
  history: HistoryEntry[]; owner_tasks: OwnerTask[]
  status: { phase: string; detail: string }
}

const endpoint = "/api/self-dev/scheduler/queue"

/** RFC-0211 primary-shell list icon: active task plus the shared, reorderable upcoming queue. */
export function UpcomingTasks({ variant }: { variant: "hud" | "classic" }) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<QueueView | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  const refresh = useCallback(async () => {
    try {
      setView(await api<QueueView>(endpoint))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  // Every client polls the same persisted queue, so changes appear everywhere within seconds.
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), open ? 3000 : 15000)
    return () => window.clearInterval(timer)
  }, [refresh, open])

  useEffect(() => {
    if (!open) return
    panelRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); buttonRef.current?.focus() }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  async function mutate(path: string, body: unknown) {
    setBusy(true); setError("")
    try {
      await api(endpoint + path, { method: "POST", body: JSON.stringify(body) })
    } catch (e) {
      // A stale revision means another client changed the order first: the refresh below shows theirs.
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      await refresh()
      setBusy(false)
    }
  }

  const move = (id: string, to: number) => view && mutate("/move", { item_id: id, to, expected_revision: view.revision })
  const count = (view?.upcoming.length || 0) + (view?.owner_tasks.length || 0) + (view?.active ? 1 : 0)
  const latest = view?.history.at(-1)

  return <div className={`upcoming-tasks upcoming-tasks-${variant}`}>
    <button ref={buttonRef} type="button" className="upcoming-tasks-icon" aria-label={`Upcoming tasks (${count} queued)`}
      aria-expanded={open} aria-controls="upcoming-tasks-panel" title="Upcoming tasks" onClick={() => setOpen(value => !value)}>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18"><path d="M6 4h10M6 9h10M6 14h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /><circle cx="2.5" cy="4" r="1.2" fill="currentColor" /><circle cx="2.5" cy="9" r="1.2" fill="currentColor" /><circle cx="2.5" cy="14" r="1.2" fill="currentColor" /></svg>
      {count > 0 && <span className="upcoming-tasks-count">{count}</span>}
    </button>
    {open && <div id="upcoming-tasks-panel" ref={panelRef} tabIndex={-1} role="dialog" aria-label="Upcoming tasks" className="upcoming-tasks-panel">
      <header><strong>Upcoming tasks</strong><button type="button" aria-label="Close upcoming tasks" onClick={() => setOpen(false)}>×</button></header>
      {view && <p className="upcoming-tasks-status" role="status">Development: {view.status.phase}{view.status.detail ? ` · ${view.status.detail}` : ""}</p>}
      {error && <p role="alert" className="upcoming-tasks-error">{error}</p>}
      {!view && !error && <p>Loading…</p>}
      {view && <>
        <section aria-label="Active">
          <h3>Now</h3>
          {!view.active && !view.owner_tasks.length && <p className="upcoming-tasks-muted">Nothing running.</p>}
          {view.active && <div className="upcoming-tasks-row active"><span className="upcoming-tasks-kind">Develop</span><span>{view.active.title}</span><em>{view.active.stage.replace(/_/g, " ")}</em></div>}
          {view.owner_tasks.map(task => <div key={task.id} className="upcoming-tasks-row active"><span className="upcoming-tasks-kind">Task</span><Link to={`/tasks/${task.id}`} onClick={() => setOpen(false)}>{task.title}</Link><em>{task.stage || task.status}</em></div>)}
        </section>
        <section aria-label="Upcoming">
          <h3>Up next</h3>
          {!view.upcoming.length && <p className="upcoming-tasks-muted">The upcoming list is empty. Scan the backlog in <Link to="/self-development" onClick={() => setOpen(false)}>Self-development</Link>.</p>}
          <ol className="upcoming-tasks-list">
            {view.upcoming.map((task, index) => <li key={task.id} draggable={!busy}
              className={`upcoming-tasks-row${task.next ? " next" : ""}${dragging === task.id ? " dragging" : ""}`}
              onDragStart={event => { setDragging(task.id); event.dataTransfer.effectAllowed = "move" }}
              onDragEnd={() => setDragging(null)}
              onDragOver={event => { if (dragging) event.preventDefault() }}
              onDrop={event => { event.preventDefault(); if (dragging && dragging !== task.id) void move(dragging, index); setDragging(null) }}>
              <span className="upcoming-tasks-grip" aria-hidden="true">⋮⋮</span>
              <span className="upcoming-tasks-title">
                <span>{task.title}</span>
                <small>{task.next ? "Runs next" : task.reason || "Ready"}{task.pinned ? " · your order" : ""} · P{task.priority}</small>
              </span>
              <span className="upcoming-tasks-actions">
                <button type="button" disabled={busy || index === 0} aria-label={`Move ${task.title} up`} onClick={() => void move(task.id, index - 1)}>▲</button>
                <button type="button" disabled={busy || index === view.upcoming.length - 1} aria-label={`Move ${task.title} down`} onClick={() => void move(task.id, index + 1)}>▼</button>
                {task.pinned && <button type="button" disabled={busy} aria-label={`Let ANZU plan ${task.title}`} onClick={() => void mutate("/release", { item_id: task.id, expected_revision: view.revision })}>Unpin</button>}
              </span>
            </li>)}
          </ol>
        </section>
        {latest && <section aria-label="Last change" className="upcoming-tasks-history">
          <p>{latest.actor === "owner" ? "You" : "ANZU"} reordered: {latest.reason} · {new Date(latest.at * 1000).toLocaleTimeString()}</p>
          <button type="button" disabled={busy} onClick={() => void mutate("/undo", { history_id: latest.id, expected_revision: view.revision })}>Undo</button>
        </section>}
        <p className="upcoming-tasks-muted">Reordering never interrupts the running task or skips a dependency, reservation or safety check.</p>
      </>}
    </div>}
  </div>
}
