import assert from "node:assert/strict"
import { before, describe, test } from "node:test"

const apiStub = await import("./apply-runtime-profile-api-stub.mjs")
const autostart = await import("./src/hud/hexstrikeAutostart.ts")
const applyMod = await import("./src/hud/applyRuntimeProfile.ts")

function installWindow() {
  const events = []
  globalThis.window = {
    setTimeout,
    dispatchEvent(event) {
      events.push(event)
      return true
    },
  }
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, init = {}) {
      this.type = type
      this.detail = init.detail
    }
  }
  return events
}

before(() => {
  installWindow()
})

describe("hexStrikePermissionAllowsAutostart", () => {
  test("allow is granted", () => {
    assert.equal(autostart.hexStrikePermissionAllowsAutostart("allow"), true)
  })
  test("ask and deny are not granted", () => {
    assert.equal(autostart.hexStrikePermissionAllowsAutostart("ask"), false)
    assert.equal(autostart.hexStrikePermissionAllowsAutostart("deny"), false)
    assert.equal(autostart.hexStrikePermissionAllowsAutostart(""), false)
    assert.equal(autostart.hexStrikePermissionAllowsAutostart(undefined), false)
  })
})

describe("select HexStrike via applyRuntimeProfile", () => {
  test("granted calls startHexStrike and reports ready message", async () => {
    apiStub.__resetApiStub({ permissionStatus: "allow" })
    const result = await applyMod.applyRuntimeProfile("hexstrike-suite")
    assert.equal(apiStub.__apiStubState().startCalls, 1)
    assert.equal(result.hexStrikeAutoStarted, true)
    assert.equal(apiStub.__apiStubState().selectedId, "hexstrike-suite")
    assert.equal(autostart.hexStrikeSelectMessage(result.hexStrikeAutoStarted), "HexStrike AI suite ready.")
  })

  test("ask does not call startHexStrike and keeps Daybreak defer message", async () => {
    apiStub.__resetApiStub({ permissionStatus: "ask" })
    const result = await applyMod.applyRuntimeProfile("hexstrike-suite")
    assert.equal(apiStub.__apiStubState().startCalls, 0)
    assert.equal(result.hexStrikeAutoStarted, false)
    assert.equal(apiStub.__apiStubState().selectedId, "hexstrike-suite")
    assert.equal(
      autostart.hexStrikeSelectMessage(result.hexStrikeAutoStarted),
      "HexStrike selected. Open Daybreak and press Start when you want the suite running.",
    )
  })
})

describe("restore HexStrike via applyRuntimeProfile", () => {
  test("granted calls startHexStrike on restore", async () => {
    apiStub.__resetApiStub({ permissionStatus: "allow" })
    // First select stores the suite; restore re-applies the saved id.
    await applyMod.applyRuntimeProfile("hexstrike-suite")
    apiStub.__apiStubState().startCalls = 0
    const restored = await applyMod.applyRuntimeProfile("hexstrike-suite")
    assert.equal(apiStub.__apiStubState().startCalls, 1)
    assert.equal(restored.hexStrikeAutoStarted, true)
    assert.equal(autostart.hexStrikeSelectMessage(restored.hexStrikeAutoStarted), "HexStrike AI suite ready.")
  })

  test("ask does not call startHexStrike on restore", async () => {
    apiStub.__resetApiStub({ permissionStatus: "ask" })
    await applyMod.applyRuntimeProfile("hexstrike-suite")
    apiStub.__apiStubState().startCalls = 0
    const restored = await applyMod.applyRuntimeProfile("hexstrike-suite")
    assert.equal(apiStub.__apiStubState().startCalls, 0)
    assert.equal(restored.hexStrikeAutoStarted, false)
    assert.equal(
      autostart.hexStrikeSelectMessage(restored.hexStrikeAutoStarted),
      "HexStrike selected. Open Daybreak and press Start when you want the suite running.",
    )
  })
})
