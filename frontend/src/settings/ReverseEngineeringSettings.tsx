import { useEffect, useState } from "react"
import { api, getAuthUrl } from "../api"

type Ready = { engine: { status: string; stage?: string; error?: string }; android: { status: string; stage?: string; error?: string } }
type Investigation = { id: string; question: string; target: string; status: string; evidence: { id: string; operation: string }[]; findings: { claim: string; kind: string; evidence_ids: string[] }[]; unknowns: string[] }

export function ReverseEngineeringSettings() {
  const [ready, setReady] = useState<Ready | null>(null)
  const [rows, setRows] = useState<Investigation[]>([])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  async function refresh() {
    try {
      const [status, results] = await Promise.all([
        api<Ready>("/api/investigations/readiness"),
        api<{ investigations: Investigation[] }>("/api/investigations"),
      ])
      setReady(status)
      setRows(results.investigations)
      setError("")
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load investigations") }
  }
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 10000)
    return () => window.clearInterval(timer)
  }, [])
  async function setup() {
    setBusy(true)
    try { await api("/api/investigations/setup", { method: "POST" }); await refresh() }
    catch (err) { setError(err instanceof Error ? err.message : "Setup failed") }
    finally { setBusy(false) }
  }
  async function cancel(id: string) {
    try { await api(`/api/investigations/${id}/cancel`, { method: "POST" }); await refresh() }
    catch (err) { setError(err instanceof Error ? err.message : "Cancel failed") }
  }
  const installing = ready?.engine.status === "installing" || ready?.android.status === "installing"
  return <section className="card grid">
    <h2>Reverse Engineering</h2>
    <p>Ask ANZU to reverse engineer a local file or app folder and tell it what you want to understand.
      Findings are saved with evidence. Running an application requires your approval.</p>
    <p>Analysis engine: <strong>{ready?.engine.status ?? "Checking"}</strong> — {ready?.engine.stage}<br />
      Android runtime: <strong>{ready?.android.status ?? "Checking"}</strong> — {ready?.android.stage}</p>
    <p role="status">{error || ready?.engine.error || ready?.android.error}</p>
    <div className="row">
      <button className="btn" disabled={busy || installing} onClick={() => { void setup() }}>
        {installing ? "Installing…" : "Install / repair local tools"}
      </button>
      <button className="btn" onClick={() => { void refresh() }}>Refresh</button>
    </div>
    <p className="muted">Setup downloads local analysis tools and creates a dedicated WSL2 environment
      and Android emulator. Investigated applications stay local.</p>
    {rows.map(row => <article key={row.id} className="card grid">
      <strong>{row.question}</strong><span>{row.target}</span>
      <span>{row.status} · {row.evidence.length} saved evidence records</span>
      {row.findings.map((finding, i) => <p key={i}>{finding.kind}: {finding.claim} [{finding.evidence_ids.join(", ")}]</p>)}
      {row.unknowns.map((unknown, i) => <p key={i}>Unanswered: {unknown}</p>)}
      <div className="row">
        {(row.findings.length > 0 || row.unknowns.length > 0) && <>
          <a className="btn" href={getAuthUrl(`/api/investigations/${row.id}/report?format=md`)} download>Markdown report</a>
          <a className="btn" href={getAuthUrl(`/api/investigations/${row.id}/report?format=json`)} download>JSON report</a>
        </>}
        {!["closed", "cancelled"].includes(row.status) && <button className="btn" onClick={() => { void cancel(row.id) }}>Cancel investigation</button>}
      </div>
      {row.evidence.map(e => <a key={e.id} href={getAuthUrl(`/api/investigations/${row.id}/evidence/${e.id}`)} download>{e.id}: {e.operation}</a>)}
    </article>)}
  </section>
}
