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

type HarnessReport = {
  ran_at?: string | null
  model_available?: boolean
  blocked_reason?: string
  bottleneck?: string
  buy_hardware?: boolean
  hardware_recommendation?: string
  metrics?: {
    ttft_ms?: number | null
    tool_call_latency_ms?: number | null
    generation_tps?: number | null
    prompt_tps?: number | null
    vram_used_mib?: number | null
    ram_used_gb?: number | null
    cpu_utilization_percent?: number | null
    gpu_utilization_percent?: number | null
    load_time_seconds?: number | null
    context_size?: number | null
  }
  notes?: string[]
}

type ModelStatus = {
  active_model?: string
  family?: string
  thinking_mode?: string
  vision?: boolean
  quantization?: string
  context_size?: number
  context_cap?: number
  inference_backend?: string
  gpu_layers?: string
  vram_used_mib?: number
  ram_used_gb?: number
  tokens_per_second?: number
  prompt_tokens_per_second?: number
  load_time_seconds?: number
  loaded?: boolean
  loading?: boolean
  context_policy?: { live?: number; profile_cap?: number; note?: string }
  outcomes?: { tasks_completed: number; tasks_failed: number; task_success_rate: number | null }
  benchmarks?: Benchmark[]
  harness?: HarnessReport | null
}

function pct(value: number | null | undefined) {
  if (value == null) return "n/a"
  return `${Math.round(value * 1000) / 10}%`
}

