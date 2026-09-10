import { useEffect, useState } from "react"
import { api, getPrivateKey } from "../api"
import { CompanionPairingPanel } from "../components/CompanionPairingPanel"

type Device = { id: string; name: string; status: string; fingerprint: string }
type Build = { id: string; state: string; activity: string; worker?: string; stale?: boolean; heartbeat_at?: number; started_at: number; updated_at: number; result?: { sha256: string } }
type Connection = { state: string; activity: string; endpoints: string[]; server_pin?: string; router?: string; limitation?: string; local_verified?: boolean; remote_verified?: boolean; updated_at?: number }

export function MobileCompanionSetup() {
  const [devices, setDevices] = useState<Device[]>([])
  const [endpoint, setEndpoint] = useState("")
  const [connection, setConnection] = useState<Connection | null>(null)
  const [remote, setRemote] = useState(true)
  const [build, setBuild] = useState<Build | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const buildId = build?.id
  const buildState = build?.state
  const refresh = () => api<Device[]>("/api/mobile/manage/devices").then(setDevices)
  useEffect(() => {
    const tick = () => {
      refresh().catch(() => undefined)
      api<Connection>("/api/mobile/manage/connection").then(setConnection).catch(() => undefined)
    }
    tick()
    const interval = window.setInterval(tick, 5000)
    return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    if (!buildId || !buildState || ["completed", "failed"].includes(buildState)) return
    const interval = window.setInterval(() => {
      api<Build>(`/api/mobile/manage/builds/${buildId}`).then(setBuild).catch((err) => setError(String(err)))
    }, 2000)
    return () => window.clearInterval(interval)
  }, [buildId, buildState])
  async function run(action: () => Promise<unknown>) {
    setError(""); setBusy(true)
    try { await action(); await refresh() } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  async function download() {
    if (!build) return
    const response = await fetch(`/api/mobile/manage/builds/${build.id}/apk`, { headers: { "X-Jarvis-Key": getPrivateKey() } })
    if (!response.ok) throw new Error("Unable to download APK")
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "Jarvis.apk"; anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
  return <section className="card" style={{ marginBottom: 20 }}>
    <h2>Android companion</h2>
    <p className="lede">Build your personalized app, then confirm the phone’s fingerprint here. Each phone gets its own revocable identity.</p>
    <label><input type="checkbox" checked={remote} onChange={(event) => setRemote(event.target.checked)} /> Enable encrypted internet access when supported</label>
    <div className="row" style={{ gap: 10, marginTop: 12 }}>
      <button className="btn" disabled={busy} onClick={() => run(async () => setConnection(await api<Connection>("/api/mobile/manage/connection", { method: "POST", body: JSON.stringify({ enabled: true, remote }) })))}>Prepare connection</button>
      {connection?.state === "ready" && <button className="btn secondary" disabled={busy} onClick={() => run(async () => setConnection(await api<Connection>("/api/mobile/manage/connection", { method: "POST", body: JSON.stringify({ enabled: false, remote: false }) })))}>Stop mobile access</button>}
    </div>
    {connection && <div role="status" style={{ marginTop: 12 }}>
      <strong>{connection.state}</strong> · {connection.activity}
      {connection.local_verified && <p>Desktop encryption and device authentication verified. Test the phone on Wi-Fi next.</p>}
      {connection.remote_verified && <p>Hosted fallback reached this Jarvis gateway.</p>}
      {connection.limitation && <p>{connection.limitation}</p>}
      {connection.endpoints.map((address) => <div key={address}><code>{address}</code></div>)}
      {connection.server_pin && <details><summary>Server fingerprint</summary><code style={{ overflowWrap: "anywhere" }}>{connection.server_pin}</code></details>}
    </div>}
    <details style={{ marginTop: 12 }}><summary>Custom connection address</summary>
      <label>Encrypted Jarvis endpoint<input className="command" value={endpoint} placeholder={connection?.endpoints[0] || "https://your-jarvis-host:4781"} onChange={(event) => setEndpoint(event.target.value)} /></label>
    </details>
    <div className="row" style={{ gap: 10, flexWrap: "wrap", marginTop: 12 }}>
      <button className="btn" disabled={busy || (!endpoint && !connection?.endpoints.length) || (!!build && ["queued", "running"].includes(build.state))} onClick={() => run(async () => setBuild(await api<Build>("/api/mobile/manage/builds", { method: "POST", body: JSON.stringify({ endpoint }) })))}>Build Android APK</button>
    </div>
    <div style={{ marginTop: 16 }}><CompanionPairingPanel compact /></div>
    {build && <div role="status" style={{ marginTop: 12 }}>
      <strong>{build.state}</strong> · {build.activity}<br />
      <small>{build.worker || "Android builder"} · Started {new Date(build.started_at * 1000).toLocaleTimeString()} · Last progress {new Date((build.heartbeat_at || build.updated_at) * 1000).toLocaleTimeString()}</small>
      {build.stale && <p>No recent build heartbeat. Jarvis will mark an interrupted build failed after restart.</p>}
      {build.state === "completed" && <button className="btn" onClick={() => run(download)}>Download signed APK</button>}
    </div>}
    {error && <p role="alert">{error}</p>}
    {devices.map((device) => <div key={device.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 12 }}>
      <strong>{device.name}</strong> · {device.status}
      <p style={{ overflowWrap: "anywhere", fontFamily: "monospace" }}>{device.fingerprint.match(/.{1,8}/g)?.join(" ")}</p>
      {device.status === "pending" && <button className="btn" disabled={busy} onClick={() => run(() => api(`/api/mobile/manage/devices/${device.id}/confirm`, { method: "POST", body: JSON.stringify({ fingerprint: device.fingerprint }) }))}>Fingerprint matches — approve phone</button>}
      {device.status !== "revoked" && <button className="btn secondary" disabled={busy} onClick={() => run(() => api(`/api/mobile/manage/devices/${device.id}/revoke`, { method: "POST" }))}>Revoke phone</button>}
    </div>)}
  </section>
}
