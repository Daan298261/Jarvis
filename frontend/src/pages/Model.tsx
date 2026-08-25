import { useEffect, useState } from "react"
import { api } from "../api"

type Benchmark = {
  profile: string
  tokens_per_second?: number | null
  prompt_tokens_per_second?: number | null
  vram_used_mib?: number | null
  ram_used_gb?: number | null
  load_time_seconds?: number | null
  quant?: string
  quantization?: string
  context_size?: number
  thinking?: boolean | null
  recorded_at?: string
  updated_at?: string
}

type ProfileInfo = {
  name: string
  label: string
  quant?: string
  thinking?: boolean
  context_size?: number
  description?: string
  family?: string
  alias?: string
}

type ModelStatus = {
  active_model?: string
  quantization?: string
  context_size?: number
  inference_backend?: string
  remote?: boolean
  base_url?: string
  model?: string
  host?: string
  port?: number
  api_key_configured?: boolean
  gpu_layers?: string
  vram_used_mib?: number | null
  ram_used_gb?: number | null
  tokens_per_second?: number | null
  prompt_tokens_per_second?: number | null
  load_time_seconds?: number | null
  loaded?: boolean
  loading?: boolean
  profile?: string
  metrics_persisted?: boolean
  benchmarks?: Benchmark[]
  profiles?: ProfileInfo[]
}

type SettingsPayload = {
  inference?: {
    backend?: string
    host?: string
    port?: number
    base_url?: string
    model?: string
  }
  inference_remote?: boolean
  inference_api_key_configured?: boolean
}

function fmt(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a"
  return `${value}`
}

function stamp(row: Benchmark) {
  const raw = row.updated_at || row.recorded_at || ""
  return raw ? raw.replace("T", " ").slice(0, 19) : "—"
}

