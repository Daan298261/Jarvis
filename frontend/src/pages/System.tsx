import { useEffect, useState } from "react"
import { api } from "../api"

type HardwareItem = { label: string; value: string }
type HardwareGroup = { id: string; label: string; items: HardwareItem[] }
type AutonomyMode = { name: string; label: string; description: string; confirms: string }
type Worker = { name: string; label: string; available: boolean; reason: string }

type SystemInfo = {
  hardware_view?: {
    summary?: string
    recommendation?: string
    groups?: HardwareGroup[]
  }
  hardware?: Record<string, unknown>
  autonomy_mode?: AutonomyMode
  execution_mode?: string
  workers?: Worker[]
  model?: { loaded?: boolean; quantization?: string; profile?: string; vram_used_mib?: number | null }
  bind_host?: string
  bind_port?: number
  lan_access?: boolean
  auth_token_configured?: boolean
  voice?: {
    stt?: { available?: boolean; engine?: string; reason?: string }
    tts?: { available?: boolean; engine?: string; reason?: string }
  }
}

export function SystemPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  useEffect(() => { api<SystemInfo>("/api/system").then(setInfo) }, [])
  const view = info?.hardware_view
  const groups = view?.groups || []
  const workers = info?.workers || []
  return (
    <div>
      <h1>System</h1>
      <p className="lede">{view?.summary || "Detected hardware used to tune local inference."}</p>
      {view?.recommendation ? <p className="lede">{view.recommendation}</p> : null}
      <div className="grid cards">
        {groups.map((group) => (
          <div className="card" key={group.id}>
            <h2>{group.label}</h2>
            <div className="kv">
              {group.items.map((item) => (
                <span key={item.label} style={{ display: "contents" }}>
                  <b>{item.label}</b><span>{item.value}</span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Autonomy</h2>
          <p>
            <strong>{info?.autonomy_mode?.label || info?.autonomy_mode?.name || "—"}</strong>
          </p>
          <p className="lede">{info?.autonomy_mode?.description}</p>
          <p className="lede">Confirms {info?.autonomy_mode?.confirms || "—"}. Change this on Settings. Execution mode is {info?.execution_mode || "balanced"} (agent loop, not the model profile).</p>
        </div>
        <div className="card">
          <h2>Inference now</h2>
          <div className="kv">
            <b>Model</b><span>{info?.model?.loaded ? "loaded" : "unloaded"}</span>
            <b>Profile</b><span>{info?.model?.profile || "—"}</span>
            <b>Quant</b><span>{info?.model?.quantization || "—"}</span>
            <b>VRAM in use</b><span>{info?.model?.vram_used_mib ? `${info.model.vram_used_mib} MiB` : "n/a"}</span>
            <b>API bind</b><span>{info?.bind_host || "127.0.0.1"}:{info?.bind_port || 4780}</span>
            <b>LAN</b><span>{info?.lan_access && info?.auth_token_configured ? "on (token required)" : info?.lan_access ? "requested, still localhost" : "off (localhost)"}</span>
            <b>Auth token</b><span>{info?.auth_token_configured ? "set" : "not set"}</span>
            <b>Whisper STT</b><span>{info?.voice?.stt?.available ? info.voice.stt.engine || "ready" : info?.voice?.stt?.reason || "—"}</span>
            <b>Local TTS</b><span>{info?.voice?.tts?.available ? info.voice.tts.engine || "ready" : info?.voice?.tts?.reason || "—"}</span>
          </div>
        </div>
      </div>
      {!!workers.length && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Workers</h2>
          {workers.map((worker) => (
            <div className="toggle" key={worker.name}>
              <div>
                <strong>{worker.label}</strong>
                <div className="lede" style={{ margin: "4px 0 0" }}>{worker.reason}</div>
              </div>
              <span className={`badge ${worker.available ? "completed" : "queued"}`}>
                {worker.available ? "available" : "unavailable"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
