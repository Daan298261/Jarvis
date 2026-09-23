import assert from "node:assert/strict"
import { describe, test } from "node:test"

const view = await import("./src/settings/automationBreakerView.ts")

function sample(overrides = {}) {
  return {
    automation_id: "sched-nightly",
    consecutive_failure_count: 3,
    failure_threshold: 3,
    last_failure_at: "2026-09-11T08:00:00.000Z",
    last_failure_summary: "verifier rejected the export",
    breaker_state: "DISABLED_BY_FAILURE",
    disabled_at: "2026-09-11T08:00:01.000Z",
    recent_failed_run_ids: ["task-1", "task-2"],
    recent_failed_runs: [{ task_or_run_id: "task-1" }, { task_or_run_id: "task-2" }],
    kind: "schedule",
    ref_id: "nightly",
    updated_at: "2026-09-11T08:00:01.000Z",
    ...overrides,
  }
}

describe("automation breaker view", () => {
  test("parses public views and prefers recent_failed_runs", () => {
    const rows = view.parseBreakerList({
      automations: [sample({ recent_failed_run_ids: ["ignored"] })],
    })
    assert.equal(rows.length, 1)
    assert.deepEqual(
      rows[0].recent_failed_runs.map((run) => run.task_or_run_id),
      ["task-1", "task-2"],
    )
    assert.equal(rows[0].consecutive_failure_count, 3)
    assert.equal(rows[0].failure_threshold, 3)
    assert.equal(rows[0].breaker_state, "DISABLED_BY_FAILURE")
  })

  test("falls back to recent_failed_run_ids when run objects are absent", () => {
    const parsed = view.parseAutomationBreaker(sample({
      recent_failed_runs: [],
      recent_failed_run_ids: ["run-9"],
    }))
    assert.deepEqual(parsed.recent_failed_runs, [{ task_or_run_id: "run-9" }])
  })

  test("rejects a list that is not the breaker payload", () => {
    assert.throws(
      () => view.parseBreakerList({ ok: true }),
      /did not include automations/,
    )
    assert.throws(
      () => view.parseBreakerList({ automations: [{ automation_id: "x", breaker_state: "ACTIVE" }] }),
      /missing required state/,
    )
  })

  test("does not coerce an unknown state into ACTIVE", () => {
    const parsed = view.parseAutomationBreaker(sample({
      breaker_state: "MYSTERY",
      consecutive_failure_count: 0,
      last_failure_summary: "",
      last_failure_at: null,
      disabled_at: null,
    }))
    assert.equal(parsed.breaker_state, "MYSTERY")
    assert.equal(view.isKnownBreakerState(parsed.breaker_state), false)
    assert.equal(view.canReenableBreaker(parsed.breaker_state), false)
    assert.equal(view.breakerBadgeClass(parsed.breaker_state), "queued")
    assert.match(view.breakerStateCaption(parsed.breaker_state), /not confirmed healthy/)
    assert.equal(view.failureSummaryText(parsed), "No failure summary was returned.")
  })

  test("re-enable is only offered for DISABLED_BY_FAILURE", () => {
    assert.equal(view.canReenableBreaker("DISABLED_BY_FAILURE"), true)
    assert.equal(view.canReenableBreaker("ACTIVE"), false)
    assert.equal(view.canReenableBreaker("DEGRADED"), false)
    assert.equal(view.breakerBadgeClass("ACTIVE"), "ok")
    assert.equal(view.breakerBadgeClass("DEGRADED"), "waiting")
    assert.equal(view.breakerBadgeClass("DISABLED_BY_FAILURE"), "failed")
  })

  test("threshold input accepts only integers 1 through 100", () => {
    assert.equal(view.parseThresholdInput("1"), 1)
    assert.equal(view.parseThresholdInput("100"), 100)
    assert.equal(view.parseThresholdInput("0"), null)
    assert.equal(view.parseThresholdInput("101"), null)
    assert.equal(view.parseThresholdInput("3.5"), null)
    assert.equal(view.parseThresholdInput(""), null)
    assert.equal(view.parseThresholdInput(" 8 "), 8)
  })

  test("surfaces 400 and 403 without masking them as a healthy miss", () => {
    const denied = Object.assign(new Error("Automation cannot re-enable itself"), { status: 403 })
    assert.match(view.breakerFailureMessage(denied, "reenable"), /403/)
    assert.match(view.breakerFailureMessage(denied, "reenable"), /cannot re-enable itself/)

    const masked = Object.assign(
      new Error("There's a setup problem. Jarvis is working on a fix."),
      { status: 403 },
    )
    const maskedMessage = view.breakerFailureMessage(masked, "reenable")
    assert.match(maskedMessage, /403/)
    assert.doesNotMatch(maskedMessage, /setup problem/)

    const bad = Object.assign(new Error("actor is required for re-enable"), { status: 400 })
    assert.match(view.breakerFailureMessage(bad, "reenable"), /400/)
    assert.match(view.breakerFailureMessage(bad, "reenable"), /actor is required/)

    const unauthorized = Object.assign(new Error("Valid owner private key required"), { status: 401 })
    assert.match(view.breakerFailureMessage(unauthorized, "threshold"), /401/)
  })

  test("parses audit events and keeps trip evidence", () => {
    const events = view.parseBreakerAudit({
      events: [{
        id: "evt-1",
        event_type: "breaker_tripped",
        automation_id: "sched-nightly",
        actor: "system",
        timestamp: "2026-09-11T08:00:01.000Z",
        detail: {
          consecutive_failure_count: 3,
          failure_threshold: 3,
          last_failure_summary: "verifier rejected the export",
        },
      }],
    })
    assert.equal(view.breakerAuditLabel(events[0].event_type), "Breaker tripped")
    assert.match(view.formatAuditDetail(events[0].detail), /consecutive failure count: 3/)
    assert.equal(view.auditEventsForAutomation(events, "other").length, 0)
    assert.equal(view.auditEventsForAutomation(events, "sched-nightly").length, 1)
  })

  test("rejects an audit payload that omits events", () => {
    assert.throws(() => view.parseBreakerAudit({}), /did not include events/)
  })
})