export function ModelPage() {
  const [model, setModel] = useState<ModelStatus | null>(null)
  const [machine, setMachine] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [mode, setMode] = useState<"local" | "remote">("local")
  const [host, setHost] = useState("127.0.0.1")
  const [port, setPort] = useState(8088)
  const [baseUrl, setBaseUrl] = useState("")
  const [remoteModel, setRemoteModel] = useState("Qwen3.5-9B-Abliterated")
  const [keyConfigured, setKeyConfigured] = useState(false)

  async function refresh() {
    const status = await api<ModelStatus>("/api/model")
    setModel(status)
    return status
  }

  useEffect(() => {
    refresh()
    api<{ hardware_view?: { summary?: string; recommendation?: string } }>("/api/system")
      .then((sys) => {
        const summary = sys.hardware_view?.summary
        const rec = sys.hardware_view?.recommendation
        setMachine([summary, rec].filter(Boolean).join(" "))
      })
      .catch(() => undefined)
    api<SettingsPayload>("/api/settings")
      .then((settings) => {
        const inf = settings.inference || {}
        const remote = Boolean(settings.inference_remote || (inf.backend && inf.backend !== "llama.cpp"))
        setMode(remote ? "remote" : "local")
        setHost(inf.host || "127.0.0.1")
        setPort(inf.port || 8088)
        setBaseUrl(inf.base_url || "")
        setRemoteModel(inf.model || "Qwen3.5-9B-Abliterated")
        setKeyConfigured(Boolean(settings.inference_api_key_configured))
      })
      .catch(() => undefined)
  }, [])

  async function load(profile: string) {
    setBusy(true)
    setError("")
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ inference_backend: "llama.cpp", profile }),
      })
      setMode("local")
      await api("/api/model/load", { method: "POST", body: JSON.stringify({ profile }) })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed")
    } finally {
      setBusy(false)
    }
  }

  async function connectRemote() {
    setBusy(true)
    setError("")
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          inference_backend: "openai-compat",
          inference_host: host,
          inference_port: Number(port),
          inference_base_url: baseUrl,
          inference_model: remoteModel,
        }),
      })
      setMode("remote")
      await api("/api/model/load", { method: "POST", body: JSON.stringify({}) })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connect failed")
    } finally {
      setBusy(false)
    }
  }

  async function measure() {
    setBusy(true)
    setError("")
    try {
      await api("/api/model/benchmark", { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Benchmark failed")
    } finally {
      setBusy(false)
    }
  }

  const rows = model?.benchmarks || []
  const remote = Boolean(model?.remote || mode === "remote")
  const officialProfiles = (model?.profiles || []).filter((row) => (row.family || "official") === "official")
  const unrestrictedProfiles = (model?.profiles || []).filter((row) => row.family === "unrestricted")
  const abliteratedProfiles = (model?.profiles || []).filter((row) => row.family === "abliterated")
  const officialButtons = officialProfiles.length
    ? officialProfiles
    : [
        { name: "fast", label: "Fast" },
        { name: "balanced", label: "Balanced" },
        { name: "quality", label: "Quality" },
      ]

  return (
    <div>
      <h1>Model</h1>
      <p className="lede">Default is local Qwen3.5 9B Abliterated Q6_K via llama.cpp on this PC. You can point Jarvis at another OpenAI-compatible `/v1` host without changing the agent. Model profiles change context and thinking. Agent Fast / Balanced / Reliable execution modes are a separate setting on Command and Settings.</p>
      {machine ? <p className="lede">{machine}</p> : null}
      <div className="grid two">
        <div className="card">
          <div className="kv">
            <b>Active</b><span>{model?.active_model || "unloaded"}</span>
            <b>Quantization</b><span>{model?.quantization}</span>
            <b>Context</b><span>{model?.context_size}</span>
            <b>Backend</b><span>{model?.inference_backend}</span>
            <b>Endpoint</b><span>{model?.base_url || "n/a"}</span>
            <b>GPU layers</b><span>{model?.gpu_layers}</span>
            <b>VRAM</b><span>{model?.vram_used_mib ? `${model.vram_used_mib} MiB` : "n/a"}</span>
            <b>RAM</b><span>{model?.ram_used_gb ? `${model.ram_used_gb} GB` : "n/a"}</span>
            <b>tok/s</b><span>{model?.tokens_per_second ?? "n/a"}</span>
            <b>Prompt tok/s</b><span>{model?.prompt_tokens_per_second ?? "n/a"}</span>
            <b>Load time</b><span>{model?.load_time_seconds ? `${model.load_time_seconds}s` : "n/a"}</span>
            <b>State</b><span>{model?.loaded ? (remote ? "connected" : "loaded") : model?.loading ? "loading" : "unloaded"}</span>
          </div>
        </div>
        <div className="card">
          <h2>Recommended: Abliterated 9B</h2>
          {abliteratedProfiles.length ? (
            <>
              <div className="row">
                {abliteratedProfiles.map((row) => (
                  <button key={row.name} className="btn" disabled={busy} onClick={() => load(row.name)}>{row.label}</button>
                ))}
              </div>
              <p className="lede" style={{ marginTop: 12 }}>
                Q6_K stays fully GPU-resident for faster agent/tool loops. Fast disables thinking at 16K; Balanced enables thinking at 32K.
              </p>
            </>
          ) : (
            <p className="lede">Qwen3.5 9B Abliterated is not on disk yet. Download it into `models/Qwen3.5-9B-Abliterated-GGUF`.</p>
          )}
          <h2 style={{ marginTop: 20 }}>Official 27B profiles</h2>
          <div className="row">
            {officialButtons.map((row) => (
              <button key={row.name} className="btn" disabled={busy} onClick={() => load(row.name)}>{row.label}</button>
            ))}
            <button className="btn secondary" disabled={busy} onClick={() => api("/api/model/unload", { method: "POST" }).then(refresh)}>Unload</button>
            <button className="btn secondary" disabled={busy || !model?.loaded} onClick={measure}>Measure tok/s</button>
          </div>
          <p className="lede" style={{ marginTop: 16 }}>
            Fast: official Q4_K_M, thinking off, 16K context.<br />
            Balanced: official Q4_K_M, thinking on, 32K context.<br />
            Quality: official Q5_K_M, thinking on, hybrid GPU/CPU.<br />
            These buttons keep the original 27B weights available as a fallback.
          </p>
          {unrestrictedProfiles.length ? (
            <>
              <h2 style={{ marginTop: 20 }}>Unrestricted (beside official)</h2>
              <div className="row">
                {unrestrictedProfiles.map((row) => (
                  <button key={row.name} className="btn secondary" disabled={busy} onClick={() => load(row.name)}>{row.label}</button>
                ))}
              </div>
              <p className="lede" style={{ marginTop: 12 }}>
                HauhauCS Unrestricted Qwen 27B GGUF in `models/Qwen3.5-27B-Unrestricted-GGUF`. Loading it unloads the official weights from VRAM; files stay side by side.
              </p>
            </>
          ) : (
            <p className="lede" style={{ marginTop: 16 }}>Unrestricted Qwen 27B is not on disk yet. Download into `models/Qwen3.5-27B-Unrestricted-GGUF` to enable these buttons.</p>
          )}
          {error ? <p className="lede" style={{ color: "var(--bad)" }}>{error}</p> : null}
        </div>
      </div>
      <div className="card" style={{ marginTop: 16, maxWidth: 720 }}>
        <h2>Remote OpenAI-compatible host</h2>
        <p className="lede">Connect to llama.cpp, vLLM, or another `/v1/chat/completions` server on the LAN. Prompts go to the host you enter. A local llama-server process still binds 127.0.0.1 only. Optional API key: set `JARVIS_INFERENCE_API_KEY` in the environment (never stored in settings.json).</p>
        <div className="grid" style={{ maxWidth: 560 }}>
          <label>Host
            <input type="text" value={host} onChange={(e) => setHost(e.target.value)} placeholder="192.168.1.50" />
          </label>
          <label>Port
            <input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} />
          </label>
          <label>Base URL (optional, overrides host/port)
            <input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://192.168.1.50:8080/v1" />
          </label>
          <label>Model name
            <input type="text" value={remoteModel} onChange={(e) => setRemoteModel(e.target.value)} />
          </label>
        </div>
        <p className="lede">API key: {keyConfigured ? "set in environment" : "not set (sends key `local`)"}</p>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={busy} onClick={connectRemote}>Connect</button>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Saved benchmarks</h2>
        <p className="lede">Last measured tok/s, VRAM, and load time for each profile. Values stay after unload or restart.</p>
        {rows.length ? (
          <table>
            <thead>
              <tr>
                <th>Profile</th>
                <th>tok/s</th>
                <th>Prompt tok/s</th>
                <th>VRAM</th>
                <th>Load time</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.profile}>
                  <td>
                    {row.profile}
                    {(row.quantization || row.quant) ? <span className="lede" style={{ display: "block", margin: 0 }}>{row.quantization || row.quant}</span> : null}
                  </td>
                  <td>{fmt(row.tokens_per_second)}</td>
                  <td>{fmt(row.prompt_tokens_per_second)}</td>
                  <td>{row.vram_used_mib ? `${row.vram_used_mib} MiB` : "n/a"}</td>
                  <td>{row.load_time_seconds ? `${row.load_time_seconds}s` : "n/a"}</td>
                  <td>{stamp(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="lede">No saved measurements yet. Load a profile or run Measure tok/s to record tok/s, VRAM, and load time.</p>
        )}
      </div>
    </div>
  )
}
