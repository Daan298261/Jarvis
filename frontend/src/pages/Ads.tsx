import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import {
  AMAZON_ADS_WINDOWS,
  AMAZON_ADS_WRITE_AUTHORITY,
  approveAmazonAdsRecommendation,
  executeAmazonAdsRecommendation,
  getAmazonAdsHealth,
  getAmazonAdsMetrics,
  getAmazonAdsPolicy,
  getAmazonAdsWinnersWaste,
  ingestAmazonAds,
  listAmazonAdsConnections,
  listAmazonAdsPendingApprovals,
  listAmazonAdsRecommendations,
  startAmazonAdsOAuth,
  updateAmazonAdsPolicy,
  type AmazonAdsBreakEven,
  type AmazonAdsConnection,
  type AmazonAdsEntityRow,
  type AmazonAdsHealth,
  type AmazonAdsOAuthStart,
  type AmazonAdsPolicy,
  type AmazonAdsRecommendation,
  type AmazonAdsWindowDays,
  type AmazonAdsWindowKey,
  type AmazonAdsWindowMetrics,
} from "../api"

const PROFILE_KEY = "jarvis_ads_profile_id"
const PORTAL_ACTOR = "portal-user"

const ACTION_COPY: Record<string, string> = {
  pause: "Pause this target",
  unpause: "Resume this target",
  decrease_bid: "Lower the bid",
  increase_bid: "Raise the bid",
  decrease_budget: "Lower the daily budget",
  increase_budget: "Raise the daily budget",
  add_negative: "Add as a negative keyword",
}

function todayIso(): string {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, "0")
  const d = String(now.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
}

