import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import {
  deleteInferenceCredential,
  getLicenseCluster,
  getLicenseEntitlements,
  getLicenseStatus,
  listInferenceCredentials,
  refreshLicenseLease,
  upsertInferenceCredential,
  validateLicenseOffline,
  type InferenceCredentialPublic,
  type LicenseEntitlements,
  type LicenseStatus,
  type LicenseValidation,
  type SignedLeaseObject,
} from "../api"

const STATUS_COPY: Record<string, string> = {
  unlicensed: "No Jarvis subscription on this PC",
  tamper_detected: "This PC’s clock looks wrong, so the subscription cannot be trusted",
  invalid_signature: "This license file is not genuine",
  cluster_mismatch: "This license belongs to a different installation",
  not_yet_valid: "This license is not active yet",
  expired: "The Jarvis subscription has expired",
  grace: "Subscription expired — still working during the grace period",
  active: "Jarvis subscription is active",
  valid: "Jarvis subscription is active",
}

function statusLabel(status: string | null | undefined): string {
  if (!status) return "Unknown"
  return STATUS_COPY[status] || status.replaceAll("_", " ")
}

function statusBadgeClass(status: string | null | undefined): string {
  const key = (status || "").toLowerCase()
  if (key === "active" || key === "valid") return "ok"
  if (key === "grace" || key === "not_yet_valid") return "waiting"
  if (
    key === "expired" ||
    key === "tamper_detected" ||
    key === "invalid_signature" ||
    key === "cluster_mismatch"
  ) {
    return "failed"
  }
  return "queued"
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatGrace(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "None"
  if (seconds < 60) return `${Math.round(seconds)} seconds after expiry`
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes after expiry`
  if (seconds < 86400) {
    const hours = Math.round(seconds / 3600)
    return `${hours} hour${hours === 1 ? "" : "s"} after expiry`
  }
  const days = Math.round(seconds / 86400)
  return `${days} day${days === 1 ? "" : "s"} after expiry`
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function parseSignedLease(text: string): SignedLeaseObject {
  const trimmed = text.trim()
  if (!trimmed) throw new Error("Paste a signed license file first.")
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error("That does not look like a signed license file. Check for a missing comma or quote.")
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("A signed license file must be a JSON object.")
  }
  const record = parsed as Record<string, unknown>
  if (!record.payload || typeof record.payload !== "object") {
    throw new Error("This file is missing the license details (payload).")
  }
  if (typeof record.signature !== "string" || !record.signature.trim()) {
    throw new Error("This file is missing the signature.")
  }
  return record as SignedLeaseObject
}

type LicenseSettingsProps = {
  showPageChrome?: boolean
}

export function LicenseSettings({ showPageChrome = false }: LicenseSettingsProps) {
  const [status, setStatus] = useState<LicenseStatus | null>(null)
  const [entitlements, setEntitlements] = useState<LicenseEntitlements | null>(null)
  const [credentials, setCredentials] = useState<InferenceCredentialPublic[]>([])
  const [leaseText, setLeaseText] = useState("")
  const [provider, setProvider] = useState("")
  const [label, setLabel] = useState("")
  const [endpoint, setEndpoint] = useState("")
  const [secret, setSecret] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const loadAll = useCallback(async () => {
    const [statusResult, entitlementResult, credentialResult, clusterResult] = await Promise.allSettled([
      getLicenseStatus(),
      getLicenseEntitlements(),
      listInferenceCredentials(),
      getLicenseCluster(),
    ])

    if (statusResult.status === "fulfilled") {
      setStatus(statusResult.value)
    } else if (clusterResult.status === "fulfilled") {
      setStatus({
        cluster_id: clusterResult.value.cluster_id,
        validation: { status: "unlicensed", valid: false, message: "Could not load license status." },
        lease_present: false,
        last_status: null,
        last_message: null,
        last_validated_at: null,
      })
    } else {
      throw statusResult.reason
    }

    if (entitlementResult.status === "fulfilled") {
      setEntitlements(entitlementResult.value.entitlements)
    } else {
      setEntitlements(null)
    }

    if (credentialResult.status === "fulfilled") {
      setCredentials(credentialResult.value.credentials)
    } else {
      setCredentials([])
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    loadAll().catch((err: unknown) => {
      if (!cancelled) setError(errorMessage(err, "Could not load license settings."))
    })
    return () => {
      cancelled = true
    }
  }, [loadAll])

  async function refresh() {
    setError("")
    await loadAll()
  }

  async function onOfflineCheck() {
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const validation = await validateLicenseOffline()
      setStatus((prev) =>
        prev
          ? {
              ...prev,
              validation,
              last_status: validation.status ?? prev.last_status,
              last_message: validation.message ?? prev.last_message,
              last_validated_at: validation.last_validated_at ?? prev.last_validated_at,
            }
          : prev,
      )
      setMsg("Checked this PC’s saved license. Jarvis did not need to reach the vendor for this check.")
      await refresh()
    } catch (err: unknown) {
      setError(errorMessage(err, "Could not check the license on this PC."))
    } finally {
      setBusy(false)
    }
  }

  async function onApplyLease(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const lease = parseSignedLease(leaseText)
      await refreshLicenseLease(lease)
      setLeaseText("")
      setMsg("Signed license applied. Your files and models were not changed.")
      await refresh()
    } catch (err: unknown) {
      setError(errorMessage(err, "Could not apply that license file."))
    } finally {
      setBusy(false)
    }
  }

  async function onSaveCredential(event: FormEvent) {
    event.preventDefault()
    const nextProvider = provider.trim()
    const nextLabel = label.trim()
    const nextSecret = secret
    const nextEndpoint = endpoint.trim()
    if (!nextProvider || !nextLabel || !nextSecret.trim()) {
      setError("Provider, label, and secret are required.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      await upsertInferenceCredential({
        provider: nextProvider,
        label: nextLabel,
        secret: nextSecret,
        endpoint: nextEndpoint || undefined,
      })
      setSecret("")
      setProvider("")
      setLabel("")
      setEndpoint("")
      setMsg("Inference key saved. Jarvis will not show the secret again.")
      await refresh()
    } catch (err: unknown) {
      setSecret("")
      setError(errorMessage(err, "Could not save that inference key."))
    } finally {
      setBusy(false)
    }
  }

  async function onRevokeCredential(credential: InferenceCredentialPublic) {
    const name = credential.label || credential.provider || credential.id
    const ok = window.confirm(`Remove the inference key “${name}”? The secret cannot be recovered.`)
    if (!ok) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      await deleteInferenceCredential(credential.id)
      setMsg("Inference key removed.")
      await refresh()
    } catch (err: unknown) {
      setError(errorMessage(err, "Could not remove that inference key."))
    } finally {
      setBusy(false)
    }
  }

  const validation: LicenseValidation = status?.validation || {}
  const statusKey = validation.status || status?.last_status || "unlicensed"
  const packs = entitlements?.pack_entitlements || validation.pack_entitlements || []
  const features = entitlements?.features || validation.features || []
  const tier = entitlements?.tier || validation.tier || null

  return (
    <div className={showPageChrome ? "license-page" : undefined}>
      {showPageChrome ? (
        <>
          <p className="interview-kicker">
            <Link to="/settings">Settings</Link>
            {" · "}
            License
          </p>
          <h1>License &amp; local models</h1>
          <p className="lede">
            Local models and GPUs are yours — their cost is not a Jarvis bill. The Jarvis subscription
            is only for Jarvis the orchestrator on this PC.
          </p>
        </>
      ) : (
        <>
          <h2>License &amp; local models</h2>
          <p className="lede">
            Local models and GPUs are yours — their cost is not a Jarvis bill. The Jarvis subscription
            is only for Jarvis the orchestrator on this PC.
          </p>
        </>
      )}

      <div className="license-stories">
        <div className="card license-story subscription">
          <p className="license-kicker">Jarvis subscription</p>
          <h2>This PC’s license</h2>
          <p className="lede">
            Pays for Jarvis itself — planning, tools, packs, and the portal. It does not rent you a
            model. A missing or expired license never deletes your files or models.
          </p>
          <div className="kv">
            <b>Status</b>
            <span>
              <span className={`badge ${statusBadgeClass(statusKey)}`}>{statusLabel(statusKey)}</span>
            </span>
            <b>This installation</b>
            <span className="stat">{status?.cluster_id || "—"}</span>
            <b>License on file</b>
            <span>{status?.lease_present ? "Yes" : "No"}</span>
            <b>Expires</b>
            <span>{formatWhen(validation.expires_at)}</span>
            <b>Offline grace</b>
            <span>
              {validation.in_grace ? "In grace now · " : ""}
              {formatGrace(validation.grace_seconds)}
            </span>
            <b>Last check</b>
            <span>{formatWhen(validation.last_validated_at || status?.last_validated_at)}</span>
          </div>
          {validation.message && (
            <p className="ads-hint">{validation.message}</p>
          )}
        </div>

        <div className="card license-story inference">
          <p className="license-kicker">Your compute</p>
          <h2>Local &amp; self-hosted inference</h2>
          <p className="lede">
            Models on this PC, a LAN box, or a key you bring are your electricity and your cloud bill —
            not the Jarvis subscription. Jarvis only stores a label so it can call <em>your</em> endpoint.
          </p>
          <div className="kv">
            <b>Who pays</b>
            <span>You — local GPU, power, or the provider on the key</span>
            <b>Stored keys</b>
            <span>{credentials.length ? `${credentials.length} on this PC` : "None yet"}</span>
            <b>Shown here</b>
            <span>Provider, label, id, and endpoint only</span>
          </div>
          <p className="ads-hint">
            Secrets are typed once, sent to this PC, then cleared. Jarvis will not show them again.
          </p>
        </div>
      </div>

      {msg && (
        <div className="card license-banner ok" role="status">
          {msg}
        </div>
      )}
      {error && (
        <div className="card license-banner bad" role="alert">
          {error}
        </div>
      )}

      <div className="card grid" style={{ marginTop: 16 }}>
        <h2>Apply a signed license</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Paste the signed license you already have. This is not a store checkout — Jarvis only
          accepts a signed lease for this installation. Checking the saved license works offline
          while it is still valid or in grace.
        </p>
        <div className="row" style={{ marginBottom: 12 }}>
          <button className="btn" type="button" disabled={busy} onClick={onOfflineCheck}>
            Check license on this PC
          </button>
        </div>
        <form className="grid" onSubmit={onApplyLease} autoComplete="off">
          <label>
            Signed license file
            <textarea
              className="field"
              rows={8}
              value={leaseText}
              spellCheck={false}
              autoComplete="off"
              aria-label="Signed license JSON"
              placeholder='{"payload": { "cluster_id": "…", "tier": "…", "expires_at": "…" }, "signature": "…"}'
              onChange={(event) => setLeaseText(event.target.value)}
            />
          </label>
          <div className="row">
            <button className="btn" type="submit" disabled={busy}>
              Apply license
            </button>
            <button
              className="btn secondary"
              type="button"
              disabled={busy || !leaseText}
              onClick={() => setLeaseText("")}
            >
              Clear paste
            </button>
          </div>
        </form>
      </div>

      <div className="card grid" style={{ marginTop: 16 }}>
        <h2>Included with this subscription</h2>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          Product and pack features from the Jarvis license — not access to your own models.
          {entitlements?.cluster_wide ? " These apply to the whole installation." : ""}
        </p>
        <div className="kv">
          <b>Plan</b>
          <span>{tier || "None on file"}</span>
        </div>
        <h3 className="env-subhead">Packs</h3>
        {packs.length ? (
          <div className="runtime-tags">
            {packs.map((pack) => (
              <span key={pack}>{pack}</span>
            ))}
          </div>
        ) : (
          <p className="lede" style={{ margin: 0 }}>
            No product packs are unlocked by a Jarvis subscription. Local models still belong to you.
          </p>
        )}
        <h3 className="env-subhead">Features</h3>
        {features.length ? (
          <div className="runtime-tags">
            {features.map((feature) => (
              <span key={feature}>{feature}</span>
            ))}
          </div>
        ) : (
          <p className="lede" style={{ margin: 0 }}>No extra orchestrator features on file.</p>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Inference keys (your cost)</h2>
        <p className="lede">
          Optional keys for local or self-hosted endpoints you already pay for. This is not a Jarvis
          subscription. List shows provider, label, id, and endpoint — never the secret.
        </p>
        {credentials.length === 0 ? (
          <p className="lede">No inference keys stored.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Label</th>
                <th>Id</th>
                <th>Endpoint</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {credentials.map((credential) => (
                <tr key={credential.id}>
                  <td>{credential.provider || "—"}</td>
                  <td>{credential.label || "—"}</td>
                  <td className="stat">{credential.id}</td>
                  <td className="stat">{credential.endpoint || "—"}</td>
                  <td>
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={busy}
                      onClick={() => onRevokeCredential(credential)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form className="grid license-cred-form" autoComplete="off" onSubmit={onSaveCredential}>
          <label>
            Provider
            <input
              type="text"
              value={provider}
              list="license-inference-providers"
              placeholder="ollama, llama.cpp, openai"
              autoComplete="off"
              aria-label="Inference provider"
              onChange={(event) => setProvider(event.target.value)}
            />
          </label>
          <label>
            Label
            <input
              type="text"
              value={label}
              placeholder="Home GPU"
              autoComplete="off"
              aria-label="Inference credential label"
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
          <label className="span-2">
            Endpoint (optional)
            <input
              type="text"
              value={endpoint}
              placeholder="http://127.0.0.1:11434"
              autoComplete="off"
              aria-label="Inference endpoint"
              onChange={(event) => setEndpoint(event.target.value)}
            />
          </label>
          <label className="span-2">
            Secret
            <input
              type="password"
              value={secret}
              autoComplete="new-password"
              aria-label="Inference credential secret"
              onChange={(event) => setSecret(event.target.value)}
            />
          </label>
          <datalist id="license-inference-providers">
            <option value="llama.cpp" />
            <option value="ollama" />
            <option value="lmstudio" />
            <option value="openai-compat" />
            <option value="vllm" />
            <option value="sglang" />
          </datalist>
          <div className="span-2 row">
            <button className="btn" type="submit" disabled={busy}>
              Save inference key
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function LicensePage() {
  return <LicenseSettings showPageChrome />
}
