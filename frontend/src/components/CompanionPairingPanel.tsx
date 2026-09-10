import { useCallback, useEffect, useState } from "react"
import {
  api,
  createCompanionPairingCode,
  getActiveCompanionPairingCode,
  regenerateCompanionPairingCode,
  type CompanionPairingCode,
} from "../api"

type CompanionDevice = { id: string; name: string; status: string; fingerprint: string }

function formatDigits(code: string): string {
  const digits = code.replace(/\D/g, "").slice(0, 6)
  return digits.padStart(6, "0")
}

function remainingSeconds(pairing: CompanionPairingCode): number {
  if (pairing.expires_at) {
    const expiresMs = typeof pairing.expires_at === "number" ? pairing.expires_at * 1000 : Date.parse(pairing.expires_at)
    if (!Number.isNaN(expiresMs)) {
      return Math.max(0, Math.ceil((expiresMs - Date.now()) / 1000))
    }
  }
  if (typeof pairing.ttl_seconds === "number" && pairing.ttl_seconds >= 0) {
    return Math.max(0, Math.floor(pairing.ttl_seconds))
  }
  return 0
}

function formatCountdown(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

type PanelState =
  | { mode: "loading" }
  | { mode: "waiting_api" }
  | { mode: "ready"; pairing: CompanionPairingCode; remaining: number }
  | { mode: "expired"; pairing: CompanionPairingCode | null }
  | { mode: "error"; message: string }

export function CompanionPairingPanel({ compact = false }: { compact?: boolean }) {
  const [state, setState] = useState<PanelState>({ mode: "loading" })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [devices, setDevices] = useState<CompanionDevice[]>([])

  const refreshDevices = useCallback(() => {
    if (compact) return Promise.resolve()
    return api<CompanionDevice[]>("/api/mobile/manage/devices").then(setDevices)
  }, [compact])

  const applyResult = useCallback((result: Awaited<ReturnType<typeof getActiveCompanionPairingCode>>) => {
    if (!result.available) {
      if (result.reason === "not_found") {
        setState({ mode: "waiting_api" })
        return
      }
      setState({ mode: "error", message: result.message || "Could not load pairing code." })
      return
    }
    const remaining = remainingSeconds(result.pairing)
    if (remaining <= 0) {
      setState({ mode: "expired", pairing: result.pairing })
      return
    }
    setState({ mode: "ready", pairing: result.pairing, remaining })
  }, [])

  const ensureCode = useCallback(async (createIfMissing: boolean) => {
    setBusy(true)
    setMsg("")
    try {
      let result = await getActiveCompanionPairingCode()
      if (!result.available && result.reason === "not_found" && createIfMissing) {
        result = await createCompanionPairingCode()
      }
      applyResult(result)
      if (!result.available && result.reason === "not_found") {
        setMsg("Pairing service is unavailable. Check that Jarvis is running and try again.")
      }
    } finally {
      setBusy(false)
    }
  }, [applyResult])

  useEffect(() => {
    ensureCode(true).catch(() => setState({ mode: "waiting_api" }))
  }, [ensureCode]) // Generate once when this owner-only screen opens; plaintext is never stored server-side.

  useEffect(() => {
    if (compact) return
    refreshDevices().catch(() => undefined)
    const timer = window.setInterval(() => refreshDevices().catch(() => undefined), 3000)
    return () => window.clearInterval(timer)
  }, [compact, refreshDevices])

  const readyExpiresAt = state.mode === "ready" ? state.pairing.expires_at : null

  useEffect(() => {
    if (state.mode !== "ready") return
    const timer = window.setInterval(() => {
      setState((current) => {
        if (current.mode !== "ready") return current
        const next = remainingSeconds(current.pairing)
        if (next <= 0) return { mode: "expired", pairing: current.pairing }
        return { ...current, remaining: next }
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [state.mode, readyExpiresAt])

  async function regenerate() {
    setBusy(true)
    setMsg("")
    try {
      let result = await regenerateCompanionPairingCode()
      if (!result.available && result.reason === "not_found") {
        result = await createCompanionPairingCode()
      }
      applyResult(result)
      if (result.available) {
        setMsg("New pairing code generated. Previous unclaimed codes are invalidated.")
      } else if (result.reason === "not_found") {
        setState({ mode: "waiting_api" })
        setMsg("Pairing service is unavailable. Check that Jarvis is running and try again.")
      } else {
        setState({ mode: "error", message: result.message || "Could not regenerate code." })
      }
    } finally {
      setBusy(false)
    }
  }

  async function copyCode() {
    if (state.mode !== "ready" && state.mode !== "expired") return
    const code = state.pairing ? formatDigits(state.pairing.code) : "------"
    if (code === "------") {
      setMsg("No code to copy yet.")
      return
    }
    try {
      await navigator.clipboard.writeText(code)
      setMsg("Code copied.")
    } catch {
      setMsg(code)
    }
  }

  const displayCode =
    state.mode === "ready" || state.mode === "expired"
      ? state.pairing
        ? formatDigits(state.pairing.code)
        : "------"
      : state.mode === "waiting_api"
        ? "------"
        : "······"

  const countdown =
    state.mode === "ready"
      ? formatCountdown(state.remaining)
      : state.mode === "expired"
        ? "Expired"
        : state.mode === "waiting_api"
          ? "Waiting for API"
          : state.mode === "loading"
            ? "Loading…"
            : "—"

  return (
    <div className={compact ? "companion-pairing companion-pairing--compact" : "companion-pairing"}>
      <div className="companion-pairing-code" aria-live="polite">
        {displayCode.split("").map((digit, index) => (
          <span key={index} className="companion-pairing-digit">{digit}</span>
        ))}
      </div>

      <div className="companion-pairing-meta">
        <span className="companion-pairing-ttl">{countdown}</span>
        {state.mode === "waiting_api" && (
          <span className="companion-pairing-hint">Pairing service unavailable.</span>
        )}
        {state.mode === "error" && (
          <span className="companion-pairing-hint">{state.message}</span>
        )}
      </div>

      {msg && <p className="companion-pairing-msg">{msg}</p>}

      <div className="row companion-pairing-actions">
        <button className="btn" type="button" disabled={busy} onClick={regenerate}>
          Regenerate code
        </button>
        <button className="btn secondary" type="button" disabled={busy || displayCode === "------"} onClick={copyCode}>
          Copy
        </button>
        {state.mode === "waiting_api" && (
          <button className="btn secondary" type="button" disabled={busy} onClick={() => ensureCode(true)}>
            Try create
          </button>
        )}
      </div>

      {!compact && (
        <>
          <ol className="companion-pairing-steps">
            <li>Open the Jarvis companion app on your phone.</li>
            <li>Enter this 6-digit code.</li>
            <li>Compare and approve the fingerprint below.</li>
          </ol>
          {devices.filter((device) => device.status === "pending").map((device) => (
            <div key={device.id} className="card" style={{ marginTop: 12 }}>
              <strong>{device.name} · awaiting approval</strong>
              <p style={{ overflowWrap: "anywhere", fontFamily: "monospace" }}>
                {device.fingerprint.match(/.{1,8}/g)?.join(" ")}
              </p>
              <button className="btn" type="button" onClick={async () => {
                setBusy(true); setMsg("")
                try {
                  await api(`/api/mobile/manage/devices/${device.id}/confirm`, {
                    method: "POST", body: JSON.stringify({ fingerprint: device.fingerprint }),
                  })
                  setMsg(`${device.name} approved. Return to the phone and connect.`)
                  await refreshDevices()
                } catch (error) {
                  setMsg(error instanceof Error ? error.message : String(error))
                } finally { setBusy(false) }
              }} disabled={busy}>Fingerprint matches — approve phone</button>
            </div>
          ))}
          {devices.some((device) => device.status === "active") && (
            <p className="companion-pairing-msg">Paired: {devices.filter((device) => device.status === "active").map((device) => device.name).join(", ")}</p>
          )}
        </>
      )}
    </div>
  )
}
