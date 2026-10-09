import assert from "node:assert/strict"
import { test } from "node:test"
import { buildPortraitVolume } from "./src/presence/renderers/shapes/portraitVolume.ts"

function artwork(width = 24, height = 24) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let y = 3; y < height - 3; y++) for (let x = 2; x < width - 2; x++) {
    // A central slit must remain a gap, not become a generic mask.
    if (x >= 11 && x <= 12) continue
    pixels.set([180, 120, 60, 255], (y * width + x) * 4)
  }
  return { pixels, width, height }
}

test("volumetric artwork has front and rear depth while preserving silhouette gaps and colour", () => {
  const { pixels, width, height } = artwork()
  const points = buildPortraitVolume(pixels, width, height)
  assert.ok(points.some(p => p.z > 0.25))
  assert.ok(points.some(p => p.z < -0.25))
  for (const p of points) {
    assert.ok([p.x, p.y, p.z, p.light, p.size].every(Number.isFinite))
    assert.equal(p.flow, 0, "solid artwork must never dissolve or orbit as a halo")
    const x = Math.round((p.x / 3.1 + 0.5) * (width - 1))
    assert.ok(x < 11 || x > 12)
    assert.ok(p.color[0] > p.color[1] && p.color[1] > p.color[2])
  }
  assert.deepEqual(points, buildPortraitVolume(pixels, width, height))
})

test("transparent and black background never become particle shells", () => {
  assert.deepEqual(buildPortraitVolume(new Uint8ClampedArray(16 * 16 * 4), 16, 16), [])
})
