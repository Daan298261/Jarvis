import assert from "node:assert/strict"
import { describe, test } from "node:test"

const recovery = await import("./src/companionPairingRecovery.ts")

describe("pairing retry backoff", () => {
  test("ramps then holds at 30s", () => {
    assert.deepEqual([0, 1, 2, 3, 4, 5, 50].map(recovery.pairingRetryDelayMs), [2000, 4000, 8000, 15000, 30000, 30000, 30000])
  })
})

describe("manager status summary", () => {
  test("unreachable manager tells the owner to start ANZU", () => {
    assert.match(recovery.describeManagerView({ kind: "unreachable" }), /Manager is not running/)
  })
  test("crash with pending watchdog restart shows reason and countdown", () => {
    const text = recovery.describeManagerView({
      kind: "status",
      status: {
        core: { state: "stopped", healthy: false, process_present: false },
        supervisor: { enabled: true, desired_running: true, restarting: false, restart_attempts: 1, next_restart_in_seconds: 12, last_exit: { reason: "backend process exited" } },
      },
    })
    assert.equal(text, "ANZU backend stopped (backend process exited). Automatic restart in 12s.")
  })
  test("owner stop is not presented as auto-restarting", () => {
    const text = recovery.describeManagerView({
      kind: "status",
      status: { core: { state: "stopped", healthy: false, process_present: false }, supervisor: { enabled: true, desired_running: false, restarting: false, restart_attempts: 0, next_restart_in_seconds: 0, last_exit: null } },
    })
    assert.equal(text, "ANZU backend is stopped.")
  })
})

describe("manager calls", () => {
  test("network failure maps to unreachable", async () => {
    const view = await recovery.fetchManagerStatus(async () => { throw new TypeError("Failed to fetch") })
    assert.deepEqual(view, { kind: "unreachable" })
  })
  test("restart posts explicit confirmation", async () => {
    let seen
    const result = await recovery.requestManagerRestart(async (url, init) => {
      seen = { url, body: init.body, method: init.method }
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    assert.equal(result.ok, true)
    assert.equal(seen.url, "http://127.0.0.1:4782/api/manager/v1/control/restart")
    assert.equal(seen.method, "POST")
    assert.deepEqual(JSON.parse(seen.body), { confirm: true })
  })
})
