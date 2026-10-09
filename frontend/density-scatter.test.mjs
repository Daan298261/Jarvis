import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"
await register("./presence-lifecycle-loader.mjs", import.meta.url)
const { resampleOrbs } = await import("./src/presence/renderers/shapes/catalog.ts")

test("lower density removes scattered dots across every row and column, never whole bars", () => {
  const grid = []
  for (let y = 0; y < 64; y++) for (let x = 0; x < 64; x++) grid.push({
    x: (x - 32) / 20, y: (y - 32) / 20, z: 0,
    gold: 0, flow: 0, light: 1, size: 1.7,
  })
  const full = resampleOrbs(grid, grid.length)
  assert.deepEqual(full, resampleOrbs(grid, grid.length), "thinning order must remain stable")
  const sparse = full.slice(0, Math.round(full.length * 0.35))
  for (const axis of ["x", "y"]) {
    const rows = Array(64).fill(0)
    for (const p of sparse) rows[Math.round(p[axis] * 20 + 32)]++
    assert.ok(Math.min(...rows) >= 8, `${axis} has missing rows: ${rows}`)
    assert.ok(Math.max(...rows) <= 40, `${axis} has dense bars: ${rows}`)
  }
  assert.equal(new Set(sparse).size, sparse.length)
  assert.ok(sparse.every(p => p.size === 1.7), "density must not enlarge remaining dots")
})

test("resampling below the artwork count also scatters removals over the complete silhouette", () => {
  const grid = Array.from({ length: 4096 }, (_, i) => ({
    x: i % 64, y: Math.floor(i / 64), z: 0, gold: 0, flow: 0, light: 1, size: 1,
  }))
  const sparse = resampleOrbs(grid, 1434)
  assert.equal(sparse.length, 1434)
  assert.equal(new Set(sparse).size, sparse.length)
  assert.equal(new Set(sparse.map(p => p.y)).size, 64)
  assert.equal(new Set(sparse.map(p => p.x)).size, 64)
})
