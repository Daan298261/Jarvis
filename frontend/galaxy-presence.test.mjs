import assert from "node:assert/strict"
import { test } from "node:test"

const galaxy = await import("./src/presence/galaxyPresence.ts")

test("default requested presence stays neural and galaxy round-trips", () => {
  assert.equal(galaxy.parseRequestedPresence(undefined), "neural")
  assert.equal(galaxy.parseRequestedPresence(null), "neural")
  assert.equal(galaxy.parseRequestedPresence("galaxy"), "galaxy")
  assert.equal(galaxy.parseRequestedPresence("avatar"), "neural")
  assert.notEqual(galaxy.parseRequestedPresence("avatar"), "galaxy")
})

test("existing presence values still parse", () => {
  for (const value of ["none", "neural", "humanoid", "particle_bust"]) {
    assert.equal(galaxy.parseRequestedPresence(value), value)
  }
})

test("galaxy stars are additional and do not lower figure or field budgets", () => {
  const budgets = galaxy.presenceBudgets(1)
  assert.equal(budgets.figure, 82000)
  assert.equal(budgets.field, 15000)
  assert.equal(budgets.galaxyStars, 24000)
  assert.equal(galaxy.FIGURE_BUDGET_SCALE, 82000)
  assert.equal(galaxy.FIELD_BUDGET_SCALE, 15000)
  const dense = galaxy.presenceBudgets(1.15)
  assert.equal(dense.figure, Math.round(82000 * 1.15))
  assert.equal(dense.field, Math.round(15000 * 1.15))
  assert.equal(dense.galaxyStars, Math.round(24000 * 1.15))
  assert.ok(dense.galaxyStars > 0)
  assert.ok(dense.figure >= budgets.figure * 1.1)
})

test("galaxy starfield cap is 2400-4000 and the old formula stays otherwise", () => {
  assert.equal(galaxy.hudStarfieldCount(1920, 1080, true, true), 90)
  assert.equal(galaxy.hudStarfieldCount(1920, 1080, true, false), 90)
  const desktop = galaxy.hudStarfieldCount(1920, 1080, false, true)
  assert.ok(desktop >= 2400 && desktop <= 4000)
  const wide = galaxy.hudStarfieldCount(3440, 1440, false, true)
  assert.ok(wide >= 2400 && wide <= 4000)
  assert.equal(wide, 4000)
  const classic = galaxy.hudStarfieldCount(1920, 1080, false, false)
  assert.equal(classic, Math.round(Math.min(420, Math.max(160, (1920 * 1080) / 9000))))
  assert.ok(classic <= 420)
})

test("galaxy status pill follows phase and stays static without an analyser", () => {
  assert.equal(galaxy.galaxyStatusText("idle"), "STATUS: IDLE | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("waiting"), "STATUS: IDLE | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("thinking"), "STATUS: THINKING | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("listening"), "STATUS: LISTENING | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("speaking"), "STATUS: SPEAKING | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("executing"), "STATUS: WORKING | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("approval"), "STATUS: WAITING | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("alert"), "STATUS: ATTENTION | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("error"), "STATUS: ATTENTION | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("offline"), "STATUS: OFFLINE | ····· | SYN-01")
  assert.equal(
    galaxy.galaxyStatusText("speaking", { analyser: false, level: 0.9 }),
    "STATUS: SPEAKING | ····· | SYN-01",
  )
  const live = galaxy.galaxyStatusText("listening", { analyser: true, level: 1 })
  assert.match(live, /^STATUS: LISTENING \| .+ \| SYN-01$/)
  assert.notEqual(live, "STATUS: LISTENING | ····· | SYN-01")
  assert.equal(galaxy.galaxyStatusText("idle", { bust: false }), "STATUS: IDLE")
})

test("galaxy keeps hex, custom, and non-default persona figures", () => {
  assert.equal(galaxy.galaxyFigureShapeId({
    requestedPresence: "humanoid",
    resolvedShapeId: "stormbird",
    suiteActive: false,
    customPresetActive: false,
    personaId: "anzu",
  }), "stormbird")
  assert.equal(galaxy.galaxyFigureShapeId({
    requestedPresence: "galaxy",
    resolvedShapeId: "stormbird",
    suiteActive: false,
    customPresetActive: false,
    personaId: "anzu",
  }), "stormbird")
  assert.equal(galaxy.galaxyFigureShapeId({
    requestedPresence: "galaxy",
    resolvedShapeId: "waveform_letters",
    suiteActive: false,
    customPresetActive: false,
    personaId: "bragi",
  }), "waveform_letters")
  assert.equal(galaxy.galaxyFigureShapeId({
    requestedPresence: "galaxy",
    resolvedShapeId: "hex_aegis",
    suiteActive: true,
    customPresetActive: false,
    personaId: "anzu",
  }), "hex_aegis")
  assert.equal(galaxy.galaxyFigureShapeId({
    requestedPresence: "galaxy",
    resolvedShapeId: "custom_ui_nebula",
    suiteActive: false,
    customPresetActive: true,
    personaId: "anzu",
  }), "custom_ui_nebula")
})

test("hexstrike override means galaxy is not effective and does not require a saved rewrite", () => {
  assert.equal(galaxy.isGalaxyPresenceEffective({
    requestedPresence: "galaxy",
    suiteOverride: true,
    webglAvailable: true,
  }), false)
  assert.equal(galaxy.isGalaxyPresenceEffective({
    requestedPresence: "galaxy",
    suiteOverride: false,
    webglAvailable: false,
  }), false)
  assert.equal(galaxy.isGalaxyPresenceEffective({
    requestedPresence: "neural",
    suiteOverride: false,
    webglAvailable: true,
  }), false)
  assert.equal(galaxy.isGalaxyPresenceEffective({
    requestedPresence: "galaxy",
    suiteOverride: false,
    webglAvailable: true,
  }), true)
})
