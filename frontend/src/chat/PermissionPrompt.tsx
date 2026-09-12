import { useEffect, useMemo, useState } from "react"
import { api } from "../api"
import "./permissionPrompt.css"

export type PermissionCatalogItem = {
  id: string
  group: string
  title: string
  detail: string
  status: string
  persisted: string
  gated?: string | null
  offensive?: boolean
  gate_unlocked?: boolean
  reason?: string
}

export type ConfirmationPayload = {
  kind?: string
  id?: string
  name?: string
  arguments?: Record<string, unknown>
  irreversible?: boolean
  permission_id?: string
  pending?: string[]
  title?: string
  detail?: string
  reason?: string
  options?: string[]
  catalog?: PermissionCatalogItem[]
}

type PermissionSnapshot = {
  permissions: PermissionCatalogItem[]
  groups: Record<string, PermissionCatalogItem[]>
}

type PermissionPromptProps = {
  taskId: string
  payload?: unknown
  variant?: "hud" | "classic" | "phone"
}

const GROUP_LABELS: Record<string, string> = {
  computer: "Computer use",
  network: "Network",
  cyber: "Cybersecurity suite",
  blue: "Blue team (defensive)",
  red: "Red team (flags only)",
}

export function parseConfirmationPayload(raw: unknown): ConfirmationPayload | null {
  if (raw == null || raw === "") return null
  if (typeof raw === "object") return raw as ConfirmationPayload
  if (typeof raw !== "string") return null
  try {
    const parsed = JSON.parse(raw) as ConfirmationPayload
    return parsed && typeof parsed === "object" ? parsed : null
  } catch {
    return null
  }
}

export function PermissionPrompt({ taskId, payload, variant = "classic" }: PermissionPromptProps) {
  const parsed = useMemo(() => parseConfirmationPayload(payload), [payload])
  const isPermission = parsed?.kind === "permission" || Boolean(parsed?.permission_id)
  const [moreOpen, setMoreOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [catalog, setCatalog] = useState<PermissionCatalogItem[]>(parsed?.catalog || [])

  useEffect(() => {
    if (!moreOpen) return
    let cancelled = false
    api<PermissionSnapshot>("/api/permissions")
      .then((data) => {
        if (!cancelled) setCatalog(data.permissions || [])
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [moreOpen])

  async function continueTask(body: Record<string, unknown>) {
    setBusy(true)
    setError("")
    try {
      await api(`/api/tasks/${taskId}/continue`, {
        method: "POST",
        body: JSON.stringify(body),
      })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save that choice.")
    } finally {
      setBusy(false)
    }
  }

  async function grant(mode: "allow_once" | "allow_session" | "always" | "deny") {
    await continueTask({
      approve: mode !== "deny",
      grant_mode: mode,
      permission_id: parsed?.permission_id,
    })
  }

  async function saveCatalogItem(id: string, mode: string) {
    setBusy(true)
    setError("")
    try {
      const next = await api<PermissionCatalogItem>(`/api/permissions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ mode }),
      })
      setCatalog((items) => items.map((item) => (item.id === id ? { ...item, ...next } : item)))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update that permission.")
    } finally {
      setBusy(false)
    }
  }

  const title = parsed?.title || (parsed?.irreversible ? "Approve this deletion" : "Jarvis needs permission")
  const detail =
    parsed?.detail ||
    parsed?.reason ||
    (parsed?.name ? `Jarvis wants to run ${parsed.name}.` : "Review this action before Jarvis continues.")

  const groups = useMemo(() => {
    const grouped: Record<string, PermissionCatalogItem[]> = {}
    for (const item of catalog) {
      grouped[item.group] = grouped[item.group] || []
      grouped[item.group].push(item)
    }
    return grouped
  }, [catalog])

  return (
    <div className={`permission-prompt permission-prompt-${variant}`}>
      <p className="permission-prompt-kicker">Permission required</p>
      <strong className="permission-prompt-title">{title}</strong>
      <p className="permission-prompt-detail">{detail}</p>
      {parsed?.irreversible && (
        <p className="permission-prompt-warn">This can delete or irreversibly change files.</p>
      )}
      {isPermission ? (
        <div className="permission-prompt-actions">
          <button className="btn" type="button" disabled={busy} onClick={() => void grant("allow_once")}>
            Allow once
          </button>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => void grant("always")}>
            Always allow
          </button>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => void grant("deny")}>
            Don&apos;t allow
          </button>
          <button
            className="permission-more-btn"
            type="button"
            aria-expanded={moreOpen}
            disabled={busy}
            onClick={() => setMoreOpen((open) => !open)}
          >
            {moreOpen ? "Less" : "More"}
          </button>
        </div>
      ) : (
        <div className="permission-prompt-actions">
          <button
            className="btn danger"
            type="button"
            disabled={busy}
            onClick={() => void continueTask({ approve: true })}
          >
            Approve
          </button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy}
            onClick={() => void continueTask({ approve: false })}
          >
            Reject
          </button>
        </div>
      )}
      {moreOpen && (
        <div className="permission-more">
          <p className="permission-more-lede">
            Internet, local network, HexStrike, and blue/red flags. Red is a permission flag only — Jarvis will not
            run offensive tools.
          </p>
          {Object.entries(GROUP_LABELS).map(([group, label]) => (
            <section key={group} className="permission-group">
              <h3>{label}</h3>
              {(groups[group] || []).map((item) => (
                <label key={item.id} className="permission-row">
                  <span>
                    <strong>{item.title}</strong>
                    <em>{item.detail}</em>
                    {item.offensive && <em className="permission-lock">Flag only. No payloads.</em>}
                    {item.gated && !item.gate_unlocked && (
                      <em className="permission-lock">Locked until the {item.gated} password gate is unlocked.</em>
                    )}
                  </span>
                  <select
                    value={item.persisted || item.status}
                    disabled={busy || (Boolean(item.gated) && !item.gate_unlocked && item.offensive)}
                    onChange={(event) => void saveCatalogItem(item.id, event.target.value)}
                    aria-label={item.title}
                  >
                    <option value="ask">Ask</option>
                    <option value="always">Always</option>
                    <option value="deny">Don&apos;t allow</option>
                  </select>
                </label>
              ))}
            </section>
          ))}
          <button
            className="btn secondary"
            type="button"
            disabled={busy}
            onClick={() => void grant("allow_session")}
          >
            Allow this session, then continue
          </button>
        </div>
      )}
      {error && <p className="permission-prompt-error">{error}</p>}
    </div>
  )
}
