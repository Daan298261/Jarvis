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

type ModelStatus = {
  active_model?: string
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
  thinking_mode?: string
  vision?: boolean
  context_policy?: string
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

  return (
    <div>
      <h1>Model</h1>
      <p className="lede">Local Qwen3.5-27B served by llama.cpp. Profiles change quantization and whether thinking is allowed. Thinking is selective (planning, recovery, consequential verification — not every tool call). Context is chosen per task class (8K / 16K / 32K). The vision projector stays unloaded until a multimodal task needs it.</p>
      <div className="grid two">
        <div className="card">
          <div className="kv">
            <b>Active</b><span>{model?.active_model || "unloaded"}</span>
            <b>Quantization</b><span>{model?.quantization}</span>
            <b>Context</b><span>{model?.context_size}{model?.context_policy ? ` · ${model.context_policy}` : ""}</span>
            <b>Thinking</b><span>{model?.thinking_mode || "off"}</span>
            <b>Vision</b><span>{model?.vision ? "loaded" : "lazy / off"}</span>
            <b>Backend</b><span>{model?.inference_backend}</span>
            <b>GPU layers</b><span>{model?.gpu_layers}</span>
            <b>VRAM</b><span>{model?.vram_used_mib ? `${model.vram_used_mib} MiB` : "n/a"}</span>
            <b>RAM</b><span>{model?.ram_used_gb ? `${model.ram_used_gb} GB` : "n/a"}</span>
            <b>tok/s</b><span>{model?.tokens_per_second ?? "n/a"}</span>
            <b>Prompt tok/s</b><span>{model?.prompt_tokens_per_second ?? "n/a"}</span>
            <b>Load time</b><span>{model?.load_time_seconds ? `${model.load_time_seconds}s` : "n/a"}</span>
            <b>Vision</b><span>{model?.vision_loaded ? "projector loaded" : (model?.vision || "lazy")}</span>
            <b>Thinking</b><span>{model?.thinking ? "profile allows (selective per turn)" : "off"}</span>
            <b>Task success</b><span>{pct(outcomes?.task_success_rate)} ({outcomes?.tasks_completed || 0} ok / {outcomes?.tasks_failed || 0} failed)</span>
            <b>State</b><span>{model?.loaded ? "loaded" : model?.loading ? "loading" : "unloaded"}</span>
          </div>
        </div>
        <div className="card">
          <h2>Profiles</h2>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => load("fast")}>Fast</button>
            <button className="btn" disabled={busy} onClick={() => load("balanced")}>Balanced</button>
            <button className="btn" disabled={busy} onClick={() => load("quality")}>Quality</button>
            <button className="btn secondary" disabled={busy} onClick={() => api("/api/model/unload", { method: "POST" }).then(refresh)}>Unload</button>
            <button className="btn secondary" disabled={busy} onClick={snapshot}>Record snapshot</button>
          </div>
          <p className="lede" style={{ marginTop: 16 }}>
            Fast: Q4_K_M, thinking off, 16K cap, no vision projector.<br />
            Balanced: Q4_K_M, selective thinking, dynamic 8K–32K context.<br />
            Quality: Q5_K_M, selective thinking, hybrid GPU/CPU. Vision loads only for screenshot/GUI work.
          </p>
        </div>
      </div>
      <AgentSuiteCard />
      <HardwareGateCard />
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

type SuiteTask = { id: string; title: string; category: string; live_requires?: string }
type Gate = {
  purchase_allowed?: boolean
  recommendation?: string
  bottlenecks?: string[]
  inference_samples?: number
  agent_results?: number
  deferred_until_measured?: string[]
}

function AgentSuiteCard() {
  const [report, setReport] = useState<any>(null)
  useEffect(() => { api("/api/model/agent-benchmarks").then(setReport).catch(() => undefined) }, [])
  const tasks: SuiteTask[] = report?.suite || []
  const comparison = report?.comparison
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>20-task agent suite</h2>
      <p className="lede">
        Representative autonomous tasks used to compare models. Primary metric: successful tasks per hour — not tok/s.
        {report?.coverage ? ` Catalog has ${report.coverage.task_count} tasks.` : ""} {report?.live_status}
      </p>
      {comparison?.winner && (
        <p>Current recorded leader: <strong>{comparison.winner}</strong> ({comparison.primary_metric}).</p>
      )}
      {tasks.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Id</th>
              <th>Task</th>
              <th>Category</th>
              <th>Live needs</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td>{task.id}</td>
                <td>{task.title}</td>
                <td>{task.category}</td>
                <td>{task.live_requires || "unit-testable"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function HardwareGateCard() {
  const [gate, setGate] = useState<Gate | null>(null)
  useEffect(() => { api<Gate>("/api/model/hardware-gate").then(setGate).catch(() => undefined) }, [])
  if (!gate) return null
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Hardware purchasing gate</h2>
      <p className="lede">{gate.recommendation}</p>
      <div className="kv">
        <b>Purchases allowed</b><span>{gate.purchase_allowed ? "yes" : "no — measure first"}</span>
        <b>Inference samples</b><span>{gate.inference_samples ?? 0}</span>
        <b>Agent results</b><span>{gate.agent_results ?? 0}</span>
      </div>
      <ul>
        {(gate.bottlenecks || []).map((item) => <li key={item}>{item}</li>)}
      </ul>
      {!!gate.deferred_until_measured?.length && (
        <p className="lede">Deferred until measured: {gate.deferred_until_measured.join(", ")}.</p>
      )}
    </div>
  )
}
