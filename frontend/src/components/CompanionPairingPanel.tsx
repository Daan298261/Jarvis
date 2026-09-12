import { useCallback, useEffect, useState } from "react"
import { QRCodeSVG } from "qrcode.react"
import {
  api,
  createCompanionPairingCode,
  fetchCompanionOnboarding,
  getActiveCompanionPairingCode,
  regenerateCompanionPairingCode,
  type CompanionOnboardingOffer,
  type CompanionOnboardingSnapshot,
  type CompanionPairingCode,
} from "../api"
import { speakChatReply } from "../tts/chatTtsPlayer"
import { useSpeakChatReplies } from "../tts/chatTtsSettings"

type CompanionDevice = { id: string; name: string; status: string; fingerprint: string }

function formatDigits(code: string): string {
  const digits = code.replace(/\D/g, "").slice(0, 6)
  return digits.padStart(6, "0")
}

function remainingSeconds(pairing: CompanionPairingCode): number {
  if (pairing.expires_at) {
    const expiresMs =
      typeof pairing.expires_at === "number" ? pairing.expires_at * 1000 : Date.parse(String(pairing.expires_at))
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

function qrPayload(pairing: CompanionPairingCode): string | null {
  if (pairing.qr?.endpoint && pairing.qr.server_pin && pairing.qr.code) {
    return JSON.stringify(pairing.qr)
  }
  if (pairing.endpoint && pairing.server_pin && pairing.code) {
    return JSON.stringify({
      endpoint: pairing.endpoint,
      server_pin: pairing.server_pin,
      code: formatDigits(pairing.code),
    })
  }
  return null
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
  const [onboarding, setOnboarding] = useState<CompanionOnboardingSnapshot | null>(null)
  const [spokenOfferId, setSpokenOfferId] = useState<string | null>(null)
  const [speakChatReplies] = useSpeakChatReplies()

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

  const ensureCode = useCallback(
    async (createIfMissing: boolean) => {
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
    },
    [applyResult],
  )

  useEffect(() => {
    ensureCode(true).catch(() => setState({ mode: "waiting_api" }))
  }, [ensureCode]) // Generate once when this owner-only screen opens; plaintext is never stored server-side.

  useEffect(() => {
    fetchCompanionOnboarding()
      .then(setOnboarding)
      .catch(() => setOnboarding(null))
  }, [])

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

  async function speakOffer(offer: CompanionOnboardingOffer) {
    setSpokenOfferId(offer.id)
    setMsg(offer.spoken_prompt)
    const shouldSpeak = speakChatReplies || onboarding?.speak_chat_replies === true
    if (shouldSpeak) {
      await speakChatReply(offer.spoken_prompt)
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

  const readyPairing = state.mode === "ready" ? state.pairing : null
  const qrValue = readyPairing ? qrPayload(readyPairing) : null

  return (
    <div className={compact ? "companion-pairing companion-pairing--compact" : "companion-pairing"}>
      {!compact && onboarding && onboarding.offers.length > 0 && (
        <div className="companion-pairing-offers" aria-label="Companion onboarding choices">
          <p className="companion-pairing-offers-lede">What would you like to do?</p>
          <div className="row companion-pairing-offer-actions">
            {onboarding.offers.map((offer) => (
              <button
                key={offer.id}
                className={`btn ${spokenOfferId === offer.id ? "" : "secondary"}`}
                type="button"
                disabled={busy}
                onClick={() => void speakOffer(offer)}
              >
                {offer.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="companion-pairing-code" aria-live="polite">
        {displayCode.split("").map((digit, index) => (
          <span key={index} className="companion-pairing-digit">
            {digit}
          </span>
        ))}
      </div>

      {!compact && state.mode === "ready" && (
        <div className="companion-pairing-qr-block">
          {qrValue ? (
            <>
              <div className="companion-pairing-qr" aria-label="Companion pairing QR code">
                <QRCodeSVG value={qrValue} size={232} level="M" marginSize={2} />
              </div>
              <p className="companion-pairing-hint">
                Scan with the Jarvis companion app, or type the 6-digit code. Same session as the digits above.
              </p>
            </>
          ) : (
            <p className="companion-pairing-hint">
              QR appears after Prepare connection is ready (HTTPS endpoint + server pin). The 6-digit code still works.
            </p>
          )}
        </div>
      )}

      <div className="companion-pairing-meta">
        <span className="companion-pairing-ttl">{countdown}</span>
        {state.mode === "waiting_api" && (
          <span className="companion-pairing-hint">Pairing service unavailable.</span>
        )}
        {state.mode === "error" && <span className="companion-pairing-hint">{state.message}</span>}
      </div>

      {msg && <p className="companion-pairing-msg">{msg}</p>}

      <div className="row companion-pairing-actions">
        <button className="btn" type="button" disabled={busy} onClick={() => void regenerate()}>
          Regenerate code
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={busy || displayCode === "------"}
          onClick={() => void copyCode()}
        >
          Copy
        </button>
        {state.mode === "waiting_api" && (
          <button className="btn secondary" type="button" disabled={busy} onClick={() => void ensureCode(true)}>
            Try create
          </button>
        )}
      </div>

      {!compact && (
        <>
          <ol className="companion-pairing-steps">
            <li>Open the Jarvis companion app on your phone.</li>
            <li>Scan the QR code or enter this 6-digit code.</li>
            <li>Compare and approve the fingerprint below.</li>
          </ol>
          {devices
            .filter((device) => device.status === "pending")
            .map((device) => (
              <div key={device.id} className="card" style={{ marginTop: 12 }}>
                <strong>{device.name} · awaiting approval</strong>
                <p style={{ overflowWrap: "anywhere", fontFamily: "monospace" }}>
                  {device.fingerprint.match(/.{1,8}/g)?.join(" ")}
                </p>
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true)
                    setMsg("")
                    try {
                      await api(`/api/mobile/manage/devices/${device.id}/confirm`, {
                        method: "POST",
                        body: JSON.stringify({ fingerprint: device.fingerprint }),
                      })
                      setMsg(`${device.name} approved. Return to the phone and connect.`)
                      await refreshDevices()
                    } catch (error) {
                      setMsg(error instanceof Error ? error.message : String(error))
                    } finally {
                      setBusy(false)
                    }
                  }}
                >
                  Fingerprint matches — approve phone
                </button>
              </div>
            ))}
          {devices.some((device) => device.status === "active") && (
            <p className="companion-pairing-msg">
              Paired:{" "}
              {devices
                .filter((device) => device.status === "active")
                .map((device) => device.name)
                .join(", ")}
            </p>
          )}
        </>
      )}
    </div>
  )
}
