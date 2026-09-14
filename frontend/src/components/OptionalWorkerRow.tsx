import { useState } from "react"
import { api } from "../api"

export type OptionalWorker = {
  id: string
  name: string
  available?: boolean
  status: string
  detail?: string
  installable?: boolean
  install_status?: string
  install_error?: string
  install_detail?: string
}

export function isWorkerInstalling(worker: OptionalWorker): boolean {
  return worker.status === "installing" || worker.install_status === "installing"
}

export function workerBadgeClass(worker: OptionalWorker): string {
  if (worker.available) return "completed"
  if (isWorkerInstalling(worker)) return "running"
  if (worker.install_status === "error" || worker.install_error) return "failed"
  return "queued"
}

export function OptionalWorkerRow({
  worker,
  onChanged,
}: {
  worker: OptionalWorker
  onChanged?: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState("")
  const installing = busy || isWorkerInstalling(worker)
  const showInstall = Boolean(worker.installable) && !worker.available
  const errorText = localError || worker.install_error || ""

  async function install() {
    if (installing) return
    setBusy(true)
    setLocalError("")
    try {
      await api(`/api/tools/optional-workers/${encodeURIComponent(worker.id)}/install`, { method: "POST" })
      onChanged?.()
    } catch (err: unknown) {
      setLocalError(err instanceof Error ? err.message : "Install failed.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="toggle">
      <div>
        <strong>{worker.name}</strong>
        <div className="lede" style={{ margin: "4px 0 0" }}>{worker.detail}</div>
        {installing && worker.install_detail ? (
          <div className="lede" style={{ margin: "4px 0 0" }}>{worker.install_detail}</div>
        ) : null}
        {errorText ? (
          <div className="lede worker-install-error" style={{ margin: "4px 0 0" }}>{errorText}</div>
        ) : null}
      </div>
      <div className="worker-actions">
        {showInstall ? (
          <button className="btn" type="button" disabled={installing} onClick={() => { void install() }}>
            {installing ? "Installing…" : "Install now"}
          </button>
        ) : null}
        <span className={`badge ${workerBadgeClass(worker)}`}>{worker.status}</span>
      </div>
    </div>
  )
}
