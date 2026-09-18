import { useEffect, useRef, useState } from "react"
import {
  cleanReinstallDurableLogPath,
  cleanReinstallUnavailableMessage,
  formatCleanReinstallLogPaths,
  getCleanReinstallOwnedRoots,
  getCleanReinstallStatus,
  isCleanReinstallConfirmTokenExpired,
  isCleanReinstallSuccess,
  startCleanReinstall,
  type CleanReinstallLogPaths,
  type CleanReinstallOwnedRootEntry,
  type CleanReinstallPreview,
} from "../api"

const POLL_MS = 2000

type Phase = "idle" | "step1" | "step2" | "running" | "succeeded" | "failed"

function DurableLogCallout({ logPaths }: { logPaths: CleanReinstallLogPaths | null | undefined }) {
  const durable = cleanReinstallDurableLogPath(logPaths)
  if (!durable) return null
  return (
    <p className="lede" style={{ margin: "10px 0 0" }}>
      Check the durable log on this PC: <code>{durable}</code>
    </p>
  )
}

function LogPathsBlock({ logPaths, title }: { logPaths: CleanReinstallLogPaths | null | undefined; title?: string }) {
  if (!logPaths) return null
  const lines = formatCleanReinstallLogPaths(logPaths)
  if (!lines.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      {title ? <strong>{title}</strong> : null}
      <ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>
        {lines.map((line) => (
          <li key={line.label}>
            <span>{line.label}: </span>
            <code>{line.path}</code>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function CleanInstallReinstallCard() {
  const [phase, setPhase] = useState<Phase>("idle")
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<CleanReinstallPreview | null>(null)
  const [acknowledged, setAcknowledged] = useState<Record<string, boolean>>({})
  const [error, setError] = useState("")
  const [statusMessage, setStatusMessage] = useState("")
  const [logPaths, setLogPaths] = useState<CleanReinstallLogPaths | null>(null)
  const [logTail, setLogTail] = useState<string[]>([])
  const pollRef = useRef(0)

  const entries: CleanReinstallOwnedRootEntry[] = preview?.owned_root_entries ?? []
  const allAcknowledged =
    entries.length > 0 && entries.every((entry) => acknowledged[entry.path] === true)

  function resetFlow() {
    setPhase("idle")
    setPreview(null)
    setAcknowledged({})
    setError("")
    setStatusMessage("")
    setLogPaths(null)
    setLogTail([])
  }

  async function loadPreview() {
    setBusy(true)
    setError("")
    setStatusMessage("")
    try {
      const data = await getCleanReinstallOwnedRoots()
      setPreview(data)
      setLogPaths(data.log_paths)
      const nextAck: Record<string, boolean> = {}
      for (const entry of data.owned_root_entries) {
        nextAck[entry.path] = false
      }
      setAcknowledged(nextAck)
      if (!data.action_available) {
        setPhase("failed")
        setError(
          `${cleanReinstallUnavailableMessage(data)} `
            + (data.preserved_note ? `${data.preserved_note} ` : "")
            + "You can still use JarvisSetup.exe Clean from the Windows installer.",
        )
        return
      }
      setPhase("step1")
    } catch (err) {
      setPhase("failed")
      setError(err instanceof Error ? err.message : "Could not load the owned-folder list.")
    } finally {
      setBusy(false)
    }
  }

  async function onFinalConfirm() {
    if (!preview || !allAcknowledged) return
    if (isCleanReinstallConfirmTokenExpired(preview)) {
      setPhase("failed")
      setError("The confirmation expired. Start over to load a fresh folder list and token.")
      return
    }
    setBusy(true)
    setError("")
    setStatusMessage("")
    const paths = entries.map((e) => e.path)
    const result = await startCleanReinstall({
      confirm_token: preview.confirm_token,
      acknowledged_roots: paths,
      final_confirm: true,
      setup_exe: null,
    })
    setBusy(false)

    if (result.kind === "aborted") {
      setLogPaths(result.data.log_paths)
      setPhase("failed")
      setError(result.data.reason || "Clean reinstall was aborted before it started.")
      return
    }
    if (result.kind === "error") {
      setPhase("failed")
      setError(result.message)
      return
    }

    setLogPaths(result.data.log_paths)
    setPhase("running")
    setStatusMessage(
      result.data.message
        || "Clean reinstall helper started. Jarvis may stop immediately while files are removed and Setup runs again.",
    )
  }

  useEffect(() => {
    if (phase !== "running") return

    let cancelled = false

    const poll = async () => {
      try {
        const status = await getCleanReinstallStatus()
        if (cancelled) return
        setLogPaths(status.log_paths)
        if (status.log_tail?.length) setLogTail(status.log_tail)

        if (status.status === "running" || status.status === "idle" || status.status === "unknown") {
          pollRef.current = window.setTimeout(() => {
            void poll()
          }, POLL_MS)
          return
        }

        if (isCleanReinstallSuccess(status)) {
          setPhase("succeeded")
          setStatusMessage(
            "Clean reinstall finished successfully. Setup should be running or complete — follow the installer if a window opened.",
          )
          return
        }

        setPhase("failed")
        const reason = status.exit_reason || status.status
        setError(`Clean reinstall did not complete successfully (${reason}). See the log files below.`)
      } catch (err) {
        if (cancelled) return
        setPhase("failed")
        setError(
          (err instanceof Error ? err.message : "Lost connection while checking status.")
            + " The helper may still be running. Check the durable log on this PC before trying again.",
        )
      }
    }

    void poll()

    return () => {
      cancelled = true
      window.clearTimeout(pollRef.current)
    }
  }, [phase])

  const tokenExpiry =
    preview?.confirm_token_expires_at
      ? new Date(preview.confirm_token_expires_at * 1000).toLocaleString()
      : null

  return (
    <div className="card grid settings-pane-card auth-card">
      <h2>Clean Install / Reinstall</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Permanently removes Jarvis application files, models, chats, logs, and other <strong>Jarvis-owned</strong> data
        on this PC, then runs Setup again. Your Documents, Desktop, and folders you added under Allowed directories are
        not part of this list.
      </p>
      {preview?.preserved_note && (
        <p className="lede" style={{ margin: "0 0 12px" }}>
          {preview.preserved_note}
          {preview.license_issuer_preserved ? (
            <>
              {" "}
              (<code>{preview.license_issuer_preserved}</code>)
            </>
          ) : null}
        </p>
      )}

      {phase === "succeeded" && (
        <div style={{ marginBottom: 12, borderLeft: "4px solid var(--ok)", padding: "10px 14px" }}>
          {statusMessage}
          <LogPathsBlock logPaths={logPaths} title="Logs" />
        </div>
      )}

      {error && (
        <div className="card" style={{ marginBottom: 12, padding: "10px 14px" }}>
          {error}
          <DurableLogCallout logPaths={logPaths} />
          <LogPathsBlock logPaths={logPaths} title="Logs" />
          {logTail.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary>Recent log lines</summary>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, marginTop: 8 }}>{logTail.join("\n")}</pre>
            </details>
          )}
        </div>
      )}

      {phase === "running" && !error && (
        <div style={{ marginBottom: 12, borderLeft: "4px solid var(--gold)", padding: "10px 14px" }}>
          <p style={{ margin: 0 }}>{statusMessage || "Clean reinstall is in progress…"}</p>
          <p className="lede" style={{ margin: "8px 0 0" }}>
            Do not close this window until the process finishes or fails. Jarvis may restart or disappear while the
            helper runs.
          </p>
          <LogPathsBlock logPaths={logPaths} title="Logs" />
          {logTail.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary>Recent log lines</summary>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, marginTop: 8 }}>{logTail.join("\n")}</pre>
            </details>
          )}
        </div>
      )}

      {phase === "step1" && preview && (
        <div style={{ marginBottom: 12 }}>
          <p className="lede" style={{ margin: "0 0 12px" }}>
            Step 1 of 2 — confirm every folder Jarvis will delete. This matches the list recorded for this install.
            {tokenExpiry ? ` Confirmation expires ${tokenExpiry}.` : ""}
          </p>
          <ul className="grid" style={{ gap: 10, listStyle: "none", padding: 0, margin: 0 }}>
            {entries.map((entry) => (
              <li key={entry.id} className="card" style={{ padding: "10px 14px" }}>
                <label className="row" style={{ alignItems: "flex-start", gap: 10 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(acknowledged[entry.path])}
                    onChange={(e) =>
                      setAcknowledged((prev) => ({ ...prev, [entry.path]: e.target.checked }))
                    }
                  />
                  <span>
                    <strong>{entry.label}</strong>
                    <br />
                    <code>{entry.path}</code>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="row" style={{ marginTop: 14 }}>
            <button
              className="btn"
              type="button"
              disabled={
                busy
                || !allAcknowledged
                || (preview ? isCleanReinstallConfirmTokenExpired(preview) : false)
              }
              onClick={() => setPhase("step2")}
            >
              Continue to final confirmation
            </button>
            <button className="btn secondary" type="button" disabled={busy} onClick={resetFlow}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === "step2" && preview && (
        <div style={{ marginBottom: 12 }}>
          {isCleanReinstallConfirmTokenExpired(preview) && (
            <p className="lede" style={{ margin: "0 0 12px", color: "var(--bad)" }}>
              Confirmation expired. Go back and cancel, then start over to fetch a new token.
            </p>
          )}
          <p className="lede" style={{ margin: "0 0 12px" }}>
            Step 2 of 2 — <strong>This cannot be undone.</strong> Jarvis will force-stop, delete only the folders you
            acknowledged, and launch Setup for a clean install. Default is to cancel.
          </p>
          <ul style={{ margin: "0 0 12px", paddingLeft: 20 }}>
            {entries.map((entry) => (
              <li key={entry.id}>
                <code>{entry.path}</code>
              </li>
            ))}
          </ul>
          <div className="row">
            <button className="btn secondary" type="button" disabled={busy} onClick={() => setPhase("step1")}>
              Back
            </button>
            <button className="btn secondary" type="button" disabled={busy} onClick={resetFlow}>
              No, cancel
            </button>
            <button
              className="btn danger"
              type="button"
              disabled={busy || isCleanReinstallConfirmTokenExpired(preview)}
              onClick={() => void onFinalConfirm()}
            >
              Yes, clean install — cannot be undone
            </button>
          </div>
        </div>
      )}

      {(phase === "idle" || phase === "failed" || phase === "succeeded") && (
        <div className="row">
          {phase === "idle" && (
            <button className="btn danger" type="button" disabled={busy} onClick={() => void loadPreview()}>
              Clean Install / Reinstall
            </button>
          )}
          {(phase === "failed" || phase === "succeeded") && (
            <button className="btn secondary" type="button" disabled={busy} onClick={resetFlow}>
              {phase === "succeeded" ? "Done" : "Start over"}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
