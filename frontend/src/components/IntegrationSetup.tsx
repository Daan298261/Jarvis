import { useEffect, useState, type FormEvent } from "react"
import { QRCodeSVG } from "qrcode.react"
import {
  cancelWhatsAppPairing,
  configureGmail,
  getIntegrationStatus,
  getWhatsAppPairing,
  startWhatsAppPairing,
  type EmailIntegrationStatus,
  type WhatsAppIntegrationStatus,
} from "../api"

const EMPTY_EMAIL: EmailIntegrationStatus = { configured: false, email: "", full_name: "" }
const EMPTY_WHATSAPP: WhatsAppIntegrationStatus = {
  state: "idle",
  qr: "",
  error: "",
  paired: false,
}

function StatusPill({ state, label }: { state: "idle" | "working" | "ready" | "failed"; label: string }) {
  return <span className={`integration-status ${state}`}>{label}</span>
}

export function IntegrationSetup() {
  const [emailStatus, setEmailStatus] = useState(EMPTY_EMAIL)
  const [whatsapp, setWhatsApp] = useState(EMPTY_WHATSAPP)
  const [accountName, setAccountName] = useState("personal")
  const [email, setEmail] = useState("")
  const [fullName, setFullName] = useState("")
  const [appPassword, setAppPassword] = useState("")
  const [emailBusy, setEmailBusy] = useState(false)
  const [emailError, setEmailError] = useState("")
  const [whatsappBusy, setWhatsAppBusy] = useState(false)

  useEffect(() => {
    getIntegrationStatus()
      .then((status) => {
        setEmailStatus(status.email)
        setWhatsApp(status.whatsapp)
        if (status.email.email) setEmail(status.email.email)
        if (status.email.full_name) setFullName(status.email.full_name)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!(["starting", "pairing"] as string[]).includes(whatsapp.state)) return
    const timer = window.setInterval(() => {
      getWhatsAppPairing()
        .then((result) => setWhatsApp(result.whatsapp))
        .catch(() => undefined)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [whatsapp.state])

  async function submitGmail(event: FormEvent) {
    event.preventDefault()
    setEmailBusy(true)
    setEmailError("")
    try {
      const result = await configureGmail({
        account_name: accountName,
        email,
        full_name: fullName,
        app_password: appPassword,
      })
      setEmailStatus(result.email)
      setAppPassword("")
    } catch (error) {
      setEmailError(String(error))
    } finally {
      setEmailBusy(false)
    }
  }

  async function pairWhatsApp() {
    setWhatsAppBusy(true)
    try {
      const result = await startWhatsAppPairing()
      setWhatsApp(result.whatsapp)
    } catch (error) {
      setWhatsApp({ ...EMPTY_WHATSAPP, state: "failed", error: String(error) })
    } finally {
      setWhatsAppBusy(false)
    }
  }

  async function cancelPairing() {
    setWhatsAppBusy(true)
    try {
      const result = await cancelWhatsAppPairing()
      setWhatsApp(result.whatsapp)
    } finally {
      setWhatsAppBusy(false)
    }
  }

  const whatsAppWorking = whatsapp.state === "starting" || whatsapp.state === "pairing"

  return (
    <div className="integration-grid">
      <article className="card integration-card">
        <div className="integration-card-head">
          <div className="integration-provider-icon gmail" aria-hidden="true">M</div>
          <div>
            <h3>Gmail</h3>
            <p>Let Jarvis read and send mail from your account.</p>
          </div>
          {emailStatus.configured ? (
            <StatusPill state="ready" label="Connected" />
          ) : emailBusy ? (
            <StatusPill state="working" label="Checking…" />
          ) : (
            <StatusPill state="idle" label="Not connected" />
          )}
        </div>

        {emailStatus.configured && (
          <div className="integration-success">
            <strong>{emailStatus.email}</strong>
            <span>Gmail sign-in tested and saved on this PC.</span>
          </div>
        )}

        <form className="integration-form" onSubmit={submitGmail}>
          <label>
            Your name
            <input value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" placeholder="Daan van Essen" required />
          </label>
          <label>
            Gmail address
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" placeholder="you@gmail.com" required />
          </label>
          <label>
            Google app password
            <input value={appPassword} onChange={(event) => setAppPassword(event.target.value)} type="password" autoComplete="new-password" placeholder="16-character app password" required />
          </label>
          <label className="integration-account-name">
            Connection name
            <input value={accountName} onChange={(event) => setAccountName(event.target.value)} placeholder="personal" required />
          </label>
          <p className="integration-help">
            Use a Google app password, not your normal password. <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">Create one at Google</a>.
          </p>
          {emailError && <p className="integration-error">{emailError}</p>}
          <button className="btn" type="submit" disabled={emailBusy}>
            {emailBusy ? "Testing Gmail…" : emailStatus.configured ? "Reconnect Gmail" : "Connect Gmail"}
          </button>
        </form>
      </article>

      <article className="card integration-card">
        <div className="integration-card-head">
          <div className="integration-provider-icon whatsapp" aria-hidden="true">W</div>
          <div>
            <h3>WhatsApp</h3>
            <p>Pair this PC by scanning one QR code.</p>
          </div>
          {whatsapp.state === "connected" || whatsapp.paired ? (
            <StatusPill state="ready" label="Connected" />
          ) : whatsapp.state === "failed" ? (
            <StatusPill state="failed" label="Needs attention" />
          ) : whatsAppWorking ? (
            <StatusPill state="working" label={whatsapp.state === "pairing" ? "Scan now" : "Starting…"} />
          ) : (
            <StatusPill state="idle" label="Not connected" />
          )}
        </div>

        {whatsapp.state === "connected" || whatsapp.paired ? (
          <div className="integration-success">
            <strong>WhatsApp is paired</strong>
            <span>Jarvis can use the saved connection on this PC.</span>
          </div>
        ) : whatsapp.qr ? (
          <div className="whatsapp-pairing">
            <div className="whatsapp-qr">
              <QRCodeSVG value={whatsapp.qr} size={232} level="M" marginSize={2} />
            </div>
            <ol>
              <li>Open WhatsApp on your phone.</li>
              <li>Go to <strong>Settings → Linked devices</strong>.</li>
              <li>Tap <strong>Link a device</strong> and scan this code.</li>
            </ol>
          </div>
        ) : (
          <div className="integration-empty">
            <strong>No terminal needed</strong>
            <p>Jarvis opens a secure local pairing session and shows the QR code here.</p>
          </div>
        )}

        {whatsapp.error && <p className="integration-error">{whatsapp.error}</p>}
        <div className="row integration-actions">
          {!whatsAppWorking && whatsapp.state !== "connected" && !whatsapp.paired && (
            <button className="btn" type="button" disabled={whatsappBusy} onClick={pairWhatsApp}>
              {whatsapp.state === "failed" ? "Try again" : "Pair WhatsApp"}
            </button>
          )}
          {whatsAppWorking && (
            <button className="btn secondary" type="button" disabled={whatsappBusy} onClick={cancelPairing}>
              Cancel pairing
            </button>
          )}
        </div>
      </article>
    </div>
  )
}
