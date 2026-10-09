import assert from "node:assert/strict"
import { test } from "node:test"
import { calibratedPortraitExposure, portraitSampleEnergy, HUMANOID_PORTRAIT_ENERGY } from "./src/presence/renderers/shapes/portraitLighting.ts"

const sample = (color, light = 1, size = 2.45) => ({ x: 0, y: 0, z: 0, gold: 0, flow: 0, light, size, color: [...color, 1] })

test("dark and saturated portraits reach the humanoid light target without changing hue or shading", () => {
  for (const color of [[0.1, 0.25, 0.5], [0.18, 0.03, 0.18], [0.32, 0.08, 0.015], [0.25, 0.3, 0.35]]) {
    const points = [sample(color), sample(color.map(c => c * 0.5), 0.7), sample(color, 0.18, 1.3)]
    const before = structuredClone(points)
    const exposure = calibratedPortraitExposure(points)
    assert.ok(Math.abs(portraitSampleEnergy(points) * exposure - HUMANOID_PORTRAIT_ENERGY) < 1e-8)
    assert.deepEqual(points, before, "calibration must not flatten or recolour the artwork")
  }
})

test("rear dimming and smaller A sprites are compensated in exposure, not particle size", () => {
  const front = [sample([0.2, 0.2, 0.2])]
  const withBack = [...front, sample([0.2, 0.2, 0.2], 0.18, 1.3)]
  assert.ok(calibratedPortraitExposure(withBack) > calibratedPortraitExposure(front))
  assert.ok(calibratedPortraitExposure([sample([0.2, 0.2, 0.2], 1, 1.7)]) > calibratedPortraitExposure(front))
  assert.equal(calibratedPortraitExposure([]), 1)
  assert.equal(calibratedPortraitExposure([sample([0, 0, 0])]), 1)
  assert.equal(calibratedPortraitExposure([sample([1, 1, 1], 2)]), 1, "already bright avatars must not be dimmed")
})
