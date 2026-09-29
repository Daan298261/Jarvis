import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  api,
  type BlackGridJob,
  type BlackGridOutput,
  type BlackGridStatus,
} from "../api"
import { BlackGridProjectStack } from "../vendor/shipnotes/BlackGridProjectStack"
import { ShipNotesSignalOrb } from "../vendor/shipnotes/ShipNotesSignalOrb"
import { ensureShipNotesScripts } from "../vendor/shipnotes/loadShipNotesScripts"

function signalState(status: BlackGridStatus | null): "listening" | "thinking" | "searching" | "done" {
  if (!status?.module.installed) return "thinking"
  if (status.module.install_status === "installing") return "searching"
  if (status.module.running) return "done"
  return "listening"
}

export function BlackGridStudioPage() {
  const [status, setStatus] = useState<BlackGridStatus | null>(null)
  const [prompt, setPrompt] = useState("")
  const [chunkFrames, setChunkFrames] = useState(39)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [jobs, setJobs] = useState<BlackGridJob[]>([])
  const [outputs, setOutputs] = useState<BlackGridOutput[]>([])

  const refresh = useCallback(async () => {
    setError("")
    try {
      const snap = await api<BlackGridStatus>("/api/blackgrid/status")
      setStatus(snap)
      const jobList = await api<{ jobs: BlackGridJob[] }>("/api/blackgrid/jobs")
      setJobs(jobList.jobs || [])
      const out = await api<{ outputs: BlackGridOutput[] }>("/api/blackgrid/outputs")
      setOutputs(out.outputs || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load BlackGrid studio")
    }
  }, [])

  useEffect(() => {
    void ensureShipNotesScripts().catch(() => {})
    void refresh()
    const timer = window.setInterval(() => void refresh(), 8000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const comfyUrl = status?.module.comfy_ui_url || "http://127.0.0.1:8188"

  function openComfyTab() {
    window.open(comfyUrl, "_blank", "noopener,noreferrer")
  }

  async function installStudio() {
    setBusy(true)
    setError("")
    try {
      await api("/api/blackgrid/install", { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Install failed")
    } finally {
      setBusy(false)
    }
  }

  async function startStudio() {
    setBusy(true)
    try {
      await api("/api/blackgrid/start", { method: "POST" })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Start failed")
    } finally {
      setBusy(false)
    }
  }

  async function submitJob() {
    if (!prompt.trim()) {
      setError("Enter a production prompt for HR Endless Sampler.")
      return
    }
    setBusy(true)
    setError("")
    try {
      await api("/api/blackgrid/jobs", {
        method: "POST",
        body: JSON.stringify({ prompt: prompt.trim(), chunk_frames: chunkFrames }),
      })
      await refresh()
      if (status?.module.running) openComfyTab()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Queue failed")
    } finally {
      setBusy(false)
    }
  }

  const caps = status?.capabilities

  return (
    <div className="page blackgrid-studio-page">
      <header className="page-header">
        <h1>BlackGrid Multimedia Studio</h1>
        <p className="lede">
          Primary creative workbench — ComfyUI with{" "}
          <strong>HR Endless Sampler</strong> (MiniMax H3 long-form video). Input prompts here; outputs
          land under ComfyUI and appear below.
        </p>
        <p className="lede">
          <Link to="/memory">← Memory / modules</Link>
          {" · "}
          <button type="button" className="linkish" onClick={openComfyTab}>
            Open ComfyUI in new tab
          </button>
        </p>
      </header>

      {error ? (
        <p className="lede" role="alert">
          {error}
        </p>
      ) : null}

      <div className="card grid" style={{ marginBottom: 16 }}>
        <div className="row" style={{ alignItems: "center", gap: 16 }}>
          <ShipNotesSignalOrb state={signalState(status)} level={caps?.available ? 0.85 : 0.35} size={100} />
          <div>
            <p style={{ margin: 0 }}>
              <b>Status</b>{" "}
              {caps?.available ? "Ready" : status?.module.installed ? "Installed · start ComfyUI" : "Not installed"}
            </p>
            <p className="lede" style={{ margin: "6px 0 0" }}>
              {caps?.detail || status?.module.install_error || "Install BlackGrid to enable local video generation."}
            </p>
          </div>
        </div>
        <div className="row" style={{ flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          {!status?.module.installed ? (
            <button type="button" disabled={busy} onClick={() => void installStudio()}>
              Install BlackGrid + HR Endless
            </button>
          ) : null}
          {status?.module.installed && !status.module.running ? (
            <button type="button" disabled={busy} onClick={() => void startStudio()}>
              Start ComfyUI
            </button>
          ) : null}
          <button type="button" disabled={busy} onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      </div>

      <section className="card" style={{ marginBottom: 16 }}>
        <h2>Input — HR Endless production prompt</h2>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={12}
          style={{ width: "100%", fontFamily: "inherit" }}
          placeholder="integrated_multimodal_description: … subject_definitions … detailed_description with [Shot N] blocks …"
        />
        <label className="row" style={{ marginTop: 8, gap: 8, alignItems: "center" }}>
          <span>chunk_frames</span>
          <input
            type="number"
            min={5}
            max={120}
            value={chunkFrames}
            onChange={(e) => setChunkFrames(Number(e.target.value) || 39)}
            style={{ width: 80 }}
          />
          <span className="lede" style={{ margin: 0 }}>
            Lower = less VRAM per H3 chunk (39 is a practical 1080p starting point on 16 GB).
          </span>
        </label>
        <div className="row" style={{ marginTop: 12, gap: 8 }}>
          <button type="button" disabled={busy || !caps?.available} onClick={() => void submitJob()}>
            Queue in ComfyUI
          </button>
          <button type="button" onClick={openComfyTab}>
            Open graph (new tab)
          </button>
        </div>
      </section>

      <section className="card" style={{ marginBottom: 16 }}>
        <h2>Recent jobs</h2>
        {jobs.length === 0 ? (
          <p className="lede">No queued jobs yet.</p>
        ) : (
          <ul>
            {jobs.slice(0, 8).map((job) => (
              <li key={job.prompt_id || job.id}>
                <code>{job.prompt_id || job.id}</code> — {job.status} — {job.prompt_excerpt}
              </li>
            ))}
          </ul>
        )}
      </section>

      <BlackGridProjectStack />

      <section className="card">
        <h2>Output — rendered media</h2>
        {outputs.length === 0 ? (
          <p className="lede">Outputs appear here when ComfyUI writes to its output folder.</p>
        ) : (
          <ul>
            {outputs.map((file) => (
              <li key={file.path}>
                <strong>{file.name}</strong> ({Math.round(file.size_bytes / 1024)} KB)
                {file.name.match(/\.(mp4|webm)$/i) ? (
                  <div style={{ marginTop: 8 }}>
                    <video controls style={{ maxWidth: "100%", maxHeight: 360 }} src={`/api/blackgrid/output-file?path=${encodeURIComponent(file.path)}`} />
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
