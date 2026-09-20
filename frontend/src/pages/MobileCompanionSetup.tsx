import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  api,
  companionBuildPhase,
  fetchCompanionOnboarding,
  startCompanionBuild,
  type CompanionBuildJob,
  type CompanionOnboardingSnapshot,
} from "../api"
import { CompanionApkBuildPanel } from "../components/CompanionApkBuildPanel"
import { CompanionPairingPanel } from "../components/CompanionPairingPanel"

type Device = { id: string; name: string; status: string; fingerprint: string }
type Connection = {
  state: string
  activity: string
  endpoints: string[]
  server_pin?: string
  router?: string
  limitation?: string
  local_verified?: boolean
  remote_verified?: boolean
  updated_at?: number
}

function gatewayTroubleshooting(connection: Connection | null): string | null {
  if (!connection) {
    return "Prepare connection starts the TLS gateway on port 4781. The phone never talks to the portal on :4780 directly."
  }
  if (connection.state === "failed") {
    return (
      "Gateway failed to start. On Windows, allow inbound TCP 4781 on your private network profile, " +
      "ensure nothing else is using port 4781, and confirm Jarvis is running on localhost:4780."
    )
  }
  if (connection.state === "ready" && connection.endpoints.length === 0) {
    return "No phone-reachable LAN address was found. Connect this PC to Wi‑Fi, then Prepare connection again."
  }
  if (connection.limitation) {
    return connection.limitation
  }
  if (connection.state !== "ready" && connection.state !== "running") {
    return "Prepare connection before pairing. Copy the server fingerprint into the phone when prompted."
  }
  return null
}

