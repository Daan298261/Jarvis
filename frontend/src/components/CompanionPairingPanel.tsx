import { useCallback, useEffect, useState } from "react"
import {
  createCompanionPairingCode,
  getActiveCompanionPairingCode,
  regenerateCompanionPairingCode,
  type CompanionPairingCode,
} from "../api"

function formatDigits(code: string): string {
  const digits = code.replace(/\D/g, "").slice(0, 6)
  return digits.padStart(6, "0")
}

function remainingSeconds(pairing: CompanionPairingCode): number {
  if (pairing.expires_at) {
    const expiresMs = Date.parse(pairing.expires_at)
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

  const refresh = useCallback(async () => {
    const result = await getActiveCompanionPairingCode()
    applyResult(result)
    return result
  }, [applyResult])

  useEffect(() => {
    refresh().catch(() => setState({ mode: "waiting_api" }))
  }, [refresh])

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

  async function ensureCode(createIfMissing: boolean) {
    setBusy(true)
    setMsg("")
    try {
      let result = await getActiveCompanionPairingCode()
      if (!result.available && result.reason === "not_found" && createIfMissing) {
        result = await createCompanionPairingCode()
      }
      applyResult(result)
      if (!result.available && result.reason === "not_found") {
        setMsg("Pairing API is not available yet. Enter this screen again after the backend lands.")
      }
    } finally {
      setBusy(false)
    }
  }

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
        setMsg("Pairing API is not available yet — waiting for backend (D1).")
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
          <span className="companion-pairing-hint">Backend pairing endpoints not deployed yet.</span>
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
        <ol className="companion-pairing-steps">
          <li>Open the Jarvis companion app on your phone.</li>
          <li>Enter this 6-digit code when prompted.</li>
          <li>Confirm the device fingerprint on this PC if asked.</li>
        </ol>
      )}
    </div>
  )
}
