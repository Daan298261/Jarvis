import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  listAutomationBreakerAudit,
  listAutomationBreakers,
  reenableAutomationBreaker,
  setAutomationBreakerThreshold,
} from "../api"
import {
  BREAKER_DISABLED_BY_FAILURE,
  auditEventsForAutomation,
  breakerAuditLabel,
  breakerBadgeClass,
  breakerFailureMessage,
  breakerStateCaption,
  canReenableBreaker,
  failureSummaryText,
  formatAuditDetail,
  formatBreakerTimestamp,
  parseAutomationBreaker,
  parseBreakerAudit,
  parseBreakerList,
  parseThresholdInput,
  type AutomationBreakerAuditEvent,
  type AutomationBreakerView,
} from "./automationBreakerView"

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; automations: AutomationBreakerView[] }

type AuditState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; events: AutomationBreakerAuditEvent[] }

type BusyAction = "reenable" | "threshold"

type BreakerFetch = {
  list: LoadState
  audit: AuditState
  thresholds: Record<string, string>
}

async function fetchBreakerPanel(): Promise<BreakerFetch> {
  const [listResult, auditResult] = await Promise.allSettled([
    listAutomationBreakers(),
    listAutomationBreakerAudit({ limit: 100 }),
  ])
  let list: LoadState
  let thresholds: Record<string, string> = {}
  if (listResult.status === "fulfilled") {
    try {
      const automations = parseBreakerList(listResult.value)
      list = { status: "ready", automations }
      thresholds = Object.fromEntries(
        automations.map((row) => [row.automation_id, String(row.failure_threshold)]),
      )
    } catch (err) {
      list = { status: "error", message: breakerFailureMessage(err, "list") }
    }
  } else {
    list = { status: "error", message: breakerFailureMessage(listResult.reason, "list") }
  }
  let audit: AuditState
  if (auditResult.status === "fulfilled") {
    try {
      audit = { status: "ready", events: parseBreakerAudit(auditResult.value) }
    } catch (err) {
      audit = { status: "error", message: breakerFailureMessage(err, "audit") }
    }
  } else {
    audit = { status: "error", message: breakerFailureMessage(auditResult.reason, "audit") }
  }
  return { list, audit, thresholds }
}

