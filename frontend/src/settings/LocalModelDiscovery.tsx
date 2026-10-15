import { useState } from "react"
import { api } from "../api"

type Model = { path: string; filename: string; quantization: string; weight_gb: number; already_registered: boolean }
export function LocalModelDiscovery() {
  const [models, setModels] = useState<Model[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  async function scan(importNew = false) {
    setBusy(true); setMessage("")
    try {
      if (importNew) await api("/api/model/discover-local", { method: "POST", body: JSON.stringify({ paths: models.filter(model => !model.already_registered).map(model => model.path) }) })
      const result = await api<{ models: Model[] }>("/api/model/discover-local")
      setModels(result.models || [])
      setMessage(importNew ? "Models added to the model selector." : `${result.models?.length || 0} local models found.`)
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not discover local models.") }
    finally { setBusy(false) }
  }
  return <section aria-label="Local model discovery">
    <button type="button" className="btn secondary" disabled={busy} onClick={() => void scan()}>Discover models on this PC</button>
    {models.length > 0 && <ul>{models.map(model => <li key={model.path}>{model.filename} · {model.quantization} · {model.weight_gb.toFixed(1)} GB{model.already_registered ? " · already added" : ""}</li>)}</ul>}
    {models.some(model => !model.already_registered) && <button type="button" className="btn" disabled={busy} onClick={() => void scan(true)}>Add discovered models</button>}
    {message && <p role="status">{message}</p>}
  </section>
}
