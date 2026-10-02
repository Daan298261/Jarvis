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
import {
  EMPTY_WAN_FORM,
  connectionPrepareBody,
  wanFormFromSnapshot,
  wanPathLabel,
  type WanForm,
  type WanMethod,
} from "../companionWan"

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
  wan_path?: string
  wan?: Record<string, unknown>
  remote?: boolean
  updated_at?: number
}

function gatewayTroubleshooting(connection: Connection | null): string | null {
  if (!connection) {
    return "Prepare connection starts the TLS gateway on port 4781. The phone never talks to the portal on :4780 directly."
  }
  if (connection.state === "failed") {
    return (
      "Gateway failed to start. On Windows, allow inbound TCP 4781 (Jarvis adds a firewall rule on every profile), " +
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
  const [remote, setRemote] = useState(true)
  const [wanForm, setWanForm] = useState<WanForm>(EMPTY_WAN_FORM)
  const [build, setBuild] = useState<CompanionBuildJob | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [onboarding, setOnboarding] = useState<CompanionOnboardingSnapshot | null>(null)

  const refresh = () => api<Device[]>("/api/mobile/manage/devices").then(setDevices)

  function applyConnection(next: Connection) {
    setConnection(next)
    if (typeof next.remote === "boolean") setRemote(next.remote)
    setWanForm((current) => {
      const dirty = Boolean(
        current.ssh_host ||
          current.gateway_host ||
          current.ssh_user ||
          current.gateway_user ||
          current.ssh_identity_file ||
          current.gateway_identity_file ||
          current.wan_public_host,
      )
      if (dirty) return current
      const hydrated = wanFormFromSnapshot(next)
      return { ...hydrated, gateway_password: current.gateway_password }
    })
  }

  useEffect(() => {
    const tick = () => {
      refresh().catch(() => undefined)
      api<Connection>("/api/mobile/manage/connection").then(applyConnection).catch(() => undefined)
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
      endpoint: mode === "personalized" ? endpoint.trim() : "",
      prepareConnection: mode === "personalized",
      remote,
    })
    setBuild(created)
    if (mode === "personalized") {
      api<Connection>("/api/mobile/manage/connection").then(applyConnection).catch(() => undefined)
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
  const wanPath = wanPathLabel(connection?.wan_path, connection?.router)

  function patchWan<K extends keyof WanForm>(key: K, value: WanForm[K]) {
    setWanForm((current) => ({ ...current, [key]: value }))
  }

  async function prepareConnection(enabled: boolean, useRemote: boolean) {
    applyConnection(
      await api<Connection>("/api/mobile/manage/connection", {
        method: "POST",
        body: JSON.stringify(connectionPrepareBody(enabled, useRemote, wanForm)),
      }),
    )
  }

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
        encrypted internet access (TCP 4781 via UPnP, NAT-PMP, PCP, gateway SSH, or reverse tunnel)
      </label>
      {remote && (
        <div className="grid" style={{ marginTop: 12, gap: 8 }}>
          <p className="lede" style={{ margin: 0 }}>
            Off LAN the phone talks to TCP 4781 only. Auto tries UPnP (optional router logon), then
            NAT-PMP or PCP on this PC's gateway, then SSH into your OpenWrt gateway, then an SSH
            reverse tunnel to a host you control. Jarvis will not map 4780, SSH, or the router admin
            port.
          </p>
          <label>
            Reachability
            <select
              value={wanForm.wan_method}
              onChange={(event) => patchWan("wan_method", event.target.value as WanMethod)}
            >
              <option value="auto">Auto (UPnP, NAT-PMP/PCP, gateway SSH, reverse tunnel)</option>
              <option value="upnp">UPnP / IGD on this router</option>
              <option value="gateway_ssh">Log into the gateway over SSH (OpenWrt)</option>
              <option value="ssh_reverse">SSH reverse tunnel to my host</option>
            </select>
          </label>
          {(wanForm.wan_method === "auto" || wanForm.wan_method === "upnp" || wanForm.wan_method === "gateway_ssh") && (
            <>
              {(wanForm.wan_method === "auto" || wanForm.wan_method === "upnp") && (
              <label>
                Router IGD username (optional; blank uses admin if you set a password)
                <input
                  className="command"
                  value={wanForm.gateway_username}
                  autoComplete="username"
                  onChange={(event) => patchWan("gateway_username", event.target.value)}
                />
              </label>
              )}
              <label>
                Router password (optional IGD logon and OpenWrt SSH if no key; never shown after save)
                <input
                  className="command"
                  type="password"
                  value={wanForm.gateway_password}
                  autoComplete="current-password"
                  onChange={(event) => patchWan("gateway_password", event.target.value)}
                />
              </label>
            </>
          )}
          {(wanForm.wan_method === "auto" || wanForm.wan_method === "gateway_ssh") && (
            <>
              <label>
                Gateway SSH host (blank uses this PC's default gateway)
                <input
                  className="command"
                  value={wanForm.gateway_host}
                  placeholder="192.168.1.1"
                  onChange={(event) => patchWan("gateway_host", event.target.value)}
                />
              </label>
              <label>
                Gateway SSH user
                <input
                  className="command"
                  value={wanForm.gateway_user}
                  placeholder="root"
                  onChange={(event) => patchWan("gateway_user", event.target.value)}
                />
              </label>
              <label>
                Gateway SSH port
                <input
                  className="command"
                  value={wanForm.gateway_port}
                  inputMode="numeric"
                  onChange={(event) => patchWan("gateway_port", event.target.value)}
                />
              </label>
              <label>
                Gateway identity file (optional if you set the router password)
                <input
                  className="command"
                  value={wanForm.gateway_identity_file}
                  placeholder="C:\\Users\\you\\.ssh\\router_ed25519"
                  onChange={(event) => patchWan("gateway_identity_file", event.target.value)}
                />
              </label>
            </>
          )}
          {(wanForm.wan_method === "auto" || wanForm.wan_method === "upnp" || wanForm.wan_method === "gateway_ssh") && (
            <label>
              Public hostname the phone should dial
              <input
                className="command"
                value={wanForm.wan_public_host}
                placeholder="home.example.com"
                onChange={(event) => patchWan("wan_public_host", event.target.value)}
              />
            </label>
          )}
          {(wanForm.wan_method === "auto" || wanForm.wan_method === "ssh_reverse") && (
            <>
              <label>
                Reverse-tunnel SSH host
                <input
                  className="command"
                  value={wanForm.ssh_host}
                  placeholder="vpn.example.com"
                  onChange={(event) => patchWan("ssh_host", event.target.value)}
                />
              </label>
              <label>
                Reverse-tunnel SSH user
                <input
                  className="command"
                  value={wanForm.ssh_user}
                  onChange={(event) => patchWan("ssh_user", event.target.value)}
                />
              </label>
              <label>
                Reverse-tunnel SSH port
                <input
                  className="command"
                  value={wanForm.ssh_port}
                  inputMode="numeric"
                  onChange={(event) => patchWan("ssh_port", event.target.value)}
                />
              </label>
              <label>
                Reverse-tunnel identity file
                <input
                  className="command"
                  value={wanForm.ssh_identity_file}
                  placeholder="C:\\Users\\you\\.ssh\\id_ed25519"
                  onChange={(event) => patchWan("ssh_identity_file", event.target.value)}
                />
              </label>
            </>
          )}
        </div>
      )}
      <div className="row" style={{ gap: 10, marginTop: 12 }}>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run(() => prepareConnection(true, remote))}
        >
          Prepare connection
        </button>
        {connection?.state === "ready" && (
          <button
            className="btn secondary"
            disabled={busy}
            onClick={() => run(() => prepareConnection(false, false))}
          >
            Stop mobile access
          </button>
        )}
      </div>
      {connection && (
        <div role="status" style={{ marginTop: 12 }}>
          <strong>{connection.state}</strong> · {connection.activity}
          {wanPath && <p>{wanPath}</p>}
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
              onClick={() => run(() => prepareConnection(true, remote))}
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
