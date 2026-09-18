import { useEffect, useState } from "react"
import {
  bindJevApiKey,
  getJevDecisionStatus,
  notifyJevWhenReady,
  probeJevDecision,
  setJevDecisionTier,
  type DecisionTier,
  type JevDecisionStatus,
} from "../api"

type DecisionTierSettingsProps = {
  save: (patch: Record<string, unknown>) => Promise<void>
  setMsg: (msg: string) => void
}

function availabilityLabel(status: JevDecisionStatus | null): string {
  if (!status) return "Loading…"
  if (status.jev_availability === "connected") return "Connected (real TypeSafe probe)"
  if (status.jev_availability === "waitlisted") return "Waitlisted — not connected"
  if (status.jev_availability === "error") return "Error — using local decisions"
  return "Unavailable — local Ornith / heuristics"
}

export function DecisionTierSettings({ save, setMsg }: DecisionTierSettingsProps) {
  const [status, setStatus] = useState<JevDecisionStatus | null>(null)
  const [keyDraft, setKeyDraft] = useState("")
  const [busy, setBusy] = useState(false)

  async function refresh() {
    const next = await getJevDecisionStatus().catch(() => null)
    if (next) setStatus(next)
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function onTier(tier: DecisionTier) {
    setBusy(true)
    try {
      await save({ decision_tier: tier })
      const next = await setJevDecisionTier(tier)
      setStatus(next)
      if (next.owner_error) setMsg(next.owner_error)
    } finally {
      setBusy(false)
    }
  }

  async function onNotify() {
    setBusy(true)
    try {
      const next = await notifyJevWhenReady()
      setStatus(next)
      setMsg("Recorded. Notify when ready does not mean Jev is connected.")
    } finally {
      setBusy(false)
    }
  }

  async function onProbe() {
    setBusy(true)
    try {
      const next = await probeJevDecision()
      setStatus(next)
      setMsg(next.jev_availability === "connected" ? "TypeSafe probe succeeded." : next.owner_error || next.last_probe_error)
    } finally {
      setBusy(false)
    }
  }

  async function onSaveKey() {
    const secret = keyDraft.trim()
    if (!secret) return
    setBusy(true)
    try {
      const result = await bindJevApiKey(secret)
      setKeyDraft("")
      setStatus(result.status)
      setMsg(
        result.status.jev_availability === "connected"
          ? "TypeSafe key saved and probe succeeded. The key will not be shown again."
          : result.status.owner_error || "Key saved. Probe did not connect.",
      )
    } finally {
      setBusy(false)
    }
  }

  const plusOk = Boolean(status?.plus_entitled)
  const connected = status?.jev_availability === "connected"

  return (
    <div className="card grid settings-pane-card">
      <h2>Decision accelerator (Jev)</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Optional TypeSafe System One cloud decisions for tool pick, speak class, complexity, and
        approval. Local Ornith and heuristics stay the default. Cloud never auto-enables.
      </p>
      <label>
        Decision tier
        <select
          value={status?.decision_tier || "local"}
          disabled={busy}
          onChange={(event) => void onTier(event.target.value as DecisionTier)}
        >
          <option value="local">Local (Ornith + heuristics)</option>
          <option value="jev_optional">Jev (optional cloud, your TypeSafe key)</option>
          <option value="jev_plus">Plus (requires decision.jev_plus entitlement)</option>
        </select>
      </label>
      <p className="lede" style={{ margin: 0 }}>
        Status: <strong>{availabilityLabel(status)}</strong>
        {status?.last_probe_latency_ms != null && connected
          ? ` · last probe ${Math.round(status.last_probe_latency_ms)} ms`
          : ""}
        {status?.last_model && connected ? ` · ${status.last_model}` : ""}
      </p>
      {status?.owner_error ? <p className="lede">{status.owner_error}</p> : null}
      <p className="lede" style={{ margin: 0 }}>
        Plus entitlement:{" "}
        <strong>{plusOk ? "decision.jev_plus present" : "not entitled"}</strong>
        {status?.decision_tier === "jev_plus" && !plusOk
          ? " — attach the feature on the signed lease. This is not a fake checkbox."
          : ""}
      </p>
      <div className="row">
        <a className="btn" href={status?.waitlist_url || "https://typesafe.ai/"} target="_blank" rel="noreferrer">
          TypeSafe waitlist
        </a>
        <button type="button" className="btn" disabled={busy} onClick={() => void onNotify()}>
          Notify when ready
        </button>
        <button type="button" className="btn" disabled={busy || !status?.key_bound} onClick={() => void onProbe()}>
          Retry probe
        </button>
      </div>
      <label>
        TypeSafe API key (write-only)
        <input
          type="password"
          value={keyDraft}
          placeholder={status?.key_bound ? "Key bound. Type to replace. Never shown again." : "Paste a real TypeSafe key"}
          autoComplete="new-password"
          disabled={busy}
          onChange={(event) => setKeyDraft(event.target.value)}
          onBlur={() => void onSaveKey()}
        />
      </label>
    </div>
  )
}
