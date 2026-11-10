import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "../api"
import type { NodeAiInventory as Inventory } from "./nodeModelOptions"

export function NodeAiInventory() {
  const [data, setData] = useState<Inventory | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const revision = useRef(0)
  const refresh = useCallback(async (force = false) => {
    const current = ++revision.current
    setBusy(true); setError("")
    try {
      const result = await api<Inventory>(`/api/model/node-inventory${force ? "?refresh=true" : ""}`)
      if (current === revision.current) setData(result)
    } catch (err) {
      if (current === revision.current) setError(err instanceof Error ? err.message : "Node inventory is unavailable")
    } finally { if (current === revision.current) setBusy(false) }
  }, [])
  useEffect(() => { void refresh(); return () => { ++revision.current } }, [refresh])
  const loaded = data?.models.filter((model) => model.verified_loaded) || []
  const advertised = data?.servers.filter((server) => !server.verified_loaded) || []
  return <section className="node-ai-inventory" aria-label="AI instances on this node">
    <div className="node-ai-heading"><h3>{data?.node.hostname || "This node"} · AI instances</h3>
      <button type="button" disabled={busy} onClick={() => void refresh(true)}>{busy ? "Scanning…" : "Refresh"}</button></div>
    {error && <p role="alert">Could not refresh inventory: {error}{data ? " Showing the previous scan." : ""}</p>}
    {data && <>
      <p className="node-ai-meta">Scan: {new Date(data.checked_at * 1000).toLocaleTimeString()} · {data.node.id || "Local node"}</p>
      <h4>Verified loaded models ({loaded.length})</h4>
      {!loaded.length && <p>No loaded models verified in this scan.</p>}
      <ul>{loaded.map((model) => <li key={model.id}>
        <strong>{model.display_name || model.model}</strong>
        <span>{[model.parameters, model.quantization, model.context_size ? `${model.context_size.toLocaleString()} context` : "", ...model.roles].filter(Boolean).join(" · ")}</span>
        <span>{model.backend} · Port {model.port}{model.pid ? ` · PID ${model.pid}` : ""}{model.active ? " · Used by ANZU" : ""}</span>
        <span>{model.busy === true ? "Processing a request" : model.busy === false ? "Idle" : "Request activity unknown"} · {model.source}</span>
        {model.model !== model.display_name && <small>{model.model}</small>}
      </li>)}</ul>
      <h4>Other model-server listings ({advertised.length})</h4>
      {!advertised.length && <p>No additional server listings detected.</p>}
      <ul>{advertised.map((server) => <li key={server.port}>
        <strong>{server.program} · Port {server.port}{server.pid ? ` · PID ${server.pid}` : ""}</strong>
        <span>{server.status}</span><small>{server.models.join(", ") || "Model identity not exposed"}</small>
      </li>)}</ul>
      <h4>AI programs and services ({data.programs.length})</h4>
      {!data.programs.length && <p>No recognized AI programs detected.</p>}
      <ul>{data.programs.map((program) => <li key={program.id}>
        <strong>{program.name} · PID {program.pid}</strong>
        <span>{program.category} · {program.process_count} recognized process{program.process_count === 1 ? "" : "es"}</span>
        <small>Program detected; model/session activity is not inferred from its processes.</small>
      </li>)}</ul>
      {data.warnings.map((warning) => <p className="node-ai-warning" key={warning}>{warning}</p>)}
      <p className="node-ai-meta">{data.coverage} This view does not start or stop other programs.</p>
    </>}
  </section>
}
