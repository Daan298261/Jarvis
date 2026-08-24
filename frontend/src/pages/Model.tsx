import { useEffect, useState } from "react"
import { api } from "../api"

type Benchmark = {
  id: number
  profile: string
  quantization: string
  context_size: number
  prompt_tokens_per_second: number | null
  tokens_per_second: number | null
  vram_used_mib: number | null
  ram_used_gb: number | null
  load_time_seconds: number | null
  task_success_rate: number | null
  tasks_completed: number
  tasks_failed: number
  source: string
  created_at: string | null
}

type ProfileInfo = {
  name: string
  label: string
  quant: string
  thinking_mode?: string
  context_size: number
  description: string
  family?: string
  alias?: string
  installed?: boolean
}

type ModelStatus = {
  active_model?: string
  family?: string
  thinking_mode?: string
  vision?: boolean
  quantization?: string
  context_size?: number
  inference_backend?: string
  gpu_layers?: string
  vram_used_mib?: number
  ram_used_gb?: number
  tokens_per_second?: number
  prompt_tokens_per_second?: number
  load_time_seconds?: number
  loaded?: boolean
  loading?: boolean
  last_error?: string
  profiles?: ProfileInfo[]
  outcomes?: { tasks_completed: number; tasks_failed: number; task_success_rate: number | null }
  benchmarks?: Benchmark[]
}

function pct(value: number | null | undefined) {
  if (value == null) return "n/a"
  return `${Math.round(value * 1000) / 10}%`
}

export function ModelPage() {
  const [model, setModel] = useState<ModelStatus | null>(null)
  const [busy, setBusy] = useState(false)

  async function refresh() {
    setModel(await api("/api/model"))
  }
  useEffect(() => { refresh() }, [])

  async function load(profile: string) {
    setBusy(true)
    try {
      await api("/api/model/load", { method: "POST", body: JSON.stringify({ profile }) })
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function snapshot() {
    setBusy(true)
    try {
      await api("/api/model/benchmarks/snapshot", { method: "POST" })
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const outcomes = model?.outcomes
  const samples = model?.benchmarks || []
  const profiles = model?.profiles || []

  return (
    <div>
      <h1>Model</h1>
      <p className="lede">Default is Qwen3.5-9B Abliterated (fully GPU-resident on the 5070 Ti). Qwen3.5-27B remains the Expert escalation model. The vision projector stays unloaded until you enable vision in Settings.</p>
      <div className="grid two">
        <div className="card">
          <div className="kv">
            <b>Active</b><span>{model?.active_model || "unloaded"}</span>
            <b>Family</b><span>{model?.family || "—"}</span>
            <b>Quantization</b><span>{model?.quantization}</span>
            <b>Context</b><span>{model?.context_size}</span>
            <b>Thinking</b><span>{model?.thinking_mode || "—"}</span>
            <b>Vision</b><span>{model?.vision ? "projector loaded" : "off"}</span>
            <b>Backend</b><span>{model?.inference_backend}</span>
            <b>GPU layers</b><span>{model?.gpu_layers}</span>
            <b>VRAM</b><span>{model?.vram_used_mib ? `${model.vram_used_mib} MiB` : "n/a"}</span>
            <b>RAM</b><span>{model?.ram_used_gb ? `${model.ram_used_gb} GB` : "n/a"}</span>
            <b>tok/s</b><span>{model?.tokens_per_second ?? "n/a"}</span>
            <b>Prompt tok/s</b><span>{model?.prompt_tokens_per_second ?? "n/a"}</span>
            <b>Load time</b><span>{model?.load_time_seconds ? `${model.load_time_seconds}s` : "n/a"}</span>
            <b>Task success</b><span>{pct(outcomes?.task_success_rate)} ({outcomes?.tasks_completed || 0} ok / {outcomes?.tasks_failed || 0} failed)</span>
            <b>State</b><span>{model?.loaded ? "loaded" : model?.loading ? "loading" : "unloaded"}</span>
          </div>
          {model?.last_error ? <p className="lede" style={{ marginTop: 12 }}>{model.last_error}</p> : null}
        </div>
        <div className="card">
          <h2>Profiles</h2>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => load("fast")}>Fast</button>
            <button className="btn" disabled={busy} onClick={() => load("balanced")}>Balanced</button>
            <button className="btn" disabled={busy} onClick={() => load("quality")}>Quality</button>
            <button className="btn" disabled={busy} onClick={() => load("expert")}>Expert</button>
            <button className="btn secondary" disabled={busy} onClick={() => api("/api/model/unload", { method: "POST" }).then(refresh)}>Unload</button>
            <button className="btn secondary" disabled={busy} onClick={snapshot}>Record snapshot</button>
          </div>
          <p className="lede" style={{ marginTop: 16 }}>
            Fast: 9B Q6_K, thinking off, 8K context.<br />
            Balanced (default): 9B Q8_0, selective thinking, 16K context.<br />
            Quality: 9B Q8_0, thinking on, 32K context.<br />
            Expert: 27B Q4_K_M escalation only. May spill to CPU.
          </p>
          {profiles.length > 0 && (
            <div className="lede" style={{ marginTop: 12 }}>
              {profiles.map((p) => (
                <div key={p.name}>{p.label}: {p.installed ? "installed" : "GGUF not downloaded"} · {p.quant} · {p.thinking_mode}</div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Benchmark history</h2>
        {!samples.length && <p className="lede">No samples yet. Load the model or record a snapshot after a few tasks.</p>}
        {samples.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Profile</th>
                <th>tok/s</th>
                <th>Prompt tok/s</th>
                <th>VRAM</th>
                <th>RAM</th>
                <th>Success</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((row) => (
                <tr key={row.id}>
                  <td>{row.created_at?.replace("T", " ").slice(0, 19) || "—"}</td>
                  <td>{row.profile || "—"} {row.quantization ? `· ${row.quantization}` : ""}</td>
                  <td className="stat">{row.tokens_per_second ?? "—"}</td>
                  <td className="stat">{row.prompt_tokens_per_second ?? "—"}</td>
                  <td>{row.vram_used_mib != null ? `${row.vram_used_mib} MiB` : "—"}</td>
                  <td>{row.ram_used_gb != null ? `${row.ram_used_gb} GB` : "—"}</td>
                  <td>{pct(row.task_success_rate)}</td>
                  <td>{row.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
