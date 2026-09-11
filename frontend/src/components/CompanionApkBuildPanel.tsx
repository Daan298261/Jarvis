import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  companionApkDownloadName,
  companionBuildPhase,
  downloadCompanionApkBlob,
  fetchCompanionBuild,
  getIntegrationStatus,
  sendCompanionApkEmail,
  sendCompanionApkWhatsApp,
  type CompanionBuildJob,
  type IntegrationStatus,
} from "../api"

const PHASE_LABEL: Record<ReturnType<typeof companionBuildPhase>, string> = {
  queued: "Queued",
  building: "Building",
  ready: "Ready",
  failed: "Failed",
}

function BuildStatusPill({ build }: { build: CompanionBuildJob }) {
  const phase = companionBuildPhase(build.state)
  const state =
    phase === "ready" ? "ready" : phase === "failed" || build.stale ? "failed" : phase === "building" ? "working" : "idle"
  const label = build.stale && phase === "building" ? "Stale — interrupted" : PHASE_LABEL[phase]
  return <span className={`integration-status ${state}`}>{label}</span>
}

type Props = {
  build: CompanionBuildJob
  onBuildChange: (build: CompanionBuildJob) => void
  onRetry: () => void
  busy: boolean
  onError: (message: string) => void
  onClearError: () => void
}

export function CompanionApkBuildPanel({ build, onBuildChange, onRetry, busy, onError, onClearError }: Props) {
  const [integrations, setIntegrations] = useState<IntegrationStatus | null>(null)
  const [sendBusy, setSendBusy] = useState<"" | "email" | "whatsapp">("")
  const [sendError, setSendError] = useState("")
  const [sendNote, setSendNote] = useState("")

  const phase = companionBuildPhase(build.state)
  const buildInProgress = phase === "queued" || phase === "building"

  useEffect(() => {
    if (phase !== "ready") return
    getIntegrationStatus()
      .then(setIntegrations)
      .catch(() => setIntegrations(null))
  }, [phase, build.id])

  useEffect(() => {
    if (!buildInProgress) return
    const interval = window.setInterval(() => {
      fetchCompanionBuild(build.id)
        .then(onBuildChange)
        .catch((err) => onError(err instanceof Error ? err.message : String(err)))
    }, 2000)
    return () => window.clearInterval(interval)
  }, [build.id, buildInProgress, onBuildChange, onError])

  async function downloadToDesktop() {
    onClearError()
    setSendError("")
    try {
      const blob = await downloadCompanionApkBlob(build.id)
      const filename = companionApkDownloadName(build)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = filename
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
    }
  }

  async function send(channel: "email" | "whatsapp") {
    onClearError()
    setSendError("")
    setSendNote("")
    setSendBusy(channel)
    try {
      const result = channel === "email" ? await sendCompanionApkEmail(build.id) : await sendCompanionApkWhatsApp(build.id)
      if (!result.ok) {
        setSendError(result.message)
        return
      }
      setSendNote(result.detail || (channel === "email" ? "APK sent by email." : "APK sent on WhatsApp."))
    } finally {
      setSendBusy("")
    }
  }

  const emailReady = integrations?.email.configured === true
  const whatsAppReady =
    integrations?.whatsapp.paired === true || integrations?.whatsapp.state === "connected"
  const integrationsLoaded = integrations !== null

  return (
    <div className="companion-apk-build" role="status" aria-live="polite">
      <div className="companion-apk-build-head">
        <div>
          <strong className="companion-apk-build-title">Companion APK build</strong>
          <p className="companion-apk-build-activity">{build.activity}</p>
        </div>
        <BuildStatusPill build={build} />
      </div>

      <p className="companion-apk-build-meta">
        {build.worker || "Android builder"} · Started {new Date(build.started_at * 1000).toLocaleTimeString()} · Last
        progress {new Date((build.heartbeat_at || build.updated_at) * 1000).toLocaleTimeString()}
      </p>

      {build.stale && buildInProgress && (
        <p className="companion-apk-build-warn">
          No recent build heartbeat. Jarvis will mark an interrupted build failed after restart.
        </p>
      )}

      {phase === "failed" && (
        <div className="companion-apk-build-failed">
          <p className="companion-apk-build-error">{build.activity || "Build failed."}</p>
          <button className="btn secondary" type="button" disabled={busy} onClick={onRetry}>
            Retry build
          </button>
        </div>
      )}

      {buildInProgress && (
        <p className="companion-apk-build-hint">
          {phase === "queued"
            ? "Waiting for the Android builder to start…"
            : "Building your personalized companion APK — this can take several minutes."}
        </p>
      )}

      {phase === "ready" && (
        <div className="companion-apk-build-ready">
          <button className="btn" type="button" disabled={busy || sendBusy !== ""} onClick={downloadToDesktop}>
            Download to Desktop
          </button>
          <p className="companion-apk-build-hint">
            Saves as <code>{companionApkDownloadName(build)}</code> (use your browser save dialog; pick Desktop on
            Windows).
          </p>

          <div className="companion-apk-send">
            <p className="companion-apk-send-lede">Optional — send the APK to your phone</p>
            <div className="row companion-apk-send-actions">
              <button
                className="btn secondary"
                type="button"
                disabled={!whatsAppReady || sendBusy !== "" || busy}
                title={
                  whatsAppReady
                    ? "Send APK via WhatsApp"
                    : "Connect WhatsApp in Setup to enable sending"
                }
                onClick={() => send("whatsapp")}
              >
                {sendBusy === "whatsapp" ? "Sending…" : "Send APK via WhatsApp"}
              </button>
              <button
                className="btn secondary"
                type="button"
                disabled={!emailReady || sendBusy !== "" || busy}
                title={emailReady ? "Email APK" : "Connect Gmail in Setup to enable sending"}
                onClick={() => send("email")}
              >
                {sendBusy === "email" ? "Sending…" : "Email APK"}
              </button>
            </div>
            {integrationsLoaded && (!whatsAppReady || !emailReady) && (
              <p className="companion-apk-send-setup">
                {!whatsAppReady && !emailReady ? "WhatsApp and Gmail are not connected. " : !whatsAppReady ? "WhatsApp is not connected. " : "Gmail is not connected. "}
                <Link to="/setup?step=integrations">Connect Gmail and WhatsApp in Setup</Link>
              </p>
            )}
            {sendError && <p className="companion-apk-build-error">{sendError}</p>}
            {sendNote && !sendError && <p className="companion-apk-build-note">{sendNote}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
