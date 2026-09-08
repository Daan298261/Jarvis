import { useEffect, useMemo, useState, type FormEvent } from "react"
import { api } from "../api"

type SecurityGateStatus = {
  role: "blue-team" | "red-team"
  configured: boolean
  enabled: boolean
}

type GateListResponse = {
  gates: SecurityGateStatus[]
}

type GateSecrets = {
  unlock: string
  current: string
  next: string
  confirm: string
}

const EMPTY_SECRETS: GateSecrets = {
  unlock: "",
  current: "",
  next: "",
  confirm: "",
}

const GATE_COPY: Record<SecurityGateStatus["role"], { title: string; models: string; note: string }> = {
  "blue-team": {
    title: "Blue Team / DFIR",
    models: "RedSage + Imperum",
    note: "Unlocks defensive SOC, threat-analysis and DFIR model routing. The unlocked state persists across Jarvis restarts until you lock it again.",
  },
  "red-team": {
    title: "Red Team",
    models: "DeepHat V1 7B",
    note: "Unlocks the Red specialist model. Red tasks still require an authorization/case reference and explicit human confirmation; the password is not a scope bypass.",
  },
}

async function listSecurityGates(): Promise<GateListResponse> {
  return api<GateListResponse>("/api/runtime-profiles/security-gates")
}

async function setSecurityGatePassword(
  role: SecurityGateStatus["role"],
  body: { new_password: string; current_password?: string; enable?: boolean },
): Promise<SecurityGateStatus> {
  return api<SecurityGateStatus>(
    `/api/runtime-profiles/security-gates/${encodeURIComponent(role)}/password`,
    { method: "PUT", body: JSON.stringify(body) },
  )
}

async function unlockSecurityGate(
  role: SecurityGateStatus["role"],
  password: string,
): Promise<SecurityGateStatus> {
  return api<SecurityGateStatus>(
    `/api/runtime-profiles/security-gates/${encodeURIComponent(role)}/unlock`,
    { method: "POST", body: JSON.stringify({ password }) },
  )
}

async function lockSecurityGate(role: SecurityGateStatus["role"]): Promise<SecurityGateStatus> {
  return api<SecurityGateStatus>(
    `/api/runtime-profiles/security-gates/${encodeURIComponent(role)}/lock`,
    { method: "POST" },
  )
}

