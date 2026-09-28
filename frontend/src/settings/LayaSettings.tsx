import { useCallback, useEffect, useState } from "react"
import {
  disableLaya,
  enableLaya,
  getLayaStatus,
  getReflexCalibration,
  installLaya,
  type LayaStatus,
  type ReflexCalibration,
} from "../api"

type LayaSettingsProps = {
  setMsg: (msg: string) => void
}

function stateLabel(status: LayaStatus | null): string {
  if (!status) return "Loading…"
  if (status.load_error) return `Error — ${status.load_error}`
  if (status.loading) return "Warming up…"
  if (status.enabled && status.warm) {
    const device = status.device ? ` on ${status.device}` : ""
    return `Ready${device}${status.fixture ? " (test fixture)" : ""}`
  }
  if (status.installed) return "Installed — disabled"
  if (!status.package_version) return "Not installed — the laya Python package is missing"
  return "Not installed"
}

export function LayaSettings({ setMsg }: LayaSettingsProps) {
  const [status, setStatus] = useState<LayaStatus | null>(null)
  const [calibration, setCalibration] = useState<ReflexCalibration | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const next = await getLayaStatus().catch(() => null)
    if (next) setStatus(next)
    setCalibration(await getReflexCalibration().catch(() => null))
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!status?.loading) return
    const id = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(id)
  }, [status?.loading, refresh])

  async function run(action: () => Promise<LayaStatus>, done: string) {
    setBusy(true)
    try {
      setStatus(await action())
      setMsg(done)
      await refresh()
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Laya request failed")
    } finally {
      setBusy(false)
    }
  }

  const accuracyRows = Object.entries(calibration?.accuracy ?? {})

  return (
    <div className="grid" style={{ gap: 8, marginTop: 12 }}>
      <h3 style={{ margin: 0 }}>Local Laya (System One, on this PC)</h3>
      <p className="lede" style={{ margin: 0 }}>
        Status: <strong>{stateLabel(status)}</strong>
        {status?.last_infer_ms != null && status.warm ? ` · last decision ${Math.round(status.last_infer_ms)} ms` : ""}
      </p>
      <p className="lede" style={{ margin: 0 }}>
        Pinned laya {status?.version || "checkpoint"} · Apache-2.0 · runs in-process, never on the network.
        Long input is measured first, then scanned in windows or compressed so nothing is silently cut.
      </p>
      <div className="row">
        {!status?.installed ? (
          <button
            type="button"
            className="btn primary"
            disabled={busy || !status?.package_version}
            onClick={() => void run(installLaya, "Laya installed and verified. Warming up in the background.")}
          >
            Install and enable (~680 MB)
          </button>
        ) : status.enabled ? (
          <button type="button" className="btn" disabled={busy} onClick={() => void run(disableLaya, "Laya disabled.")}>
            Disable
          </button>
        ) : (
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() => void run(enableLaya, "Laya enabled. Warming up in the background.")}
          >
            Enable
          </button>
        )}
      </div>
      {accuracyRows.length ? (
        <table className="data-table">
          <thead>
            <tr>
              <th>Decision</th>
              <th>Laya</th>
              <th>Rules</th>
              <th>Served by</th>
            </tr>
          </thead>
          <tbody>
            {accuracyRows.map(([decisionClass, scores]) => {
              const laya = scores.laya
              const rules = scores.rules
              return (
                <tr key={decisionClass}>
                  <td>{decisionClass.replace(/_/g, " ")}</td>
                  <td>{laya != null ? `${Math.round(laya * 100)}%` : "—"}</td>
                  <td>{rules != null ? `${Math.round(rules * 100)}%` : "—"}</td>
                  <td>{laya != null && rules != null && laya > rules ? "Laya" : "Rules"}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