function addDays(iso: string, delta: number): string {
  const [year, month, day] = iso.split("-").map(Number)
  const date = new Date(year, (month || 1) - 1, day || 1)
  date.setDate(date.getDate() + delta)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, "0")
  const d = String(date.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function formatMoney(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return value.toLocaleString(undefined, { style: "currency", currency: "USD" })
}

function formatRoas(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return `${value.toFixed(2)}x`
}

function formatAcos(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(1)}%`
}

function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function windowKey(days: AmazonAdsWindowDays): AmazonAdsWindowKey {
  return `${days}d`
}

function windowLabel(days: AmazonAdsWindowDays): string {
  return `${days} days`
}

function readStoredProfile(): string {
  try {
    return localStorage.getItem(PROFILE_KEY) || ""
  } catch {
    return ""
  }
}

function storeProfile(id: string): void {
  try {
    if (id) localStorage.setItem(PROFILE_KEY, id)
    else localStorage.removeItem(PROFILE_KEY)
  } catch {
    // ignore
  }
}

function profilesFromConnections(connections: AmazonAdsConnection[]): string[] {
  const ids: string[] = []
  for (const connection of connections) {
    for (const id of connection.profile_ids || []) {
      if (id && !ids.includes(id)) ids.push(id)
    }
  }
  return ids
}

function parseBreakEven(value: unknown): AmazonAdsBreakEven | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  return {
    royalty_rate: asNumber(record.royalty_rate) ?? 0,
    margin_rate: asNumber(record.margin_rate) ?? 0,
    other_costs_pct: asNumber(record.other_costs_pct) ?? 0,
  }
}

function breakEvenTargets(config: AmazonAdsBreakEven | null | undefined): {
  roas: number | null
  acos: number | null
} {
  if (!config) return { roas: null, acos: null }
  const margin = config.margin_rate || 0
  const royalty = config.royalty_rate || 0
  const other = config.other_costs_pct || 0
  const net = (margin > 0 ? margin : royalty) - other
  if (net <= 0) return { roas: null, acos: null }
  return { roas: 1 / net, acos: net }
}

function connectionStatus(connections: AmazonAdsConnection[]): { label: string; tone: string } {
  if (!connections.length) return { label: "Not connected", tone: "off" }
  if (connections.some((row) => (row.status || "").toLowerCase() === "connected")) {
    return { label: "Connected", tone: "on" }
  }
  if (connections.some((row) => (row.status || "").toLowerCase() === "pending")) {
    return { label: "Waiting to finish", tone: "load" }
  }
  return { label: connections[0]?.status || "Unknown", tone: "load" }
}

function healthLabel(health: AmazonAdsHealth | null, connected: boolean): { title: string; detail: string } {
  if (!connected) {
    return { title: "No account yet", detail: "Connect an advertising account to load spend and sales." }
  }
  if (!health?.has_data) {
    return { title: "Waiting for reports", detail: "The account is connected. Refresh reports to fill this dashboard." }
  }
  return {
    title: "Reports are current",
    detail: health.updated_at ? `Last updated ${formatWhen(health.updated_at)}` : "Campaign data is available.",
  }
}

function statusBadge(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === "executed" || normalized === "connected") return "completed"
  if (normalized === "approved" || normalized === "pending_approval" || normalized === "suggested") return "waiting"
  if (normalized === "failed" || normalized === "rejected") return "failed"
  return "queued"
}

function actionLabel(action: string): string {
  return ACTION_COPY[action] || action.replaceAll("_", " ")
}

function changeLabel(change: Record<string, unknown> | undefined): string {
  if (!change) return ""
  const bid = asNumber(change.bid_change_pct)
  if (bid != null) return `${bid > 0 ? "Raise" : "Lower"} bid by ${Math.abs(bid).toFixed(0)}%`
  const budget = asNumber(change.budget_change_pct)
  if (budget != null) return `${budget > 0 ? "Raise" : "Lower"} budget by ${Math.abs(budget).toFixed(0)}%`
  if (typeof change.negative === "string" && change.negative) return `Negative: ${change.negative}`
  if (typeof change.status === "string" && change.status) return `Set status to ${change.status}`
  return ""
}

function metricNumber(metrics: Record<string, unknown> | undefined, key: string): number | null {
  if (!metrics) return null
  return asNumber(metrics[key])
}

function emptyMetrics(): AmazonAdsWindowMetrics {
  return {
    spend: 0,
    sales: 0,
    orders: 0,
    clicks: 0,
    impressions: 0,
    roas: null,
    acos: null,
    ctr: null,
    cpc: null,
    conversion_rate: null,
  }
}

function suggestOnly(authority: string | undefined): boolean {
  return (authority || AMAZON_ADS_WRITE_AUTHORITY.SUGGEST_ONLY) !== AMAZON_ADS_WRITE_AUTHORITY.EXECUTE_WITHIN_POLICY
}

function kpiTone(kind: "roas" | "acos", value: number | null, target: number | null): string {
  if (value == null || target == null) return ""
  if (kind === "roas") return value >= target ? "ok" : "bad"
  return value <= target ? "ok" : "bad"
}

export function AdsPage() {
  const [connections, setConnections] = useState<AmazonAdsConnection[]>([])
  const [profileId, setProfileId] = useState(readStoredProfile)
  const [endDate, setEndDate] = useState(todayIso)
  const [days, setDays] = useState<AmazonAdsWindowDays>(30)
  const [health, setHealth] = useState<AmazonAdsHealth | null>(null)
  const [windows, setWindows] = useState<Partial<Record<AmazonAdsWindowKey, AmazonAdsWindowMetrics>>>({})
  const [winners, setWinners] = useState<AmazonAdsEntityRow[]>([])
  const [waste, setWaste] = useState<AmazonAdsEntityRow[]>([])
  const [recommendations, setRecommendations] = useState<AmazonAdsRecommendation[]>([])
  const [pending, setPending] = useState<AmazonAdsRecommendation[]>([])
  const [policy, setPolicy] = useState<AmazonAdsPolicy | null>(null)
  const [royaltyPct, setRoyaltyPct] = useState("35")
  const [marginPct, setMarginPct] = useState("0")
  const [otherPct, setOtherPct] = useState("5")
  const [connectLabel, setConnectLabel] = useState("")
  const [connectProfile, setConnectProfile] = useState("")
  const [oauthStart, setOauthStart] = useState<AmazonAdsOAuthStart | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [error, setError] = useState("")

  const profileIds = useMemo(() => profilesFromConnections(connections), [connections])
  const authority = policy?.write_authority || health?.write_authority || AMAZON_ADS_WRITE_AUTHORITY.SUGGEST_ONLY
  const writesAreSuggestions = suggestOnly(authority)
  const selectedWindow = windows[windowKey(days)]
  const breakEven = breakEvenTargets(policy?.break_even || parseBreakEven(health?.break_even_roas))
  const connected = connectionStatus(connections)
  const account = healthLabel(health, connected.tone === "on" || profileIds.length > 0)
  const hasReports = Boolean(health?.has_data && selectedWindow)

  const load = useCallback(async (selected: string, asOf: string, windowDays: AmazonAdsWindowDays) => {
    const [connectionResp, policyResp, pendingResp] = await Promise.all([
      listAmazonAdsConnections().catch(() => ({ connections: [] as AmazonAdsConnection[] })),
      getAmazonAdsPolicy().catch(() => null),
      listAmazonAdsPendingApprovals().catch(() => ({ pending: [] as AmazonAdsRecommendation[] })),
    ])
    setConnections(connectionResp.connections)
    if (policyResp) {
      setPolicy(policyResp)
      const be = policyResp.break_even || {}
      setRoyaltyPct(String(((be.royalty_rate || 0) * 100).toFixed(0)))
      setMarginPct(String(((be.margin_rate || 0) * 100).toFixed(0)))
      setOtherPct(String(((be.other_costs_pct || 0) * 100).toFixed(0)))
    }
    setPending(pendingResp.pending)

    const available = profilesFromConnections(connectionResp.connections)
    let nextProfile = selected
    if (nextProfile && !available.includes(nextProfile) && available.length) {
      nextProfile = available[0]
    } else if (!nextProfile && available.length) {
      nextProfile = available[0]
    }
    if (nextProfile !== selected) {
      setProfileId(nextProfile)
      storeProfile(nextProfile)
    }

    if (!nextProfile) {
      setHealth(null)
      setWindows({})
      setWinners([])
      setWaste([])
      setRecommendations([])
      return
    }

    const [healthResp, metricsResp, ranked, recs] = await Promise.all([
      getAmazonAdsHealth(nextProfile).catch(() => null),
      getAmazonAdsMetrics(nextProfile, asOf).catch(() => null),
      getAmazonAdsWinnersWaste(nextProfile, asOf, windowDays).catch(() => ({ winners: [], waste: [] })),
      listAmazonAdsRecommendations(nextProfile).catch(() => ({ recommendations: [] as AmazonAdsRecommendation[] })),
    ])
    setHealth(healthResp)
    setWindows(metricsResp?.windows || {})
    setWinners(ranked.winners || [])
    setWaste(ranked.waste || [])
    setRecommendations(recs.recommendations)
  }, [])

  useEffect(() => {
    load(profileId, endDate, days).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not load Amazon Ads.")
    })
  }, [days, endDate, load, profileId])

  async function refresh() {
    setError("")
    try {
      await load(profileId, endDate, days)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh Amazon Ads.")
    }
  }

  function selectProfile(id: string) {
    setProfileId(id)
    storeProfile(id)
  }

  async function handleConnect(event: FormEvent) {
    event.preventDefault()
    const label = connectLabel.trim()
    if (!label) {
      setError("Give this advertising account a short name.")
      return
    }
    setBusy(true)
    setError("")
    try {
      const profile = connectProfile.trim()
      const started = await startAmazonAdsOAuth({
        label,
        profile_ids: profile ? [profile] : [],
      })
      setOauthStart(started)
      setMsg("Continue on Amazon to finish connecting. Jarvis does not store keys in this page.")
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the Amazon connection.")
    } finally {
      setBusy(false)
    }
  }

  async function handleIngest() {
    if (!profileId) {
      setError("Choose an advertising profile first.")
      return
    }
    setBusy(true)
    setError("")
    try {
      const result = await ingestAmazonAds({
        profile_id: profileId,
        start_date: addDays(endDate, -(days - 1)),
        end_date: endDate,
      })
      const recCount = result.recommendations ?? 0
      setMsg(
        recCount
          ? `Reports updated. ${recCount} suggestion${recCount === 1 ? "" : "s"} ready to review.`
          : "Reports updated.",
      )
      await load(profileId, endDate, days)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh reports.")
    } finally {
      setBusy(false)
    }
  }

  async function handleApprove(recId: string) {
    setBusy(true)
    setError("")
    try {
      await approveAmazonAdsRecommendation(recId, PORTAL_ACTOR)
      setMsg(
        writesAreSuggestions
          ? "Suggestion approved. Jarvis will not change bids or budgets until write permission is raised."
          : "Suggestion approved. You can apply it when you are ready.",
      )
      await load(profileId, endDate, days)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve that suggestion.")
    } finally {
      setBusy(false)
    }
  }

  async function handleApply(recId: string) {
    if (writesAreSuggestions) {
      setError("Write permission is Suggest only. Jarvis will not spend or change campaigns from this dashboard.")
      return
    }
    setBusy(true)
    setError("")
    try {
      const result = await executeAmazonAdsRecommendation(recId, {
        actor: PORTAL_ACTOR,
        approved: true,
        approval_source: "manual",
      })
      if (result.executed) {
        setMsg("The approved change was sent.")
      } else {
        setError(result.reason || "The change was not applied.")
      }
      await load(profileId, endDate, days)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply that change.")
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveBreakEven(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      const royalty = Number(royaltyPct) / 100
      const margin = Number(marginPct) / 100
      const other = Number(otherPct) / 100
      if ([royalty, margin, other].some((value) => Number.isNaN(value))) {
        setError("Break-even percentages need to be numbers.")
        return
      }
      const next = await updateAmazonAdsPolicy({
        break_even: { royalty_rate: royalty, margin_rate: margin, other_costs_pct: other },
      })
      setPolicy(next)
      setMsg("Break-even settings saved. ROAS is still not treated as profit.")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save break-even settings.")
    } finally {
      setBusy(false)
    }
  }

  const maxSpend = Math.max(
    0.01,
    ...AMAZON_ADS_WINDOWS.map((window) => windows[windowKey(window)]?.spend || 0),
  )
  const pendingForProfile = pending.filter((row) => !profileId || row.profile_id === profileId)

  return (
    <div className="ads-page">
      <h1>Amazon Ads</h1>
      <p className="lede">
        Spend, attributed sales, and efficiency for your advertising account.{" "}
        <strong>ROAS is not profit</strong> — it is attributed sales per ad dollar. ACOS is ad spend as a
        share of those sales. Break-even uses the royalty or margin you set below.
      </p>

      {msg && (
        <div className="card ads-banner ok" role="status">
          {msg}
        </div>
      )}
      {error && (
        <div className="card ads-banner bad" role="alert">
          {error}
        </div>
      )}

      <div className="card ads-toolbar">
        <div className="ads-toolbar-row">
          <label>
            Advertising profile
            <select
              value={profileId}
              onChange={(event) => selectProfile(event.target.value)}
              aria-label="Advertising profile"
            >
              {!profileIds.length && <option value="">No profile connected</option>}
              {profileIds.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
          <label>
            As of
            <input
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              aria-label="Report as-of date"
            />
          </label>
          <div>
            <span className="ads-field-label">Trend window</span>
            <div className="tabs ads-windows">
              {AMAZON_ADS_WINDOWS.map((window) => (
                <button
                  key={window}
                  type="button"
                  className={days === window ? "btn" : "btn secondary"}
                  onClick={() => setDays(window)}
                >
                  {windowLabel(window)}
                </button>
              ))}
            </div>
          </div>
          <button className="btn secondary" type="button" disabled={busy || !profileId} onClick={handleIngest}>
            Refresh reports
          </button>
        </div>
      </div>

      <section className="grid cards ads-health">
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Account health</div>
          <strong>{account.title}</strong>
          <p className="ads-hint">{account.detail}</p>
          <p className="ads-hint">
            <span className={`dot ${connected.tone}`} />
            {connected.label}
            {connections.length ? ` · ${connections.length} account${connections.length === 1 ? "" : "s"}` : ""}
          </p>
        </div>
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Spend</div>
          <strong className="ads-kpi-value">{formatMoney(hasReports ? selectedWindow?.spend : null)}</strong>
          <p className="ads-hint">{windowLabel(days)} through {endDate}</p>
        </div>
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Attributed sales</div>
          <strong className="ads-kpi-value">{formatMoney(hasReports ? selectedWindow?.sales : null)}</strong>
          <p className="ads-hint">
            {hasReports ? `${selectedWindow?.orders ?? 0} orders · ${selectedWindow?.clicks ?? 0} clicks` : "No report yet"}
          </p>
        </div>
        <div className={`card ads-kpi ${kpiTone("roas", selectedWindow?.roas ?? null, breakEven.roas)}`}>
          <div className="lede" style={{ marginBottom: 6 }}>ROAS</div>
          <strong className="ads-kpi-value">{formatRoas(hasReports ? selectedWindow?.roas : null)}</strong>
          <p className="ads-hint">
            Attributed sales ÷ spend. Not profit.
            {breakEven.roas != null ? ` Break-even ${formatRoas(breakEven.roas)}.` : ""}
          </p>
        </div>
        <div className={`card ads-kpi ${kpiTone("acos", selectedWindow?.acos ?? null, breakEven.acos)}`}>
          <div className="lede" style={{ marginBottom: 6 }}>ACOS</div>
          <strong className="ads-kpi-value">{formatAcos(hasReports ? selectedWindow?.acos : null)}</strong>
          <p className="ads-hint">
            Spend ÷ attributed sales.
            {breakEven.acos != null ? ` Break-even ${formatAcos(breakEven.acos)}.` : ""}
          </p>
        </div>
        <div className="card">
          <div className="lede" style={{ marginBottom: 6 }}>Write permission</div>
          <span className={`badge ${writesAreSuggestions ? "waiting" : "failed"}`}>
            {writesAreSuggestions ? "Suggest only" : "Bounded writes"}
          </span>
          <p className="ads-hint">
            {writesAreSuggestions
              ? "Jarvis can recommend pauses, bid, and budget changes. It will not spend on its own."
              : "Approved changes can run inside the caps already set. This is not unrestricted spend."}
          </p>
        </div>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Trend</h2>
        <p className="lede">Compare the last 7, 14, and 30 days. Highlighted row is the window you selected.</p>
        <div className="ads-trend-bars">
          {AMAZON_ADS_WINDOWS.map((window) => {
            const metrics = windows[windowKey(window)] || emptyMetrics()
            const width = `${Math.max(4, (metrics.spend / maxSpend) * 100)}%`
            return (
              <button
                key={window}
                type="button"
                className={`ads-trend-row${days === window ? " selected" : ""}`}
                onClick={() => setDays(window)}
              >
                <span>{windowLabel(window)}</span>
                <span className="ads-bar-track" aria-hidden="true">
                  <span className="ads-bar-fill" style={{ width }} />
                </span>
                <span>{formatMoney(metrics.spend)}</span>
              </button>
            )
          })}
        </div>
        <table>
          <thead>
            <tr>
              <th>Window</th>
              <th>Spend</th>
              <th>Attributed sales</th>
              <th>ROAS</th>
              <th>ACOS</th>
              <th>Orders</th>
            </tr>
          </thead>
          <tbody>
            {AMAZON_ADS_WINDOWS.map((window) => {
              const metrics = windows[windowKey(window)]
              return (
                <tr key={window} className={days === window ? "ads-row-active" : undefined}>
                  <td>{windowLabel(window)}</td>
                  <td>{formatMoney(metrics?.spend)}</td>
                  <td>{formatMoney(metrics?.sales)}</td>
                  <td>{formatRoas(metrics?.roas)}</td>
                  <td>{formatAcos(metrics?.acos)}</td>
                  <td>{metrics?.orders ?? "—"}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      <div className="grid two ads-split">
        <section className="card">
          <h2>Top winners</h2>
          <p className="lede">Highest ROAS with at least one order in this window.</p>
          <EntityTable rows={winners} empty="No winners in this window yet." />
        </section>
        <section className="card">
          <h2>Top waste</h2>
          <p className="lede">Spend with zero orders — the first place to look.</p>
          <EntityTable rows={waste} empty="No wasted spend in this window." />
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Recommendations</h2>
        <p className="lede">
          Each suggestion includes the evidence window and why it was raised. Default permission is suggest
          only — nothing here spends until you raise write permission.
        </p>
        {recommendations.length === 0 && <p className="ads-hint">No suggestions yet. Refresh reports after connecting an account.</p>}
        {recommendations.map((rec) => (
          <RecommendationCard
            key={rec.id}
            rec={rec}
            busy={busy}
            writesAreSuggestions={writesAreSuggestions}
            onApprove={handleApprove}
            onApply={handleApply}
          />
        ))}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Pending approvals</h2>
        <p className="lede">Suggestions waiting for you. Approving does not change bids or budgets by itself.</p>
        {pendingForProfile.length === 0 && <p className="ads-hint">Nothing waiting.</p>}
        {pendingForProfile.map((rec) => (
          <div key={rec.id} className="ads-pending">
            <div>
              <strong>{actionLabel(rec.proposed_action)}</strong>
              <p>{rec.rationale}</p>
              <p className="ads-hint">
                {rec.entity_id}
                {rec.evidence_window_days ? ` · Last ${rec.evidence_window_days} days` : ""}
              </p>
            </div>
            <button className="btn" type="button" disabled={busy} onClick={() => handleApprove(rec.id)}>
              Approve
            </button>
          </div>
        ))}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Break-even</h2>
        <p className="lede">
          Optional royalty or margin so Jarvis can tell revenue efficiency from contribution. Leave margin at
          0 to use royalty. Other costs come off the top.
        </p>
        <form className="ads-breakeven" onSubmit={handleSaveBreakEven}>
          <label>
            Royalty %
            <input
              type="number"
              min="0"
              max="100"
              step="1"
              value={royaltyPct}
              onChange={(event) => setRoyaltyPct(event.target.value)}
            />
          </label>
          <label>
            Margin %
            <input
              type="number"
              min="0"
              max="100"
              step="1"
              value={marginPct}
              onChange={(event) => setMarginPct(event.target.value)}
            />
          </label>
          <label>
            Other costs %
            <input
              type="number"
              min="0"
              max="100"
              step="1"
              value={otherPct}
              onChange={(event) => setOtherPct(event.target.value)}
            />
          </label>
          <div className="ads-breakeven-result">
            <div>
              <b>Break-even ROAS</b>
              <span>{formatRoas(breakEven.roas)}</span>
            </div>
            <div>
              <b>Break-even ACOS</b>
              <span>{formatAcos(breakEven.acos)}</span>
            </div>
          </div>
          <button className="btn" type="submit" disabled={busy}>
            Save break-even
          </button>
        </form>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Amazon account</h2>
        <p className="lede">
          Connection status only. Live Amazon keys stay in the server environment or vault — never in this
          page or in git.
        </p>
        {connections.length === 0 && (
          <p className="ads-hint">No advertising account connected yet.</p>
        )}
        {connections.map((connection) => (
          <div key={connection.id} className="ads-connection">
            <div>
              <strong>{connection.label || "Amazon Ads"}</strong>
              <p className="ads-hint">
                {(connection.profile_ids || []).join(", ") || "No advertising profile listed"}
              </p>
            </div>
            <span className={`badge ${statusBadge(connection.status || "")}`}>
              {connection.status || "unknown"}
            </span>
          </div>
        ))}
        <form className="ads-connect" onSubmit={handleConnect}>
          <label>
            Account name
            <input
              type="text"
              value={connectLabel}
              onChange={(event) => setConnectLabel(event.target.value)}
              placeholder="Publishing ads"
            />
          </label>
          <label>
            Advertising profile ID
            <input
              type="text"
              value={connectProfile}
              onChange={(event) => setConnectProfile(event.target.value)}
              placeholder="Optional"
            />
          </label>
          <button className="btn secondary" type="submit" disabled={busy}>
            Start Amazon connection
          </button>
        </form>
        {oauthStart?.authorization_url && (
          <p className="ads-hint">
            <a href={oauthStart.authorization_url} target="_blank" rel="noreferrer">
              Continue on Amazon
            </a>
          </p>
        )}
      </section>
    </div>
  )
}

function EntityTable({ rows, empty }: { rows: AmazonAdsEntityRow[]; empty: string }) {
  if (!rows.length) return <p className="ads-hint">{empty}</p>
  return (
    <table>
      <thead>
        <tr>
          <th>Target</th>
          <th>Spend</th>
          <th>Sales</th>
          <th>ROAS</th>
          <th>ACOS</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.entity_id || row.text}>
            <td>{row.text || row.entity_id || "—"}</td>
            <td>{formatMoney(row.spend)}</td>
            <td>{formatMoney(row.sales)}</td>
            <td>{formatRoas(row.roas)}</td>
            <td>{formatAcos(row.acos)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function RecommendationCard({
  rec,
  busy,
  writesAreSuggestions,
  onApprove,
  onApply,
}: {
  rec: AmazonAdsRecommendation
  busy: boolean
  writesAreSuggestions: boolean
  onApprove: (id: string) => void
  onApply: (id: string) => void
}) {
  const canApprove = rec.status === "suggested" || rec.status === "pending_approval"
  const canApply = rec.status === "approved" && !writesAreSuggestions
  const change = changeLabel(rec.proposed_change)
  return (
    <article className="ads-rec">
      <div className="ads-rec-head">
        <strong>{actionLabel(rec.proposed_action)}</strong>
        <span className={`badge ${statusBadge(rec.status)}`}>{rec.status.replaceAll("_", " ")}</span>
      </div>
      <p>{rec.rationale}</p>
      <p className="ads-hint">
        {rec.entity_type} {rec.entity_id}
        {rec.evidence_window_days ? ` · Evidence: last ${rec.evidence_window_days} days` : ""}
        {typeof rec.confidence === "number" ? ` · Confidence ${formatPct(rec.confidence, 0)}` : ""}
      </p>
      <div className="ads-rec-metrics">
        <span>Spend {formatMoney(metricNumber(rec.metrics, "spend"))}</span>
        <span>Sales {formatMoney(metricNumber(rec.metrics, "sales"))}</span>
        <span>ROAS {formatRoas(metricNumber(rec.metrics, "roas"))}</span>
        <span>ACOS {formatAcos(metricNumber(rec.metrics, "acos"))}</span>
      </div>
      {change && <p className="ads-hint">{change}</p>}
      {rec.estimated_impact && <p className="ads-hint">{rec.estimated_impact}</p>}
      <div className="row">
        {canApprove && (
          <button className="btn" type="button" disabled={busy} onClick={() => onApprove(rec.id)}>
            Approve
          </button>
        )}
        {canApply && (
          <button className="btn secondary" type="button" disabled={busy} onClick={() => onApply(rec.id)}>
            Apply approved change
          </button>
        )}
        {rec.status === "approved" && writesAreSuggestions && (
          <span className="ads-hint">Queued. Jarvis will not spend while permission is Suggest only.</span>
        )}
      </div>
    </article>
  )
}