export function MobileCompanionSetup() {
  const [devices, setDevices] = useState<Device[]>([])
  const [endpoint, setEndpoint] = useState("")
  const [connection, setConnection] = useState<Connection | null>(null)
  const [remote, setRemote] = useState(false)
  const [build, setBuild] = useState<CompanionBuildJob | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [onboarding, setOnboarding] = useState<CompanionOnboardingSnapshot | null>(null)

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
    fetchCompanionOnboarding()
      .then(setOnboarding)
      .catch(() => setOnboarding(null))
  }, [])

  async function run(action: () => Promise<unknown>) {
    setError("")
    setBusy(true)
    try {
      await action()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function startBuild(mode: "personalized" | "generic") {
    const created = await startCompanionBuild({
      mode,
      endpoint: mode === "personalized" ? endpoint || connection?.endpoints[0] || "" : "",
      prepareConnection: mode === "personalized",
      remote,
    })
    setBuild(created)
    if (mode === "personalized") {
      api<Connection>("/api/mobile/manage/connection").then(setConnection).catch(() => undefined)
    }
  }

  async function retryBuild() {
    const mode = build?.mode === "generic" ? "generic" : "personalized"
    await startBuild(mode)
  }

  const buildPhase = build ? companionBuildPhase(build.state) : null
  const buildLocked = buildPhase === "queued" || buildPhase === "building"
  const canStartPersonalized = !busy && !buildLocked
  const canStartGeneric = !busy && !buildLocked
  const gatewayHint = gatewayTroubleshooting(connection)

  return (
    <section className="card" style={{ marginBottom: 20 }}>
      <h2>Android companion</h2>
      <p className="lede">
        Generate the companion APK entirely from this page — prepare the connection when needed, watch build
        progress, then download or send. Use a generic APK for releases and sideload; pair in the app after
        install.
      </p>
      <label>
        <input type="checkbox" checked={remote} onChange={(event) => setRemote(event.target.checked)} /> Enable
        encrypted internet access when supported
      </label>
      <div className="row" style={{ gap: 10, marginTop: 12 }}>
        <button
          className="btn"
          disabled={busy}
          onClick={() =>
            run(async () =>
              setConnection(
                await api<Connection>("/api/mobile/manage/connection", {
                  method: "POST",
                  body: JSON.stringify({ enabled: true, remote }),
                }),
              ),
            )
          }
        >
          Prepare connection
        </button>
        {connection?.state === "ready" && (
          <button
            className="btn secondary"
            disabled={busy}
            onClick={() =>
              run(async () =>
                setConnection(
                  await api<Connection>("/api/mobile/manage/connection", {
                    method: "POST",
                    body: JSON.stringify({ enabled: false, remote: false }),
                  }),
                ),
              )
            }
          >
            Stop mobile access
          </button>
        )}
      </div>
      {connection && (
        <div role="status" style={{ marginTop: 12 }}>
          <strong>{connection.state}</strong> · {connection.activity}
          {connection.local_verified && (
            <p>Desktop encryption and device authentication verified. Test the phone on Wi-Fi next.</p>
          )}
          {connection.remote_verified && <p>Hosted fallback reached this Jarvis gateway.</p>}
          {gatewayHint && (
            <p className="companion-gateway-hint" role="note">
              {gatewayHint}
            </p>
          )}
          {connection.endpoints.map((address) => (
            <div key={address}>
              <code>{address}</code>
            </div>
          ))}
          {connection.server_pin && (
            <details>
              <summary>Server fingerprint</summary>
              <code style={{ overflowWrap: "anywhere" }}>{connection.server_pin}</code>
            </details>
          )}
        </div>
      )}
      <details style={{ marginTop: 12 }}>
        <summary>Custom connection address</summary>
        <label>
          Encrypted Jarvis endpoint
          <input
            className="command"
            value={endpoint}
            placeholder={connection?.endpoints[0] || "https://your-jarvis-host:4781"}
            onChange={(event) => setEndpoint(event.target.value)}
          />
        </label>
      </details>
      <div className="row" style={{ gap: 10, flexWrap: "wrap", marginTop: 12 }}>
        <button className="btn" disabled={!canStartPersonalized} onClick={() => run(() => startBuild("personalized"))}>
          {buildLocked && build?.mode !== "generic" ? "Build in progress…" : "Build personalized APK"}
        </button>
        <button className="btn secondary" disabled={!canStartGeneric} onClick={() => run(() => startBuild("generic"))}>
          {buildLocked && build?.mode === "generic" ? "Build in progress…" : "Build generic companion APK"}
        </button>
      </div>
      <p className="companion-apk-build-hint" style={{ marginTop: 8 }}>
        Personalized auto-prepares the connection when needed and bakes this desktop’s endpoints. Generic ships
        every companion feature and pairs with the 6-digit code / QR after install — use that for releases.
      </p>
      {build && (
        <CompanionApkBuildPanel
          build={build}
          onBuildChange={setBuild}
          onRetry={() => run(retryBuild)}
          busy={busy}
          onError={setError}
          onClearError={() => setError("")}
        />
      )}
      {!build && (
        <p className="companion-apk-build-hint" style={{ marginTop: 12 }}>
          Start a build above. Progress, Download to Desktop, and optional WhatsApp/email send appear here.
        </p>
      )}
      <div className="companion-offline-pair-cta" style={{ marginTop: 16 }}>
        <h3 style={{ marginBottom: 8 }}>Pair after install (offline-friendly)</h3>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Generic and sideload APKs pair on your LAN with the same 6-digit code and QR as this desktop — no
          rebuild required.
          {connection?.state !== "ready" &&
            " Prepare connection above first, then open the full pairing screen for the code and QR."}
          {onboarding && onboarding.paired_device_count === 0 && onboarding.connection.ready && (
            <> The live code below updates from the server.</>
          )}
        </p>
        <div className="row" style={{ gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
          <Link className="btn" to="/companion-pairing">Open pairing code + QR</Link>
          {connection?.state !== "ready" && (
            <button
              className="btn secondary"
              type="button"
              disabled={busy}
              onClick={() =>
                run(async () =>
                  setConnection(
                    await api<Connection>("/api/mobile/manage/connection", {
                      method: "POST",
                      body: JSON.stringify({ enabled: true, remote }),
                    }),
                  ),
                )
              }
            >
              Prepare connection for pairing
            </button>
          )}
        </div>
        <CompanionPairingPanel compact />
      </div>
      {error && <p role="alert">{error}</p>}
      {devices.map((device) => (
        <div key={device.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 12 }}>
          <strong>{device.name}</strong> · {device.status}
          <p style={{ overflowWrap: "anywhere", fontFamily: "monospace" }}>
            {device.fingerprint.match(/.{1,8}/g)?.join(" ")}
          </p>
          {device.status === "pending" && (
            <button
              className="btn"
              disabled={busy}
              onClick={() =>
                run(() =>
                  api(`/api/mobile/manage/devices/${device.id}/confirm`, {
                    method: "POST",
                    body: JSON.stringify({ fingerprint: device.fingerprint }),
                  }),
                )
              }
            >
              Fingerprint matches — approve phone
            </button>
          )}
          {device.status !== "revoked" && (
            <button
              className="btn secondary"
              disabled={busy}
              onClick={() => run(() => api(`/api/mobile/manage/devices/${device.id}/revoke`, { method: "POST" }))}
            >
              Revoke phone
            </button>
          )}
        </div>
      ))}
    </section>
  )
}
