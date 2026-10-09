import assert from "node:assert/strict"
import { test } from "node:test"
import { buildLivingBird } from "./src/presence/renderers/shapes/livingBird.ts"

const head = [{ x: 0, y: 0.5, z: 0.3, size: 2.45, light: 1.2, gold: 0, flow: 0, color: [0.1, 0.4, 0.8, 1] }]

test("both birds have a closed chest and separately articulated wings below the intact head", () => {
  for (const persona of ["anzu", "nabu"]) {
    const body = buildLivingBird(head, persona)
    assert.equal(body[0].x, head[0].x)
    assert.equal(body[0].y, head[0].y)
    assert.equal(body[0].z, head[0].z)
    assert.deepEqual(body[0].color, head[0].color)
    assert.ok(body.some(p => p.flow === -1 && p.z > 0.2))
    assert.ok(body.some(p => p.flow === -1 && p.z < -0.2))
    assert.ok(body.some(p => p.flow === -2 && p.x < -1))
    assert.ok(body.some(p => p.flow === -3 && p.x > 1))
    assert.ok(body.some(p => p.y < -3), "torso continues beneath the viewport")
    assert.ok(body.every(p => [p.x, p.y, p.z, p.light, p.size, ...p.color].every(Number.isFinite)))
    assert.equal(head[0].light, 1.2, "cached head artwork stays unmodified")
    assert.ok(Math.abs(body[0].light / body.length - head[0].light / head.length) < 1e-8,
      "adding body samples preserves expected head light at the same draw budget")
  }
})

test("other personas keep their artwork unchanged", () => {
  assert.deepEqual(buildLivingBird(head, "eir"), head)
})
