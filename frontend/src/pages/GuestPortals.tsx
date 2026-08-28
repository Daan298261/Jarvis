import { useEffect, useMemo, useState, type FormEvent } from "react"
import {
  GUEST_ACTIONS,
  GUEST_RESOURCE_TYPES,
  createGuestPortal,
  getGuestPortal,
  listGuestPortalAudit,
  listGuestPortals,
  previewGuestPortal,
  revokeGuestPortal,
  type GuestAction,
  type GuestAuditEntry,
  type GuestEffectivePermissions,
  type GuestGrant,
  type GuestPortal,
  type GuestPortalCreateIn,
  type GuestResourceType,
  type Task,
  api,
} from "../api"
import { EffectivePermissionsView } from "./guestPermissions"

type GrantDraft = {
  key: string
  resource_type: GuestResourceType
  resource_id: string
  actions: GuestAction[]
}

const RESOURCE_LABELS: Record<GuestResourceType, string> = {
  task: "Task",
  agent: "Agent",
  project: "Project",
  decision_inbox: "Decision inbox",
}

function newGrantKey(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function emptyGrant(): GrantDraft {
  return {
    key: newGrantKey(),
    resource_type: "task",
    resource_id: "",
    actions: ["read"],
  }
}

function toIsoExpiry(localValue: string): string | null {
  const trimmed = localValue.trim()
  if (!trimmed) return null
  const parsed = new Date(trimmed)
  if (Number.isNaN(parsed.getTime())) return trimmed
  return parsed.toISOString()
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "Never"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function parseOptionalInt(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) return null
  return Math.trunc(parsed)
}

function grantsFromDrafts(drafts: GrantDraft[]): GuestGrant[] {
  return drafts
    .map((draft) => ({
      resource_type: draft.resource_type,
      resource_id: draft.resource_id.trim(),
      actions: [...draft.actions],
    }))
    .filter((grant) => grant.resource_id && grant.actions.length)
}

function fingerprint(body: { grants: GuestGrant[]; limits: GuestPortalCreateIn["limits"]; expires_at: string | null }): string {
  return JSON.stringify({
    grants: body.grants,
    limits: {
      single_use: Boolean(body.limits?.single_use),
      max_sessions: body.limits?.max_sessions ?? null,
      max_uses: body.limits?.max_uses ?? null,
    },
    expires_at: body.expires_at,
  })
}

export function GuestPortalsPage() {
  const [portals, setPortals] = useState<GuestPortal[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [label, setLabel] = useState("Client review")
  const [guestLabel, setGuestLabel] = useState("guest")
  const [grants, setGrants] = useState<GrantDraft[]>([emptyGrant()])
  const [singleUse, setSingleUse] = useState(false)
  const [maxSessions, setMaxSessions] = useState("")
  const [maxUses, setMaxUses] = useState("")
  const [expiresLocal, setExpiresLocal] = useState("")
  const [preview, setPreview] = useState<GuestEffectivePermissions | null>(null)
  const [previewedFingerprint, setPreviewedFingerprint] = useState("")
  const [issued, setIssued] = useState<GuestPortal | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<GuestPortal | null>(null)
  const [audit, setAudit] = useState<GuestAuditEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const requestBody = useMemo(() => {
    const limits = {
      single_use: singleUse,
      max_sessions: parseOptionalInt(maxSessions),
      max_uses: parseOptionalInt(maxUses),
    }
    return {
      label: label.trim() || "Guest portal",
      guest_label: guestLabel.trim() || "guest",
      grants: grantsFromDrafts(grants),
      limits,
      expires_at: toIsoExpiry(expiresLocal),
    } satisfies GuestPortalCreateIn
  }, [label, guestLabel, grants, singleUse, maxSessions, maxUses, expiresLocal])

  const currentFingerprint = fingerprint(requestBody)
  const previewMatches = Boolean(preview) && previewedFingerprint === currentFingerprint

  async function refreshList() {
    const rows = await listGuestPortals()
    setPortals(rows)
  }

  useEffect(() => {
    refreshList().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not load guest portals.")
    })
    api<Task[]>("/api/tasks")
      .then(setTasks)
      .catch(() => undefined)
  }, [])

  async function loadPortal(id: string) {
    setSelectedId(id)
    setBusy(true)
    setError("")
    try {
      const [detail, rows] = await Promise.all([
        getGuestPortal(id),
        listGuestPortalAudit(id),
      ])
      setSelected(detail)
      setAudit(rows)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not load portal.")
    } finally {
      setBusy(false)
    }
  }

  function updateGrant(key: string, patch: Partial<GrantDraft>) {
    setGrants((current) => current.map((grant) => (grant.key === key ? { ...grant, ...patch } : grant)))
    setPreview(null)
    setPreviewedFingerprint("")
  }

  function toggleAction(key: string, action: GuestAction) {
    setGrants((current) =>
      current.map((grant) => {
        if (grant.key !== key) return grant
        const has = grant.actions.includes(action)
        const actions = has ? grant.actions.filter((item) => item !== action) : [...grant.actions, action]
        return { ...grant, actions }
      }),
    )
    setPreview(null)
    setPreviewedFingerprint("")
  }

  async function onPreview(event?: FormEvent) {
    event?.preventDefault()
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const result = await previewGuestPortal({
        grants: requestBody.grants,
        limits: requestBody.limits,
        expires_at: requestBody.expires_at,
      })
      setPreview(result)
      setPreviewedFingerprint(currentFingerprint)
      setMsg("Previewed effective permissions. Review them before issuing access.")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Preview failed.")
    } finally {
      setBusy(false)
    }
  }

  async function onIssue() {
    if (!previewMatches) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const created = await createGuestPortal(requestBody)
      setIssued(created)
      setMsg("Portal issued. Copy the token now — it is shown only once.")
      await refreshList()
      if (created.id) await loadPortal(created.id)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not issue portal.")
    } finally {
      setBusy(false)
    }
  }

  async function onRevoke(portal: GuestPortal) {
    if (portal.revoked) return
    const ok = window.confirm(`Revoke “${portal.label}” immediately? The guest link stops working now.`)
    if (!ok) return
    setBusy(true)
    setError("")
    try {
      const next = await revokeGuestPortal(portal.id)
      setMsg(`Revoked ${next.label}.`)
      await refreshList()
      if (selectedId === portal.id) await loadPortal(portal.id)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Revoke failed.")
    } finally {
      setBusy(false)
    }
  }

  async function copyText(value: string) {
    try {
      await navigator.clipboard.writeText(value)
      setMsg("Copied.")
    } catch {
      setMsg("Copy failed — select the text manually.")
    }
  }

  const guestLink = issued?.token
    ? `${window.location.origin}/guest?guest_token=${encodeURIComponent(issued.token)}`
    : ""

  return (
    <div className="guest-portals-page">
      <h1>Guest portals</h1>
      <p className="lede">
        Issue a scoped, revocable link so a client can read, query, or approve only the resources you
        grant. They never see unrelated agents, files, tools, or settings. Preview effective
        permissions before the token is created.
      </p>

      {error && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
          {error}
        </div>
      )}
      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--gold)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}

      <form className="card grid" style={{ maxWidth: 860 }} onSubmit={onPreview}>
        <h2>Create access</h2>
        <label>
          Portal label
          <input type="text" value={label} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label>
          Guest label (audit identity)
          <input type="text" value={guestLabel} onChange={(event) => setGuestLabel(event.target.value)} />
        </label>
        <label>
          Expires
          <input
            type="datetime-local"
            value={expiresLocal}
            onChange={(event) => {
              setExpiresLocal(event.target.value)
              setPreview(null)
              setPreviewedFingerprint("")
            }}
          />
        </label>
        <label className="row">
          <input
            type="checkbox"
            checked={singleUse}
            onChange={(event) => {
              setSingleUse(event.target.checked)
              setPreview(null)
              setPreviewedFingerprint("")
            }}
          />
          Single use (revokes after one authorized action)
        </label>
        <label>
          Max concurrent sessions (optional)
          <input
            type="number"
            min={1}
            value={maxSessions}
            placeholder="Unlimited"
            onChange={(event) => {
              setMaxSessions(event.target.value)
              setPreview(null)
              setPreviewedFingerprint("")
            }}
          />
        </label>
        <label>
          Max uses (optional)
          <input
            type="number"
            min={1}
            value={maxUses}
            placeholder="Unlimited"
            onChange={(event) => {
              setMaxUses(event.target.value)
              setPreview(null)
              setPreviewedFingerprint("")
            }}
          />
        </label>

        <div>
          <div className="rail-heading" style={{ paddingLeft: 0 }}>
            <span>Grants</span>
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setGrants((current) => [...current, emptyGrant()])
                setPreview(null)
                setPreviewedFingerprint("")
              }}
            >
              Add grant
            </button>
          </div>
          <p className="lede" style={{ margin: "0 0 10px" }}>
            Empty grants mean deny-all. Actions are only read, query, and approve.
          </p>
          {grants.map((grant) => (
            <div key={grant.key} className="grant-editor">
              <label>
                Resource
                <select
                  value={grant.resource_type}
                  onChange={(event) =>
                    updateGrant(grant.key, { resource_type: event.target.value as GuestResourceType })
                  }
                >
                  {GUEST_RESOURCE_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {RESOURCE_LABELS[type]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Resource id
                <input
                  type="text"
                  list={grant.resource_type === "task" ? "guest-task-ids" : undefined}
                  value={grant.resource_id}
                  placeholder={grant.resource_type === "task" ? "Task id" : "Exact id"}
                  onChange={(event) => updateGrant(grant.key, { resource_id: event.target.value })}
                />
              </label>
              <div className="chip-row" role="group" aria-label="Actions">
                {GUEST_ACTIONS.map((action) => (
                  <button
                    key={action}
                    type="button"
                    className={`chip${grant.actions.includes(action) ? " on" : ""}`}
                    onClick={() => toggleAction(grant.key, action)}
                  >
                    {action}
                  </button>
                ))}
              </div>
              {grants.length > 1 && (
                <button
                  className="btn secondary"
                  type="button"
                  onClick={() => {
                    setGrants((current) => current.filter((item) => item.key !== grant.key))
                    setPreview(null)
                    setPreviewedFingerprint("")
                  }}
                >
                  Remove grant
                </button>
              )}
            </div>
          ))}
          <datalist id="guest-task-ids">
            {tasks.map((task) => (
              <option key={task.id} value={task.id}>
                {task.title || task.prompt?.slice(0, 72) || task.id}
              </option>
            ))}
          </datalist>
        </div>

        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            Preview permissions
          </button>
          <button className="btn secondary" type="button" disabled={busy || !previewMatches} onClick={onIssue}>
            Issue access
          </button>
        </div>
        {!previewMatches && (
          <p className="lede" style={{ margin: 0 }}>
            Preview the effective permissions for this grant set before a token can be issued.
          </p>
        )}
      </form>

      {preview && (
        <div className="card" style={{ maxWidth: 860, marginTop: 16 }}>
          <EffectivePermissionsView perms={preview} title="Preview — what this guest would receive" />
        </div>
      )}

      {issued?.token && (
        <div className="card" style={{ maxWidth: 860, marginTop: 16, borderColor: "var(--gold)" }}>
          <h2>Token (shown once)</h2>
          <p className="lede">
            Copy this now. Jarvis does not store the raw token after issue. Share the guest link, not
            the owner portal.
          </p>
          <pre className="token-once">{issued.token}</pre>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" type="button" onClick={() => copyText(issued.token || "")}>
              Copy token
            </button>
            {guestLink && (
              <button className="btn secondary" type="button" onClick={() => copyText(guestLink)}>
                Copy guest link
              </button>
            )}
          </div>
          {guestLink && (
            <p className="lede" style={{ margin: "12px 0 0" }}>
              Guest view: <a href={guestLink}>{guestLink}</a>
            </p>
          )}
          {issued.effective_permissions && (
            <div style={{ marginTop: 16 }}>
              <EffectivePermissionsView perms={issued.effective_permissions} title="Issued permissions" />
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ maxWidth: 860, marginTop: 16 }}>
        <div className="rail-heading" style={{ paddingLeft: 0 }}>
          <span>Issued portals</span>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => refreshList()}>
            Refresh
          </button>
        </div>
        {portals.length === 0 ? (
          <p className="lede">No guest portals yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Label</th>
                <th>Guest</th>
                <th>Expires</th>
                <th>Limits</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {portals.map((portal) => (
                <tr
                  key={portal.id}
                  className={`swarm-row${selectedId === portal.id ? " selected" : ""}`}
                  onClick={() => loadPortal(portal.id)}
                >
                  <td>{portal.label}</td>
                  <td>{portal.guest_label}</td>
                  <td>{formatWhen(portal.expires_at)}</td>
                  <td>
                    {portal.limits?.single_use ? "single-use" : "multi-use"}
                    {portal.limits?.max_sessions != null ? ` · ${portal.limits.max_sessions} sessions` : ""}
                    {portal.uses_remaining != null ? ` · ${portal.uses_remaining} uses left` : ""}
                    {portal.active_sessions ? ` · ${portal.active_sessions} active` : ""}
                  </td>
                  <td>
                    <span className={`badge ${portal.revoked ? "failed" : "ok"}`}>
                      {portal.revoked ? "Revoked" : "Active"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && (
        <div className="card grid" style={{ maxWidth: 860, marginTop: 16 }}>
          <h2>{selected.label}</h2>
          <div className="kv">
            <b>Guest</b><span>{selected.guest_label}</span>
            <b>Created</b><span>{formatWhen(selected.created_at)}</span>
            <b>Expires</b><span>{formatWhen(selected.expires_at)}</span>
            <b>Revoked</b><span>{selected.revoked ? formatWhen(selected.revoked_at) : "No"}</span>
            <b>Uses remaining</b><span>{selected.uses_remaining ?? "Unlimited"}</span>
            <b>Active sessions</b><span>{selected.active_sessions}</span>
          </div>
          {selected.effective_permissions && (
            <EffectivePermissionsView perms={selected.effective_permissions} />
          )}
          <div className="row">
            <button
              className="btn danger"
              type="button"
              disabled={busy || selected.revoked}
              onClick={() => onRevoke(selected)}
            >
              Revoke immediately
            </button>
          </div>
          <h3>Audit</h3>
          {audit.length === 0 ? (
            <p className="lede">No audit events yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Guest</th>
                  <th>Action</th>
                  <th>Outcome</th>
                  <th>Resource</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((row) => (
                  <tr key={row.id}>
                    <td>{formatWhen(row.created_at)}</td>
                    <td>{row.guest_label}</td>
                    <td>{row.action}</td>
                    <td>
                      <span className={`badge ${row.outcome === "ok" ? "ok" : "failed"}`}>
                        {row.outcome}
                      </span>
                    </td>
                    <td>
                      {row.resource_type ? `${row.resource_type}:${row.resource_id || ""}` : row.path || "—"}
                      {row.detail ? ` · ${row.detail}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
