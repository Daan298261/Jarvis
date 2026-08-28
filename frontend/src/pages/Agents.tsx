import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  AGENT_AUTONOMY_LEVELS,
  deleteAgentPolicyProfile,
  getPlatformAgentPolicy,
  listAgentPolicyAudit,
  listAgentPolicyProfiles,
  putPlatformAgentPolicy,
  type AgentPolicyAuditEvent,
  type AgentPolicyProfile,
  type PlatformAgentPolicy,
} from "../api"
import { AUTONOMY_COPY, autonomyTitle } from "./agentInterviewCopy"

type CapRow = { key: string; level: string }

function capsToRows(caps: Record<string, string> | undefined): CapRow[] {
  const entries = Object.entries(caps || {})
  if (!entries.length) return [{ key: "*", level: "L5_OPERATOR" }]
  return entries.map(([key, level]) => ({ key, level }))
}

function rowsToCaps(rows: CapRow[]): Record<string, string> {
  const next: Record<string, string> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (!key) continue
    next[key] = row.level
  }
  return next
}

function formatWhen(value: string | undefined): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function missionPreview(profile: AgentPolicyProfile): string {
  const mission = profile.interview_answers?.mission?.trim()
  if (mission) return mission
  return "No mission written yet."
}

export function AgentsPage() {
  const navigate = useNavigate()
  const [profiles, setProfiles] = useState<AgentPolicyProfile[]>([])
  const [platform, setPlatform] = useState<PlatformAgentPolicy | null>(null)
  const [events, setEvents] = useState<AgentPolicyAuditEvent[]>([])
  const [capRows, setCapRows] = useState<CapRow[]>([{ key: "*", level: "L5_OPERATOR" }])
  const [defaultCap, setDefaultCap] = useState("L2_EXECUTE_SAFE")
  const [showPlatform, setShowPlatform] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [error, setError] = useState("")

  async function refresh() {
    const [list, plat, audit] = await Promise.all([
      listAgentPolicyProfiles(),
      getPlatformAgentPolicy().catch(() => null),
      listAgentPolicyAudit({ limit: 12 }).catch(() => ({ events: [] as AgentPolicyAuditEvent[] })),
    ])
    setProfiles(list.profiles || [])
    setEvents(audit.events || [])
    if (plat) {
      setPlatform(plat)
      setCapRows(capsToRows(plat.autonomy_caps))
      setDefaultCap(plat.default_agent_autonomy || "L2_EXECUTE_SAFE")
    }
  }

  useEffect(() => {
    refresh().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not load agent profiles.")
    })
  }, [])

  async function onDelete(profile: AgentPolicyProfile) {
    if (!window.confirm(`Remove agent “${profile.name}”? This cannot be undone.`)) return
    setBusy(true)
    setError("")
    try {
      await deleteAgentPolicyProfile(profile.id)
      await refresh()
      setMsg(`Removed ${profile.name}.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not remove this agent.")
    } finally {
      setBusy(false)
    }
  }

  async function onSavePlatform() {
    setBusy(true)
    setError("")
    try {
      const next = await putPlatformAgentPolicy({
        autonomy_caps: rowsToCaps(capRows),
        default_agent_autonomy: defaultCap,
      })
      setPlatform(next)
      setCapRows(capsToRows(next.autonomy_caps))
      setDefaultCap(next.default_agent_autonomy)
      setMsg("This PC’s limits were saved. They always cap what an agent may do.")
      await refresh()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save this PC’s limits.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="agents-page">
      <h1>Agent profiles</h1>
      <p className="lede">
        Create a specialist by answering a few questions. Jarvis turns the answers into a visible
        policy you can still edit. Stay-with-a-job and Away Mode live under Settings — this page is
        about what the agent is allowed to do.
      </p>

      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}
      {error && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
          {error}
        </div>
      )}

      <div className="row" style={{ marginBottom: 16 }}>
        <Link className="btn" to="/agents/new">
          New agent interview
        </Link>
        <button className="btn secondary" type="button" onClick={() => setShowPlatform((open) => !open)}>
          {showPlatform ? "Hide this PC’s limits" : "This PC’s limits"}
        </button>
      </div>

      {showPlatform && (
        <div className="card" style={{ maxWidth: 760, marginBottom: 16 }}>
          <h2>This PC’s limits</h2>
          <p className="lede" style={{ margin: "0 0 12px" }}>
            These caps always win. An agent cannot go past them, even if its interview says otherwise.
          </p>
          <label>
            Default freedom for a new agent
            <select value={defaultCap} onChange={(event) => setDefaultCap(event.target.value)}>
              {AGENT_AUTONOMY_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {autonomyTitle(level)} — {level}
                </option>
              ))}
            </select>
          </label>
          <div className="autonomy-rows" style={{ marginTop: 12 }}>
            {capRows.map((row, index) => (
              <div className="autonomy-row" key={`${row.key}-${index}`}>
                <input
                  type="text"
                  value={row.key}
                  placeholder="tool or action, e.g. terminal"
                  aria-label="Capability"
                  onChange={(event) => {
                    const next = [...capRows]
                    next[index] = { ...row, key: event.target.value }
                    setCapRows(next)
                  }}
                />
                <select
                  value={row.level}
                  aria-label="Cap level"
                  onChange={(event) => {
                    const next = [...capRows]
                    next[index] = { ...row, level: event.target.value }
                    setCapRows(next)
                  }}
                >
                  {AGENT_AUTONOMY_LEVELS.map((level) => (
                    <option key={level} value={level}>
                      {AUTONOMY_COPY[level]?.title || level}
                    </option>
                  ))}
                </select>
                <button
                  className="btn secondary"
                  type="button"
                  onClick={() => setCapRows(capRows.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button
              className="btn secondary"
              type="button"
              onClick={() => setCapRows([...capRows, { key: "", level: "L3_EXECUTE_WITH_GATES" }])}
            >
              Add a cap
            </button>
            <button className="btn" type="button" disabled={busy} onClick={onSavePlatform}>
              Save limits
            </button>
          </div>
          {platform && (
            <p className="lede" style={{ margin: "12px 0 0" }}>
              Current default: {autonomyTitle(platform.default_agent_autonomy)}. Caps apply to every agent on this PC.
            </p>
          )}
        </div>
      )}

      <div className="template-grid">
        {profiles.map((profile) => {
          const level = profile.policy?.autonomy?.["*"] || profile.interview_answers?.default_autonomy || ""
          return (
            <article key={profile.id} className="template-card runtime-card">
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>{profile.name}</h3>
                {level && <span className="badge waiting">{autonomyTitle(level)}</span>}
              </div>
              <p>{missionPreview(profile)}</p>
              {profile.interview_answers?.tone && (
                <div className="runtime-tags">
                  <span>{profile.interview_answers.tone}</span>
                  {(profile.interview_answers.allowed_channels || []).slice(0, 4).map((channel) => (
                    <span key={channel}>{channel}</span>
                  ))}
                </div>
              )}
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" type="button" onClick={() => navigate(`/agents/${profile.id}`)}>
                  Continue interview
                </button>
                <button className="btn secondary" type="button" disabled={busy} onClick={() => onDelete(profile)}>
                  Remove
                </button>
              </div>
            </article>
          )
        })}
      </div>
      {!profiles.length && (
        <p className="lede">No specialists yet. Start an interview to describe one.</p>
      )}

      <div className="card" style={{ maxWidth: 760, marginTop: 24 }}>
        <h2>Recent changes</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Who changed a profile, when, and which field. Runtime tool checks are not this list.
        </p>
        {events.length === 0 && <p className="lede" style={{ margin: 0 }}>No policy changes recorded yet.</p>}
        {events.map((event) => (
          <div className="suggestion-row" key={event.id}>
            <div>
              <strong>{event.field}</strong>
              <p>
                {event.actor || "portal"} · {formatWhen(event.timestamp)}
                {event.profile_id ? ` · ${event.profile_id.slice(0, 8)}` : " · this PC"}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