export function SecurityModelGates() {
  const [gates, setGates] = useState<SecurityGateStatus[]>([])
  const [secrets, setSecrets] = useState<Record<string, GateSecrets>>({})
  const [busyRole, setBusyRole] = useState<string>("")
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")

  const gateByRole = useMemo(
    () => new Map(gates.map((gate) => [gate.role, gate])),
    [gates],
  )

  async function refresh() {
    const data = await listSecurityGates()
    setGates(data.gates || [])
  }

  useEffect(() => {
    refresh().catch(() => setError("Could not load the security model gates."))
  }, [])

  function roleSecrets(role: SecurityGateStatus["role"]): GateSecrets {
    return secrets[role] || EMPTY_SECRETS
  }

  function patchSecrets(role: SecurityGateStatus["role"], patch: Partial<GateSecrets>) {
    setSecrets((current) => ({
      ...current,
      [role]: { ...(current[role] || EMPTY_SECRETS), ...patch },
    }))
  }

  function clearSecrets(role: SecurityGateStatus["role"]) {
    setSecrets((current) => ({ ...current, [role]: { ...EMPTY_SECRETS } }))
  }

  async function configure(role: SecurityGateStatus["role"], event: FormEvent) {
    event.preventDefault()
    const current = roleSecrets(role)
    if (current.next.length < 10) {
      setError("Use a password of at least 10 characters.")
      return
    }
    if (current.next !== current.confirm) {
      setError("The new passwords do not match.")
      return
    }
    setBusyRole(role)
    setError("")
    setMessage("")
    try {
      await setSecurityGatePassword(role, { new_password: current.next, enable: true })
      clearSecrets(role)
      await refresh()
      setMessage(`${GATE_COPY[role].title} enabled. This state will persist across restarts.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not configure the security gate.")
    } finally {
      setBusyRole("")
    }
  }

  async function unlock(role: SecurityGateStatus["role"], event: FormEvent) {
    event.preventDefault()
    const password = roleSecrets(role).unlock
    if (!password) {
      setError("Enter the password first.")
      return
    }
    setBusyRole(role)
    setError("")
    setMessage("")
    try {
      await unlockSecurityGate(role, password)
      clearSecrets(role)
      await refresh()
      setMessage(`${GATE_COPY[role].title} enabled.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not unlock the security gate.")
    } finally {
      setBusyRole("")
    }
  }

  async function lock(role: SecurityGateStatus["role"]) {
    setBusyRole(role)
    setError("")
    setMessage("")
    try {
      await lockSecurityGate(role)
      clearSecrets(role)
      await refresh()
      setMessage(`${GATE_COPY[role].title} locked.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not lock the security gate.")
    } finally {
      setBusyRole("")
    }
  }

  async function changePassword(role: SecurityGateStatus["role"], event: FormEvent) {
    event.preventDefault()
    const current = roleSecrets(role)
    if (!current.current) {
      setError("Enter the current password.")
      return
    }
    if (current.next.length < 10) {
      setError("Use a new password of at least 10 characters.")
      return
    }
    if (current.next !== current.confirm) {
      setError("The new passwords do not match.")
      return
    }
    setBusyRole(role)
    setError("")
    setMessage("")
    try {
      const gate = gateByRole.get(role)
      await setSecurityGatePassword(role, {
        current_password: current.current,
        new_password: current.next,
        enable: gate?.enabled ?? false,
      })
      clearSecrets(role)
      await refresh()
      setMessage(`${GATE_COPY[role].title} password changed.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not change the password.")
    } finally {
      setBusyRole("")
    }
  }

  return (
    <section style={{ margin: "18px 0" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h3 style={{ marginBottom: 4 }}>Security model access</h3>
          <p className="lede" style={{ margin: 0 }}>
            Passwords are verified by Jarvis and are never stored in this browser. Unlock state is stored by the local backend.
          </p>
        </div>
        <button className="btn secondary" type="button" onClick={() => void refresh()} disabled={!!busyRole}>
          Refresh
        </button>
      </div>

      {message && (
        <div className="card" style={{ marginTop: 12, borderLeft: "4px solid var(--ok)", padding: "10px 14px" }}>
          {message}
        </div>
      )}
      {error && (
        <div className="card" style={{ marginTop: 12, borderLeft: "4px solid var(--bad)", padding: "10px 14px" }}>
          {error}
        </div>
      )}

      <div className="grid two" style={{ marginTop: 14 }}>
        {(["blue-team", "red-team"] as const).map((role) => {
          const gate = gateByRole.get(role) || { role, configured: false, enabled: false }
          const copy = GATE_COPY[role]
          const current = roleSecrets(role)
          const busy = busyRole === role
          return (
            <article className="card" key={role} style={{ margin: 0 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ margin: 0 }}>{copy.title}</h3>
                  <p style={{ margin: "4px 0 0" }}>{copy.models}</p>
                </div>
                <span className={`badge ${gate.enabled ? "ok" : ""}`}>
                  {gate.enabled ? "Enabled" : gate.configured ? "Locked" : "Not configured"}
                </span>
              </div>
              <p className="lede" style={{ marginTop: 10 }}>{copy.note}</p>

              {!gate.configured && (
                <form onSubmit={(event) => void configure(role, event)}>
                  <label>New password
                    <input
                      type="password"
                      autoComplete="new-password"
                      minLength={10}
                      value={current.next}
                      onChange={(event) => patchSecrets(role, { next: event.target.value })}
                    />
                  </label>
                  <label>Confirm password
                    <input
                      type="password"
                      autoComplete="new-password"
                      minLength={10}
                      value={current.confirm}
                      onChange={(event) => patchSecrets(role, { confirm: event.target.value })}
                    />
                  </label>
                  <button className="btn" type="submit" disabled={busy}>Set password & enable</button>
                </form>
              )}

              {gate.configured && !gate.enabled && (
                <form onSubmit={(event) => void unlock(role, event)}>
                  <label>Password
                    <input
                      type="password"
                      autoComplete="current-password"
                      value={current.unlock}
                      onChange={(event) => patchSecrets(role, { unlock: event.target.value })}
                    />
                  </label>
                  <button className="btn" type="submit" disabled={busy}>Enable</button>
                </form>
              )}

              {gate.configured && gate.enabled && (
                <div className="row" style={{ marginBottom: 12 }}>
                  <button className="btn secondary" type="button" disabled={busy} onClick={() => void lock(role)}>
                    Lock
                  </button>
                </div>
              )}

              {gate.configured && (
                <details style={{ marginTop: 10 }}>
                  <summary>Change password</summary>
                  <form onSubmit={(event) => void changePassword(role, event)} style={{ marginTop: 10 }}>
                    <label>Current password
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={current.current}
                        onChange={(event) => patchSecrets(role, { current: event.target.value })}
                      />
                    </label>
                    <label>New password
                      <input
                        type="password"
                        autoComplete="new-password"
                        minLength={10}
                        value={current.next}
                        onChange={(event) => patchSecrets(role, { next: event.target.value })}
                      />
                    </label>
                    <label>Confirm new password
                      <input
                        type="password"
                        autoComplete="new-password"
                        minLength={10}
                        value={current.confirm}
                        onChange={(event) => patchSecrets(role, { confirm: event.target.value })}
                      />
                    </label>
                    <button className="btn secondary" type="submit" disabled={busy}>Change password</button>
                  </form>
                </details>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}
