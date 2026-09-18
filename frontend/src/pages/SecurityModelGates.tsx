import { useEffect, useMemo, useState } from "react"
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
  ato?: CyberAtoStatus
}

type GateListResponse = {
  gates: SecurityGateStatus[]
}

const GATE_COPY: Record<SecurityGateStatus["role"], { title: string; models: string; note: string }> = {
  "blue-team": {
    title: "Blue Team / DFIR",
    models: "RedSage + Imperum",
    note: "Defensive SOC, threat-analysis, and DFIR routing when the installed license package includes Blue team.",
  },
  "red-team": {
    title: "Red Team",
    models: "DeepHat V1 7B",
    note: "Red specialist routing when the license package includes Red team with law enforcement. Case reference and human confirmation are still required. This does not add exploits.",
  },
}

async function listSecurityGates(): Promise<GateListResponse> {
  return api<GateListResponse>("/api/runtime-profiles/security-gates")
}

export function SecurityModelGates() {
  const [gates, setGates] = useState<SecurityGateStatus[]>([])
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

  return (
    <section style={{ margin: "18px 0" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h3 style={{ marginBottom: 4 }}>Security model access</h3>
          <p className="lede" style={{ margin: 0 }}>
            Blue, Red, and HexStrike capability follow the signed license package on this PC (License page). Per-action grants still apply after the pack is entitled.
          </p>
        </div>
        <button className="btn secondary" type="button" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

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
          return (
            <article className="card" key={role} style={{ margin: 0 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h3 style={{ margin: 0 }}>{copy.title}</h3>
                  <p style={{ margin: "4px 0 0" }}>{copy.models}</p>
                </div>
                <span className={`badge ${gate.ops_allowed ? "ok" : ""}`}>
                  {gate.ops_allowed ? "Ops allowed" : "Not on license package"}
                </span>
              </div>
              <p className="lede" style={{ marginTop: 10 }}>{copy.note}</p>
              {!gate.ops_allowed && gate.ato?.reason && (
                <p className="lede" style={{ marginTop: 8 }}>{gate.ato.reason}</p>
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
