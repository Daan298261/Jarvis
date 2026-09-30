import assert from "node:assert/strict"
import { describe, test } from "node:test"

const status = await import("./src/taskStatus.ts")

function sampleTask(overrides = {}) {
  return {
    id: "task-1",
    title: "Ship verifier UI",
    prompt: "Show phase and verification",
    status: "completed",
    state: "completed",
    stage: "completed",
    execution_phase: "COMPLETED",
    current_action: "Thinking…",
    current_activity: "Verifying 3 changed files",
    current_tool: "filesystem",
    result: "done",
    error: "",
    retries: 0,
    duration_seconds: 42,
    elapsed_seconds: 42,
    waiting_for_confirmation: false,
    created_at: "2026-09-30T12:00:00+00:00",
    verification_summary: {
      result: "NOT_VERIFIED",
      verifier: { type: "agent", name: "" },
      checks: [],
      evidence_refs: [],
      warnings: [],
    },
    ...overrides,
  }
}

describe("RFC-0026 task status helpers", () => {
  test("prefers current_activity over Thinking… / generic action", () => {
    assert.equal(status.activityLabel(sampleTask()), "Verifying 3 changed files")
    assert.equal(
      status.activityLabel(sampleTask({ current_activity: "", current_action: "Running filesystem" })),
      "Running filesystem",
    )
    assert.equal(
      status.activityLabel(sampleTask({
        current_activity: "Thinking hard",
        current_action: "Thinking…",
        current_tool: "python",
      })),
      "Running python",
    )
  })

  test("keeps lifecycle and phase labels distinct", () => {
    const task = sampleTask({ state: "running", status: "running", execution_phase: "WAITING_APPROVAL" })
    assert.equal(status.lifecycleLabel(task), "running")
    assert.equal(status.phaseLabel(task), "waiting approval")
    assert.equal(status.phaseBadgeClass(task), "waiting")
  })

  test("formats only deterministic progress units", () => {
    assert.equal(status.formatProgress(null), "")
    assert.equal(status.formatProgress({ completed_units: 3, total_units: 5, unit_type: "plan_steps" }), "3 / 5 plan steps")
    assert.equal(status.formatProgress({ completed_units: 9, total_units: 5, unit_type: "files" }), "")
    assert.equal(status.formatPercentProgress({ completed_units: 1, total_units: 4, unit_type: "files" }), "1 / 4 files (25%)")
  })

  test("renders verification checks from object API shape", () => {
    const check = {
      type: "deterministic",
      target: "pytest",
      result: "pass",
      severity: "info",
      evidence: "12 passed",
    }
    assert.match(status.checkLabel(check), /deterministic · pytest: pass/)
    assert.match(status.checkLabel(check), /12 passed/)
    assert.equal(status.checkLabel("legacy string check"), "legacy string check")
  })

  test("never treats unverified success as verified", () => {
    const completed = sampleTask()
    assert.equal(status.shouldShowVerification(completed), true)
    assert.equal(status.verificationLabel(completed.verification_summary), "not verified")
    assert.equal(status.verificationBadgeClass(completed.verification_summary), "not-verified")

    const verified = sampleTask({
      verification_summary: {
        result: "VERIFIED",
        verifier: { type: "agent", name: "Jarvis verifier" },
        checks: [{ type: "agent", target: "task", result: "pass", evidence: "pytest passed" }],
        evidence_refs: [],
        warnings: [],
      },
    })
    assert.equal(status.verificationLabel(verified.verification_summary), "verified")
    assert.equal(status.verificationBadgeClass(verified.verification_summary), "verified")
    assert.notEqual(
      status.verificationBadgeClass(completed.verification_summary),
      status.verificationBadgeClass(verified.verification_summary),
    )
  })

  test("hides empty NOT_VERIFIED while task is still running", () => {
    const running = sampleTask({
      status: "running",
      state: "running",
      execution_phase: "EXECUTING",
      verification_summary: {
        result: "NOT_VERIFIED",
        checks: [],
        warnings: [],
        evidence_refs: [],
      },
    })
    assert.equal(status.shouldShowVerification(running), false)
  })

  test("links WAITING_APPROVAL to Decision Inbox", () => {
    assert.equal(
      status.decisionInboxHref(sampleTask({
        status: "waiting",
        state: "waiting",
        execution_phase: "WAITING_APPROVAL",
        waiting_for_confirmation: true,
        decision_inbox_item_id: "di-1",
      })),
      "/coding",
    )
    assert.equal(status.decisionInboxHref(sampleTask()), null)
  })

  test("compactStatusLine stays compact and concrete", () => {
    const line = status.compactStatusLine(sampleTask({
      status: "running",
      state: "running",
      execution_phase: "EXECUTING",
      progress: { completed_units: 2, total_units: 8, unit_type: "files" },
    }))
    assert.match(line, /executing/i)
    assert.match(line, /Verifying 3 changed files/)
    assert.match(line, /2 \/ 8 files/)
  })
})