export function AutomationBreakerPanel() {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" })
  const [auditState, setAuditState] = useState<AuditState>({ status: "loading" })
  const [thresholds, setThresholds] = useState<Record<string, string>>({})
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<{ id: string; action: BusyAction } | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const applyFetch = useCallback((result: BreakerFetch) => {
    setLoadState(result.list)
    setAuditState(result.audit)
    if (result.list.status === "ready") setThresholds(result.thresholds)
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const result = await fetchBreakerPanel()
        if (!cancelled) applyFetch(result)
      } catch (err) {
        if (cancelled) return
        setLoadState({ status: "error", message: breakerFailureMessage(err, "list") })
        setAuditState({ status: "error", message: breakerFailureMessage(err, "audit") })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [applyFetch])

  async function onRefresh() {
    setRefreshing(true)
    setRowErrors({})
    try {
      applyFetch(await fetchBreakerPanel())
    } catch (err) {
      setLoadState({ status: "error", message: breakerFailureMessage(err, "list") })
      setAuditState({ status: "error", message: breakerFailureMessage(err, "audit") })
    } finally {
      setRefreshing(false)
    }
  }

  function replaceAutomation(next: AutomationBreakerView) {
    setLoadState((prev) => {
      if (prev.status !== "ready") return prev
      const exists = prev.automations.some((row) => row.automation_id === next.automation_id)
      const automations = exists
        ? prev.automations.map((row) => (row.automation_id === next.automation_id ? next : row))
        : [...prev.automations, next]
      return { status: "ready", automations }
    })
    setThresholds((prev) => ({ ...prev, [next.automation_id]: String(next.failure_threshold) }))
  }

  async function reloadAudit() {
    try {
      const payload = await listAutomationBreakerAudit({ limit: 100 })
      setAuditState({ status: "ready", events: parseBreakerAudit(payload) })
    } catch (err) {
      setAuditState({ status: "error", message: breakerFailureMessage(err, "audit") })
    }
  }

  async function onReenable(row: AutomationBreakerView) {
    if (!canReenableBreaker(row.breaker_state) || busy || refreshing) return
    setBusy({ id: row.automation_id, action: "reenable" })
    setRowErrors((prev) => ({ ...prev, [row.automation_id]: "" }))
    try {
      const payload = await reenableAutomationBreaker(row.automation_id)
      const parsed = parseAutomationBreaker(payload)
      if (!parsed || parsed.automation_id !== row.automation_id) {
        setRowErrors((prev) => ({
          ...prev,
          [row.automation_id]: "Re-enable returned an unusable breaker record. Status was not changed in this view.",
        }))
        return
      }
      replaceAutomation(parsed)
      if (parsed.breaker_state === BREAKER_DISABLED_BY_FAILURE) {
        setRowErrors((prev) => ({
          ...prev,
          [row.automation_id]: "Re-enable returned, but this automation is still disabled by failure.",
        }))
      }
      await reloadAudit()
    } catch (err) {
      setRowErrors((prev) => ({
        ...prev,
        [row.automation_id]: breakerFailureMessage(err, "reenable"),
      }))
    } finally {
      setBusy(null)
    }
  }

  async function onSaveThreshold(row: AutomationBreakerView) {
    if (busy || refreshing) return
    const next = parseThresholdInput(thresholds[row.automation_id] ?? "")
    if (next == null) {
      setRowErrors((prev) => ({
        ...prev,
        [row.automation_id]: "Threshold must be a whole number from 1 to 100.",
      }))
      return
    }
    setBusy({ id: row.automation_id, action: "threshold" })
    setRowErrors((prev) => ({ ...prev, [row.automation_id]: "" }))
    try {
      const payload = await setAutomationBreakerThreshold(row.automation_id, next)
      const parsed = parseAutomationBreaker(payload)
      if (!parsed || parsed.automation_id !== row.automation_id) {
        setRowErrors((prev) => ({
          ...prev,
          [row.automation_id]: "Threshold update returned an unusable breaker record. The saved threshold was not confirmed.",
        }))
        return
      }
      if (parsed.failure_threshold !== next) {
        replaceAutomation(parsed)
        setRowErrors((prev) => ({
          ...prev,
          [row.automation_id]: `Threshold update returned ${parsed.failure_threshold}, not ${next}. Showing the returned record.`,
        }))
        return
      }
      replaceAutomation(parsed)
      await reloadAudit()
    } catch (err) {
      setRowErrors((prev) => ({
        ...prev,
        [row.automation_id]: breakerFailureMessage(err, "threshold"),
      }))
    } finally {
      setBusy(null)
    }
  }

  const locked = refreshing || busy !== null
  const automations = loadState.status === "ready" ? loadState.automations : []

  return (
    <div className="card grid settings-pane-card" id="automation-breaker">
      <h2 id="automation-breaker-title">Automation circuit breaker</h2>
      <p className="lede" style={{ margin: 0 }}>
        Scheduled and event automations stop after repeated terminal failures. This list is the
        breaker record: state, consecutive failures against the threshold, and the last failure.
        Re-enable is an owner action. An automation cannot clear its own breaker.
      </p>
      <div className="row">
        <button
          className="btn secondary"
          type="button"
          disabled={locked || loadState.status === "loading"}
          onClick={() => void onRefresh()}
        >
          {refreshing || loadState.status === "loading" ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {loadState.status === "error" && (
        <div className="rail-error" role="alert" style={{ margin: 0 }}>
          <p>{loadState.message}</p>
          <p>Breaker status is hidden until the list loads. Nothing here is assumed healthy.</p>
        </div>
      )}

      {loadState.status === "loading" && (
        <p className="lede" style={{ margin: 0 }}>Loading breaker status…</p>
      )}

      {loadState.status === "ready" && automations.length === 0 && (
        <p className="lede" style={{ margin: 0 }}>
          No automations are registered with the circuit breaker yet.
        </p>
      )}

      {loadState.status === "ready" && auditState.status === "error" && (
        <div className="rail-error" role="alert" style={{ margin: 0 }}>
          <p>{auditState.message}</p>
          <p>Audit history is hidden. Breaker rows still come from the list response only.</p>
        </div>
      )}

      {automations.map((row) => {
        const rowBusy = busy?.id === row.automation_id
        const events = auditState.status === "ready"
          ? auditEventsForAutomation(auditState.events, row.automation_id)
          : []
        const rowError = rowErrors[row.automation_id]
        return (
          <section key={row.automation_id} style={{ borderTop: "1px solid var(--line)", paddingTop: 16 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{row.automation_id}</strong>
              <span className={`badge ${breakerBadgeClass(row.breaker_state)}`}>{row.breaker_state}</span>
            </div>
            <p className="lede" style={{ margin: "8px 0 0" }}>{breakerStateCaption(row.breaker_state)}</p>
            <div className="kv" style={{ marginTop: 12 }}>
              <b>Consecutive failures</b>
              <span>{row.consecutive_failure_count} / {row.failure_threshold}</span>
              <b>Kind</b>
              <span>{row.kind || "Not returned"}</span>
              {row.ref_id ? (<><b>Reference</b><span>{row.ref_id}</span></>) : null}
              <b>Last failure</b>
              <span>{formatBreakerTimestamp(row.last_failure_at)}</span>
              <b>Failure summary</b>
              <span>{failureSummaryText(row)}</span>
              {row.breaker_state === BREAKER_DISABLED_BY_FAILURE ? (
                <>
                  <b>Disabled at</b>
                  <span>
                    {row.disabled_at
                      ? formatBreakerTimestamp(row.disabled_at)
                      : "Disabled time was not returned."}
                  </span>
                </>
              ) : null}
              <b>Updated</b>
              <span>{row.updated_at ? formatBreakerTimestamp(row.updated_at) : "Not recorded"}</span>
            </div>

            <div style={{ marginTop: 12 }}>
              <strong>Recent failed runs</strong>
              {row.recent_failed_runs.length === 0 ? (
                <p className="lede" style={{ margin: "6px 0 0" }}>
                  {row.consecutive_failure_count > 0 || row.breaker_state === BREAKER_DISABLED_BY_FAILURE
                    ? "No recent failed runs were returned."
                    : "No failed runs recorded."}
                </p>
              ) : (
                <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {row.recent_failed_runs.map((run) => (
                    <li key={run.task_or_run_id}>
                      <Link to={`/tasks/${encodeURIComponent(run.task_or_run_id)}`}>{run.task_or_run_id}</Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {canReenableBreaker(row.breaker_state) && (
              <div style={{ marginTop: 12 }}>
                <button
                  className="btn danger"
                  type="button"
                  disabled={locked}
                  aria-busy={rowBusy && busy?.action === "reenable"}
                  onClick={() => void onReenable(row)}
                >
                  {rowBusy && busy?.action === "reenable" ? "Re-enabling…" : "Re-enable"}
                </button>
                <p className="lede" style={{ margin: "8px 0 0" }}>
                  Owner only. Sends <code>actor: owner</code> to the re-enable endpoint.
                </p>
              </div>
            )}

            <form
              style={{ marginTop: 12 }}
              noValidate
              onSubmit={(event) => {
                event.preventDefault()
                void onSaveThreshold(row)
              }}
            >
              <label>
                Failure threshold (1–100)
                <input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={thresholds[row.automation_id] ?? String(row.failure_threshold)}
                  disabled={locked}
                  onChange={(event) => {
                    const value = event.target.value
                    setThresholds((prev) => ({ ...prev, [row.automation_id]: value }))
                  }}
                />
              </label>
              <div className="row" style={{ marginTop: 8 }}>
                <button
                  className="btn secondary"
                  type="submit"
                  disabled={locked}
                  aria-busy={rowBusy && busy?.action === "threshold"}
                >
                  {rowBusy && busy?.action === "threshold" ? "Saving…" : "Save threshold"}
                </button>
              </div>
            </form>

            {rowError ? (
              <div className="rail-error" role="alert" style={{ margin: "10px 0 0" }}>
                <p>{rowError}</p>
              </div>
            ) : null}

            {auditState.status === "ready" && (
              <div style={{ marginTop: 12 }}>
                <strong>Audit</strong>
                {events.length === 0 ? (
                  <p className="lede" style={{ margin: "6px 0 0" }}>
                    No audit events for this automation in the latest 100.
                  </p>
                ) : (
                  <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                    {events.map((event) => {
                      const detail = formatAuditDetail(event.detail)
                      return (
                        <li key={event.id}>
                          <strong>{breakerAuditLabel(event.event_type)}</strong>
                          {" · "}
                          {formatBreakerTimestamp(event.timestamp)}
                          {" · "}
                          {event.actor}
                          {detail ? <div className="stat">{detail}</div> : null}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
