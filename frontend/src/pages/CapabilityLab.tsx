import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  getCapabilityLabRegistry,
  runCapabilityLabBenchmark,
  type CapabilityLabBenchmarkResult,
  type CapabilityLabRegistry,
} from "../api"

const PARITY_LABEL: Record<string, string> = {
  missing: "Missing",
  partial: "Partial",
  equivalent: "Equivalent",
}

const LIFECYCLE_LABEL: Record<string, string> = {
  specified: "Specified",
  implemented: "Implemented",
  verified: "Verified",
  parity_demonstrated: "Parity demonstrated",
}

export function CapabilityLabPage() {
  const [registry, setRegistry] = useState<CapabilityLabRegistry | null>(null)
  const [benchmark, setBenchmark] = useState<CapabilityLabBenchmarkResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const refresh = useCallback(async () => {
    setError("")
    try {
      const next = await getCapabilityLabRegistry()
      setRegistry(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load capability registry")
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function onRunDeterministic(capabilityIds?: string[]) {
    setBusy(true)
    setError("")
    try {
      const result = await runCapabilityLabBenchmark(capabilityIds)
      setBenchmark(result)
      if (!result.ok && result.error) setError(result.error)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Benchmark failed")
    } finally {
      setBusy(false)
    }
  }

  const summary = registry?.summary

  return (
    <div className="page">
      <header className="page-header">
        <h1>Capability Lab</h1>
        <p className="lede">
          RFC-0137 parity ledger from the #406 program. Coverage states are evidence-linked; deterministic
          pytest runs do not claim superiority without dated hardware measurements.
        </p>
        <p className="lede">
          <Link to="/skills">← Modules / Skills</Link>
        </p>
      </header>

      {error ? <p className="lede" role="alert">{error}</p> : null}

      {summary ? (
        <div className="card grid" style={{ marginBottom: 16 }}>
          <h2>Summary</h2>
          <p className="lede" style={{ margin: 0 }}>
            Registry v{summary.version} · {summary.total} capabilities · updated {registry?.updated_at || "—"}
          </p>
          <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
            {Object.entries(summary.by_parity_state || {}).map(([key, count]) => (
              <span key={key} className="badge">
                {PARITY_LABEL[key] || key}: {count}
              </span>
            ))}
          </div>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void onRunDeterministic()}>
            Run deterministic linked tests
          </button>
        </div>
      ) : null}

      {benchmark ? (
        <div className="card grid" style={{ marginBottom: 16 }}>
          <h2>Last benchmark</h2>
          <p className="lede" style={{ margin: 0 }}>
            {benchmark.ok ? "Passed" : "Failed"} · {benchmark.mode} · {benchmark.elapsed_ms ?? "—"} ms
          </p>
          {benchmark.message ? <p className="lede">{benchmark.message}</p> : null}
        </div>
      ) : null}

      <div className="card grid">
        <h2>Capabilities</h2>
        {!registry?.capabilities?.length ? (
          <p className="lede">Loading…</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>RFC</th>
                <th>Parity</th>
                <th>Lifecycle</th>
                <th>Tests</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {registry.capabilities.map((row) => (
                <tr key={row.id}>
                  <td>
                    <strong>{row.title}</strong>
                    <div className="lede" style={{ margin: 0 }}>{row.id}</div>
                  </td>
                  <td>{row.rfc_id}</td>
                  <td>{PARITY_LABEL[row.parity_state] || row.parity_state}</td>
                  <td>{LIFECYCLE_LABEL[row.lifecycle] || row.lifecycle}</td>
                  <td>{row.test_ids.length ? row.test_ids.join(", ") : "—"}</td>
                  <td>
                    {row.test_ids.length ? (
                      <button
                        type="button"
                        className="btn"
                        disabled={busy}
                        onClick={() => void onRunDeterministic([row.id])}
                      >
                        Run tests
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