export function ModelPage() {
  const [model, setModel] = useState<ModelStatus | null>(null)
  const [harness, setHarness] = useState<{ running?: boolean; report?: HarnessReport | null; matrix_size?: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [probe, setProbe] = useState<any>(null)

  async function refresh() {
    const [status, harnessStatus] = await Promise.all([
      api<ModelStatus>("/api/model"),
      api<{ running?: boolean; report?: HarnessReport | null; matrix_size?: number }>("/api/model/harness"),
    ])
    setModel(status)
    setHarness(harnessStatus)
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

  async function runHarness() {
    setBusy(true)
    try {
      await api("/api/model/harness/run", { method: "POST" })
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const outcomes = model?.outcomes
  const samples = model?.benchmarks || []
  const report = harness?.report
  const configPreview = (report?.configurations || []).slice(0, 8)
  const catalogPreview = (report?.agent_tasks || []).slice(0, 8)

  return (
    <div>
      <h1>Model</h1>
      <p className="lede">Local Qwen3.5-27B served by llama.cpp. Tasks start at 8K or 16K context and expand only when the live prompt is under pressure. Expert is a compact 27B consult, not the everyday loop. Benchmarks persist tok/s, VRAM, RAM, and task success so you can compare loads over time.</p>
      <div className="grid two">
        <div className="card">
          <div className="kv">
            <b>Active</b><span>{model?.active_model || "unloaded"}</span>
            <b>Family</b><span>{model?.family || "—"}</span>
            <b>Quantization</b><span>{model?.quantization}</span>
            <b>Context</b><span>{model?.context_size}</span>
            <b>Context cap</b><span>{model?.context_policy?.profile_cap ?? "n/a"}</span>
            <b>Backend</b><span>{model?.inference_backend}</span>
            <b>Endpoint</b><span>{model?.host ? `${model.host}:${model.port}` : "n/a"}</span>
            <b>Remote model</b><span>{model?.remote_model || "default"}</span>
            <b>Advertised</b><span>{(model?.advertised_models || []).join(", ") || "n/a"}</span>
            <b>Health path</b><span>{model?.health_path || "n/a"}</span>
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
          {model?.last_error ? <p className="lede" style={{ marginTop: 12 }}>{model.last_error}</p> : null}
        </div>
        <div className="card">
          <h2>Profiles</h2>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => load("fast")}>Fast</button>
            <button className="btn" disabled={busy} onClick={() => load("balanced")}>Balanced</button>
            <button className="btn" disabled={busy} onClick={() => load("quality")}>Quality</button>
            <button className="btn secondary" disabled={busy} onClick={() => load("expert")}>Expert 27B</button>
            <button className="btn secondary" disabled={busy} onClick={() => api("/api/model/unload", { method: "POST" }).then(refresh)}>Unload</button>
            <button className="btn secondary" disabled={busy} onClick={snapshot}>Record snapshot</button>
            <button className="btn secondary" disabled={busy} onClick={runHarness}>Run harness</button>
          </div>
          {probe && (
            <p className="lede" style={{ marginTop: 12 }}>
              Probe: {probe.ok ? "reachable" : "unreachable"} {probe.health_path || probe.error} {(probe.models || []).join(", ")}
            </p>
          )}
          <p className="lede" style={{ marginTop: 16 }}>
            Fast: Q4_K_M, thinking off, 16K context.<br />
            Balanced: Q4_K_M, thinking on, 32K context.<br />
            Quality: Q5_K_M, thinking on, hybrid GPU/CPU.<br />
            Expert: 27B escalation only — not for ordinary tool work.
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
      <AgentSuiteCard />
      <HardwareGateCard />
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Local harness matrix</h2>
        <p className="lede">
          Planned cases cover Fast/Balanced/Quality × 8K/16K/32K, vision on/off, and thinking off/selective/on.
          Live llama.cpp measurement is skipped here unless the GGUF and server exist.
        </p>
        {harness && (
          <p className="lede">
            Last run: {harness.measured_cases || 0} measured / {harness.skipped_cases || 0} skipped
            {harness.warning ? ` — ${harness.warning}` : ""}
          </p>
        )}
        <table>
          <thead>
            <tr>
              <th>Profile</th>
              <th>Context</th>
              <th>Vision</th>
              <th>Thinking</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(harness?.cases || (model?.harness_cases || []).map((row) => ({ ...row, status: "planned", skip_reason: "" }))).map((row, index) => (
              <tr key={`${row.profile}-${row.context_size}-${row.vision}-${row.thinking}-${index}`}>
                <td>{row.profile}</td>
                <td className="stat">{row.context_size}</td>
                <td>{row.vision ? "on" : "off"}</td>
                <td>{row.thinking}</td>
                <td>{row.status}{row.skip_reason ? ` (${row.skip_reason})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Local benchmark harness</h2>
        <p className="lede">
          {harness?.matrix_size || 0} model configurations × {report?.agent_catalog_size || 20} realistic agent tasks.
          Missing GGUFs are skipped. Live mode measures only the currently loaded configuration so it will not swap models.
        </p>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="btn" disabled={busy || harness?.running} onClick={() => runHarness(false)}>Preview matrix</button>
          <button className="btn secondary" disabled={busy || harness?.running} onClick={() => runHarness(true)}>Measure loaded model</button>
        </div>
        {report && (
          <div className="kv">
            <b>Last run</b><span>{report.created_at?.replace("T", " ").slice(0, 19) || "—"}</span>
            <b>Measured</b><span>{report.measured ?? 0} measured / {report.skipped ?? 0} skipped</span>
            <b>Primary metric</b><span>{report.primary_metric || "successful autonomous tasks per minute"}</span>
          </div>
        )}
        {configPreview.length > 0 && (
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Configuration</th>
                <th>Status</th>
                <th>Skip</th>
              </tr>
            </thead>
            <tbody>
              {configPreview.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.status}</td>
                  <td>{row.skip_reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {catalogPreview.length > 0 && (
          <p className="lede" style={{ marginTop: 12 }}>
            Agent catalog sample: {catalogPreview.map((row) => row.id).join(", ")}
          </p>
        )}
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Performance harness</h2>
        <p className="lede">
          Records load time, time-to-first-token, tok/s, VRAM/RAM, CPU/GPU use, context, and a local tool-stat probe.
          Hardware purchases stay gated until this has run on the Windows desktop with real GGUFs.
        </p>
        {model?.harness?.ran_at ? (
          <div className="kv" style={{ marginTop: 12 }}>
            <b>Last run</b><span>{model.harness.ran_at.replace("T", " ").slice(0, 19)}</span>
            <b>Model</b><span>{model.harness.model_available ? "loaded" : "not loaded"}</span>
            <b>Bottleneck</b><span>{model.harness.bottleneck || "unmeasured"}</span>
            <b>TTFT</b><span>{model.harness.metrics?.ttft_ms != null ? `${model.harness.metrics.ttft_ms} ms` : "n/a"}</span>
            <b>Tool probe</b><span>{model.harness.metrics?.tool_call_latency_ms != null ? `${model.harness.metrics.tool_call_latency_ms} ms` : "n/a"}</span>
            <b>CPU</b><span>{model.harness.metrics?.cpu_utilization_percent != null ? `${model.harness.metrics.cpu_utilization_percent}%` : "n/a"}</span>
            <b>GPU</b><span>{model.harness.metrics?.gpu_utilization_percent != null ? `${model.harness.metrics.gpu_utilization_percent}%` : "n/a"}</span>
            <b>Buy hardware</b><span>{model.harness.buy_hardware ? "maybe" : "no"}</span>
            <b>Gate</b><span>{model.harness.hardware_recommendation || "—"}</span>
          </div>
        ) : (
          <p className="lede" style={{ marginTop: 12 }}>No harness run yet. Use Run harness even without a loaded model to capture CPU/RAM and the purchase gate.</p>
        )}
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
      {gate && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Hardware purchasing gate</h2>
          <p className="lede">{gate.reason}</p>
          <div className="kv" style={{ marginTop: 12 }}>
            <b>Decision</b><span>{gate.purchase_recommended ? "purchase may be justified" : "defer purchase"}</span>
            <b>Bottleneck</b><span>{gate.bottleneck}</span>
            <b>GPU</b><span>{gate.gpu_name || "not detected"}</span>
            <b>VRAM saturated</b><span>{gate.gpu_vram_saturated ? "yes" : "no"}</span>
            <b>CPU offload</b><span>{gate.cpu_offload_likely ? "likely" : "no"}</span>
            <b>RAM constrained</b><span>{gate.system_ram_constrained ? "yes" : "no"}</span>
            <b>CPU inference</b><span>{gate.cpu_inference_limiting == null ? "unmeasured" : gate.cpu_inference_limiting ? "limiting" : "not limiting"}</span>
            <b>Model switching</b><span>{gate.model_switching_costly == null ? "unmeasured" : gate.model_switching_costly ? "costly" : "cheap"}</span>
            <b>More VRAM</b><span>{gate.estimated_benefit_more_vram || "not estimated until desktop benchmarks exist"}</span>
            <b>More RAM</b><span>{gate.estimated_benefit_more_ram || "not estimated until desktop benchmarks exist"}</span>
            <b>Agent suite</b><span>{gate.agent_suite_complete ? "complete" : `${gate.agent_suite_successes || 0}/20 desktop successes`}</span>
          </div>
          <p className="lede" style={{ marginTop: 12 }}>Deferred until then: {(gate.deferred_purchases || []).join(", ")}.</p>
          {!!gate.missing_evidence?.length && (
            <p className="lede">Missing evidence: {gate.missing_evidence.join("; ")}.</p>
          )}
        </div>
      )}
      {suite && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>20-task agent suite</h2>
          <p className="lede">
            Primary metric: {suite.primary_metric}. {suite.live_comparison_reason}
          </p>
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Category</th>
                <th>Tools</th>
                <th>Live needs</th>
              </tr>
            </thead>
            <tbody>
              {(suite.cases || []).map((row) => (
                <tr key={row.id}>
                  <td>{row.title}</td>
                  <td>{row.category}</td>
                  <td>{(row.expected_tools || []).join(", ")}</td>
                  <td>{(row.live_requires || []).join(", ") || "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
