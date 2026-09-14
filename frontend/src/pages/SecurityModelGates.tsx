import { useEffect, useMemo, useState, type FormEvent } from "react"
import {
  api,
  getCyberAtoStatus,
  installCyberAto,
  issueCyberAto,
  renewCyberAto,
  revokeCyberAto,
  type CyberAtoStatus,
} from "../api"

type SecurityGateStatus = {
  role: "blue-team" | "red-team"
  configured: boolean
  enabled: boolean
  ops_allowed?: boolean
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
    note: "Unlocks defensive SOC, threat-analysis and DFIR model routing after a valid in-person ATO grants Blue. Password unlock persists until you lock it again.",
  },
  "red-team": {
    title: "Red Team",
    models: "DeepHat V1 7B",
    note: "Unlocks the Red specialist model only with a valid in-person ATO that has the law-enforcement flag. Case reference and human confirmation are still required. This does not add exploits.",
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

      <CyberAtoPanel onChanged={() => void refresh()} />

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
                <span className={`badge ${gate.ops_allowed ? "ok" : ""}`}>
                  {gate.ops_allowed ? "Ops allowed" : gate.enabled ? "Password on · ATO needed" : gate.configured ? "Locked" : "Not configured"}
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

function CyberAtoPanel({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<CyberAtoStatus | null>(null)
  const [lawEnforcement, setLawEnforcement] = useState(false)
  const [blueTeam, setBlueTeam] = useState(true)
  const [redTeam, setRedTeam] = useState(false)
  const [validDays, setValidDays] = useState(90)
  const [renewInDays, setRenewInDays] = useState(75)
  const [caseRef, setCaseRef] = useState("")
  const [paste, setPaste] = useState("")
  const [issued, setIssued] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")

  async function refresh() {
    const next = await getCyberAtoStatus()
    setStatus(next)
    setLawEnforcement(next.law_enforcement)
    setBlueTeam(next.blue_team || !next.installed)
    setRedTeam(next.red_team)
    setCaseRef(next.case_ref)
  }

  useEffect(() => {
    refresh().catch(() => setError("Could not load the cyber ATO license."))
  }, [])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError("")
    setMessage("")
    try {
      await action()
      await refresh()
      onChanged()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "ATO request failed.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="card" style={{ marginTop: 14 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h3 style={{ margin: 0 }}>In-person cyber ATO</h3>
          <p className="lede" style={{ margin: "6px 0 0" }}>
            Blue and Red runtime require a signed license issued after in-person verification.
            Red also needs the law-enforcement checkbox. This does not add exploits or payloads.
          </p>
        </div>
        <span className={`badge ${status?.valid ? "ok" : ""}`}>
          {status?.valid ? (status.renewal_due ? "Valid · renewal due" : "Valid") : status?.installed ? "Invalid" : "Not installed"}
        </span>
      </div>
      {status && (
        <p className="lede" style={{ marginTop: 10 }}>
          {status.reason}
          {status.expires_at ? ` · valid until ${status.expires_at}` : ""}
          {status.renew_by ? ` · ATO renew by ${status.renew_by}` : ""}
        </p>
      )}
      {message && <p style={{ color: "var(--ok)" }}>{message}</p>}
      {error && <p style={{ color: "var(--bad)" }}>{error}</p>}

      <form
        onSubmit={(event) => {
          event.preventDefault()
          void run(async () => {
            const result = await issueCyberAto({
              law_enforcement: lawEnforcement,
              blue_team: blueTeam,
              red_team: redTeam,
              valid_days: validDays,
              renew_in_days: renewInDays,
              case_ref: caseRef,
              install: true,
            })
            setIssued(JSON.stringify(result.license, null, 2))
            setMessage("Issued and installed an in-person ATO license on this Leader.")
          })
        }}
      >
        <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
          <input
            type="checkbox"
            checked={lawEnforcement}
            onChange={(event) => {
              const checked = event.target.checked
              setLawEnforcement(checked)
              if (!checked) setRedTeam(false)
            }}
          />
          Law enforcement
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={blueTeam} onChange={(event) => setBlueTeam(event.target.checked)} />
          Blue team
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={redTeam}
            disabled={!lawEnforcement}
            onChange={(event) => setRedTeam(event.target.checked)}
          />
          Red team (requires LE)
        </label>
        <div className="grid two" style={{ marginTop: 10 }}>
          <label>Validity (days)
            <input type="number" min={1} max={3660} value={validDays} onChange={(event) => setValidDays(Number(event.target.value) || 1)} />
          </label>
          <label>ATO renewal (days)
            <input type="number" min={1} max={3660} value={renewInDays} onChange={(event) => setRenewInDays(Number(event.target.value) || 1)} />
          </label>
        </div>
        <label>Case / authorization reference
          <input value={caseRef} onChange={(event) => setCaseRef(event.target.value)} placeholder="optional" />
        </label>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="btn" type="submit" disabled={busy}>Issue license</button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy || !status?.can_issue || !status.installed}
            onClick={() => void run(async () => {
              const result = await renewCyberAto({ valid_days: validDays, renew_in_days: renewInDays, install: true })
              setIssued(JSON.stringify(result.license, null, 2))
              setMessage("ATO renewed on this Leader.")
            })}
          >
            Renew ATO
          </button>
          <button
            className="btn secondary"
            type="button"
            disabled={busy || !status?.installed}
            onClick={() => void run(async () => {
              await revokeCyberAto()
              setIssued("")
              setMessage("ATO removed from this Leader.")
            })}
          >
            Revoke
          </button>
        </div>
      </form>

      {issued && (
        <label style={{ marginTop: 12 }}>Signed license
          <textarea readOnly rows={8} value={issued} aria-label="Signed cyber ATO JSON" />
        </label>
      )}

      <form
        style={{ marginTop: 12 }}
        onSubmit={(event) => {
          event.preventDefault()
          void run(async () => {
            const parsed = JSON.parse(paste) as Record<string, unknown>
            await installCyberAto(parsed)
            setMessage("Installed the pasted ATO license.")
          })
        }}
      >
        <label>Install an existing signed license
          <textarea rows={6} value={paste} onChange={(event) => setPaste(event.target.value)} aria-label="Paste signed ATO JSON" />
        </label>
        <button className="btn secondary" type="submit" disabled={busy || !paste.trim()}>Install license</button>
      </form>
    </article>
  )
}
