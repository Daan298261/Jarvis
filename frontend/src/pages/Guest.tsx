import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import {
  approveGuestTask,
  clearGuestSession,
  getGuestDecision,
  getGuestSession,
  getGuestTask,
  getGuestTaskEvents,
  getGuestToken,
  setGuestToken,
  startGuestSession,
  type GuestDecision,
  type GuestEffectivePermissions,
  type GuestGrant,
  type GuestSession,
  type GuestTask,
  type GuestTaskEvents,
} from "../api"
import { EffectivePermissionsView } from "./guestPermissions"

type SelectedResource =
  | { kind: "task"; id: string; actions: string[] }
  | { kind: "decision_inbox"; id: string; actions: string[] }
  | { kind: "other"; type: string; id: string; actions: string[] }

function tokenFromSearch(search: string): string {
  const params = new URLSearchParams(search)
  return (params.get("guest_token") || params.get("token") || "").trim()
}

function grantKey(grant: GuestGrant, index: number): string {
  return `${grant.resource_type}:${grant.resource_id}:${index}`
}

function statusBadge(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "completed") return "completed"
  if (normalized === "failed" || normalized === "cancelled") return "failed"
  if (normalized === "running" || normalized === "waiting") return "running"
  return "queued"
}

export function GuestPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [tokenInput, setTokenInput] = useState("")
  const [session, setSession] = useState<GuestSession | null>(null)
  const [selected, setSelected] = useState<SelectedResource | null>(null)
  const [task, setTask] = useState<GuestTask | null>(null)
  const [events, setEvents] = useState<GuestTaskEvents | null>(null)
  const [decision, setDecision] = useState<GuestDecision | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const bootstrapped = useRef(false)

  const grants = session?.effective_permissions?.grants

  const selectedGrant = useMemo(() => {
    if (!selected || !grants) return null
    return grants.find((grant) => {
      if (selected.kind === "other") {
        return grant.resource_type === selected.type && grant.resource_id === selected.id
      }
      if (selected.kind === "task") return grant.resource_type === "task" && grant.resource_id === selected.id
      return grant.resource_type === "decision_inbox" && grant.resource_id === selected.id
    }) || null
  }, [grants, selected])

  const connect = useCallback(async (token: string) => {
    const trimmed = token.trim()
    if (!trimmed) {
      setError("Paste a guest portal token to continue.")
      return
    }
    setBusy(true)
    setError("")
    try {
      setGuestToken(trimmed)
      const next = await startGuestSession()
      setSession(next)
      setTokenInput("")
      if (location.search) navigate("/guest", { replace: true })
    } catch (err: unknown) {
      clearGuestSession()
      setSession(null)
      setError(err instanceof Error ? err.message : "Could not start guest session.")
    } finally {
      setBusy(false)
    }
  }, [location.search, navigate])

  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true
    const fromUrl = tokenFromSearch(location.search)
    const stored = getGuestToken()
    if (fromUrl) {
      void connect(fromUrl)
      return
    }
    if (!stored) return
    setBusy(true)
    getGuestSession()
      .then(setSession)
      .catch(() => {
        startGuestSession()
          .then(setSession)
          .catch((err: unknown) => {
            clearGuestSession()
            setError(err instanceof Error ? err.message : "Guest session expired.")
          })
      })
      .finally(() => setBusy(false))
  }, [connect, location.search])

  useEffect(() => {
    if (!selected) {
      setTask(null)
      setEvents(null)
      setDecision(null)
      return
    }
    if (selected.kind === "other") {
      setTask(null)
      setEvents(null)
      setDecision(null)
      return
    }
    let cancelled = false
    async function load() {
      setBusy(true)
      setError("")
      try {
        if (selected?.kind === "task") {
          const canRead = selected.actions.includes("read")
          const canQuery = selected.actions.includes("query")
          const nextTask = canRead ? await getGuestTask(selected.id) : null
          const nextEvents = canQuery ? await getGuestTaskEvents(selected.id) : null
          if (!cancelled) {
            setTask(nextTask)
            setEvents(nextEvents)
            setDecision(null)
          }
        } else if (selected?.kind === "decision_inbox") {
          const next = selected.actions.includes("read") ? await getGuestDecision(selected.id) : null
          if (!cancelled) {
            setDecision(next)
            setTask(null)
            setEvents(null)
          }
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setTask(null)
          setEvents(null)
          setDecision(null)
          setError(err instanceof Error ? err.message : "This resource is not available to this portal.")
        }
      } finally {
        if (!cancelled) setBusy(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [selected])

  function openGrant(grant: GuestGrant) {
    const actions = grant.actions || []
    if (grant.resource_type === "task") {
      setSelected({ kind: "task", id: grant.resource_id, actions })
      return
    }
    if (grant.resource_type === "decision_inbox") {
      setSelected({ kind: "decision_inbox", id: grant.resource_id, actions })
      return
    }
    setSelected({ kind: "other", type: grant.resource_type, id: grant.resource_id, actions })
  }

  async function onApprove() {
    if (!selected || selected.kind !== "task") return
    setBusy(true)
    setError("")
    try {
      const next = await approveGuestTask(selected.id)
      setTask(next)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Approve failed.")
    } finally {
      setBusy(false)
    }
  }

  function disconnect() {
    clearGuestSession()
    setSession(null)
    setSelected(null)
    setTask(null)
    setEvents(null)
    setDecision(null)
    setError("")
  }

  const permissions: GuestEffectivePermissions | undefined = session?.effective_permissions

  return (
    <div className="guest-shell">
      <header className="guest-bar">
        <div>
          <strong>JARVIS</strong>
          <div className="guest-bar-meta">Guest portal — granted resources only</div>
        </div>
        {session && (
          <button className="btn secondary" type="button" onClick={disconnect}>
            Sign out
          </button>
        )}
      </header>
      <main className="guest-main">
        {!session && (
          <div className="card grid">
            <h1>Enter guest access</h1>
            <p className="lede">
              This is not the owner portal. A guest token only unlocks the specific task or decision
              you were granted. Files, tools, agents, and settings stay hidden.
            </p>
            <label>
              Guest token
              <input
                type="password"
                value={tokenInput}
                placeholder="jarvis_gp_…"
                onChange={(event) => setTokenInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void connect(tokenInput)
                }}
              />
            </label>
            <div className="row">
              <button className="btn" type="button" disabled={busy || !tokenInput.trim()} onClick={() => void connect(tokenInput)}>
                Open portal
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="card" style={{ marginTop: session ? 0 : 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
            {error}
          </div>
        )}

        {session && permissions && (
          <>
            <h1>Hello, {session.guest_label}</h1>
            <p className="lede">
              You can only open the resources listed here. There is no path to other agents, files,
              tools, or settings.
            </p>
            <EffectivePermissionsView perms={permissions} title="Your access" />

            <div className="card" style={{ marginTop: 16 }}>
              <h2>Granted resources</h2>
              {(grants || []).length === 0 ? (
                <p className="lede">This portal grants nothing.</p>
              ) : (
                <div className="grant-pick">
                  {(grants || []).map((grant, index) => (
                    <button
                      key={grantKey(grant, index)}
                      type="button"
                      className={`template-card${
                        selected &&
                        ((selected.kind === "task" && grant.resource_type === "task" && selected.id === grant.resource_id) ||
                          (selected.kind === "decision_inbox" &&
                            grant.resource_type === "decision_inbox" &&
                            selected.id === grant.resource_id) ||
                          (selected.kind === "other" &&
                            grant.resource_type === selected.type &&
                            selected.id === grant.resource_id))
                          ? " selected"
                          : ""
                      }`}
                      onClick={() => openGrant(grant)}
                    >
                      <strong>{grant.resource_type}</strong>
                      <p>{grant.resource_id}</p>
                      <div className="runtime-tags">
                        {(grant.actions || []).map((action) => (
                          <span key={action}>{action}</span>
                        ))}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selected?.kind === "other" && (
              <div className="card" style={{ marginTop: 16 }}>
                <h2>
                  {selected.type}: {selected.id}
                </h2>
                <p className="lede">
                  This portal grants {(selectedGrant?.actions || []).join(", ") || "no actions"} on that
                  resource. There is no guest view for agents or projects — only granted tasks and
                  decision items can be opened here.
                </p>
              </div>
            )}

            {selected?.kind === "task" && (
              <div className="card" style={{ marginTop: 16 }}>
                <div className="chat-head-title">
                  <h2 style={{ margin: 0 }}>{task?.title || selected.id}</h2>
                  {task && <span className={`badge ${statusBadge(task.status)}`}>{task.status}</span>}
                </div>
                {!selected.actions.includes("read") && (
                  <p className="lede">Read is not granted. You can only take allowed actions.</p>
                )}
                {task && (
                  <>
                    <div className="kv" style={{ marginTop: 12 }}>
                      <b>Stage</b><span>{task.stage || "—"}</span>
                      <b>Waiting</b><span>{task.waiting_for_confirmation ? "Yes" : "No"}</span>
                    </div>
                    {task.result && (
                      <p className="report" style={{ marginTop: 12 }}>{task.result}</p>
                    )}
                    {task.error && (
                      <p className="lede" style={{ color: "var(--bad)" }}>{task.error}</p>
                    )}
                  </>
                )}
                {selected.actions.includes("approve") && (
                  <div className="row" style={{ marginTop: 12 }}>
                    <button
                      className="btn"
                      type="button"
                      disabled={busy || (task != null && !task.waiting_for_confirmation)}
                      onClick={() => void onApprove()}
                    >
                      Approve
                    </button>
                  </div>
                )}
                {events && (
                  <div className="timeline" style={{ marginTop: 16 }}>
                    {events.events.length === 0 && <p className="lede">No events yet.</p>}
                    {events.events.map((event, index) => (
                      <div className="t-item" key={`${event.created_at}-${index}`}>
                        <div className="rail" />
                        <div>
                          <strong>{event.title || event.kind}</strong>
                          {event.detail && <p>{event.detail}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {selected?.kind === "decision_inbox" && (
              <div className="card" style={{ marginTop: 16 }}>
                <h2>Decision {selected.id}</h2>
                {decision ? (
                  <>
                    <span className={`badge ${decision.status === "unavailable" ? "queued" : "ok"}`}>
                      {decision.status}
                    </span>
                    <p className="lede">{decision.detail}</p>
                  </>
                ) : (
                  <p className="lede">
                    {selected.actions.includes("read")
                      ? "Loading…"
                      : "Read is not granted for this decision."}
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
