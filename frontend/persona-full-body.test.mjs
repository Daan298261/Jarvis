import assert from "node:assert/strict"
import { test } from "node:test"
import { buildPersonaBody } from "./src/presence/renderers/shapes/personaBody.ts"
import { avatarMotionProfile } from "./src/presence/avatarMotion.ts"
import { isPersonaPortraitShape, personaSafeViewport, usesDaybreakAppearance } from "./src/presence/appearanceModes.ts"
import { MYTHIC_AVATAR_CHOICES, mythicAvatarForSelection } from "./src/presence/mythicPersonaVariant.ts"

const head = [{ x: 0, y: 0.5, z: 0.3, size: 2.4, light: 1.2, gold: 0, flow: 0, color: [0.1, 0.4, 0.8, 1] }]
const roster = ["anzu", "mestor", "nabu", "enki", "veles", "themis", "aegir", "bragi", "hermes", "heimdall", "eir", "maia", "vulcan", "umi"]

test("every persona has a complete finite body, intact authored head colors, and its own motion", () => {
  for (const id of roster) {
    const body = buildPersonaBody(head, id)
    assert.ok(body.points.length > 10000, id)
    assert.ok(body.points.some(p => p.y < -1.4), `${id}: feet or tail exist`)
    assert.deepEqual(body.points[0].color, head[0].color)
    assert.ok(body.points.every(p => [p.x, p.y, p.z, p.size, p.light, ...p.color].every(Number.isFinite)), id)
    assert.equal(avatarMotionProfile(`portrait_${id}_fullbody_b`), avatarMotionProfile(`portrait_${id}_b`))
  }
  assert.equal(head[0].y, 0.5, "never mutate cached original artwork")
})

test("standing stag has four separated hooves and a neck connecting to its own head", () => {
  const body = buildPersonaBody(head, "eir")
  assert.equal(body.anatomy, "stag")
  const feet = body.points.filter(p => p.y < -1.5)
  for (const x of [-1.05, -0.72, 0.31, 0.64]) assert.ok(feet.some(p => Math.abs(p.x - x) < 0.07))
  assert.ok(body.points.some(p => p.y > 0.7 && p.flow === -10))
})

test("safe framing excludes the composer and expanded appearance rail", () => {
  for (const [width, height] of [[2956, 1200], [1440, 900], [1024, 768], [768, 680]]) {
    const viewport = personaSafeViewport({ left: 0, top: 40, width, height },
      { left: 0, top: height - 170, width, height: 170 }, { left: 10, top: 60, width: 320, height: 600 })
    assert.ok(viewport.centerY + viewport.height / 2 < height - 210)
    assert.ok(viewport.centerX - viewport.width / 2 > 320)
  }
  assert.equal(isPersonaPortraitShape("portrait_humanoid"), false)
  assert.equal(isPersonaPortraitShape("portrait_humanoid_muscular"), false)
  assert.equal(isPersonaPortraitShape("portrait_eir_fullbody_b"), true)
})

test("explicit Galaxy or Humanoid selection cannot remain overridden by a Daybreak runtime", () => {
  assert.equal(usesDaybreakAppearance({ requestedPresence: "galaxy", avatarId: "hexstrike_suite" }, true), false)
  assert.equal(usesDaybreakAppearance({ requestedPresence: "humanoid", avatarId: "jarvis_base" }, true), false)
  assert.equal(usesDaybreakAppearance({ requestedPresence: "humanoid", avatarId: "hexstrike_suite" }, true), true)
})

test("legacy persona choices disappear and saved legacy choices map to full body", () => {
  assert.equal(MYTHIC_AVATAR_CHOICES.some(c => /legacy|classic/i.test(c.label)), false)
  assert.equal(mythicAvatarForSelection("mythic_legacy_d"), "mythic_living_b")
})
