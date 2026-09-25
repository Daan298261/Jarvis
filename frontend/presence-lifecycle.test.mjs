import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"
import { readFile } from "node:fs/promises"

await register("./presence-lifecycle-loader.mjs", import.meta.url)

const lifecycle = await import("./src/presence/presenceLifecycle.ts")
const attention = await import("./src/presence/presenceAttention.ts")
const cloud = await import("./src/presence/renderers/morphableOrbCloud.ts")
const shapes = await import("./src/presence/renderers/shapes/catalog.ts")
const quality = await import("./src/presence/presenceQuality.ts")
const THREE = await import("three")

function meanAxis(attribute, axis) {
  let sum = 0
  for (let i = 0; i < attribute.count; i++) sum += attribute.getComponent(i, axis)
  return sum / attribute.count
}

function meanGold(attribute) {
  let sum = 0
  for (let i = 0; i < attribute.count; i++) sum += attribute.getX(i)
  return sum / attribute.count
}

function material() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uMorph: { value: 0 },
      uGalaxy: { value: 0 },
    },
    vertexShader: "void main(){}",
    fragmentShader: "void main(){}",
  })
}

test("idle is the free cloud and engage drives uMorph toward the winning figure", () => {
  const system = cloud.createMorphablePresenceSystem(0.02, material(), "humanoid_bust")
  const geo = system.figure.geometry
  const aPos = geo.getAttribute("aPos")
  const bPos = geo.getAttribute("bPos")
  const aGold = geo.getAttribute("aGold")
  const bGold = geo.getAttribute("bGold")
  const freeY = meanAxis(aPos, 1)
  const figureY = meanAxis(bPos, 1)

  assert.equal(system.morphValue(), 0)
  assert.equal(system.currentShapeId, "humanoid_bust")
  assert.ok(Math.abs(meanGold(aGold)) < 0.001, "free cloud keeps the amber core off")
  assert.ok(meanGold(bGold) > 0.02, "winning figure carries the lattice gold")
  assert.ok(Math.abs(freeY - figureY) > 0.25, `free ${freeY} should not be the bust ${figureY}`)

  system.setLifecycleTarget(1, { duration: 1.2 })
  system.tick(0.6)
  const mid = system.morphValue()
  assert.ok(mid > 0.45 && mid < 0.55, `expected ~0.5, got ${mid}`)
  system.tick(0.7)
  assert.equal(system.morphValue(), 1)
  assert.equal(system.currentShapeId, "humanoid_bust")

  system.setLifecycleTarget(0, { duration: 1.2 })
  system.tick(0.6)
  const returning = system.morphValue()
  assert.ok(returning > 0.45 && returning < 0.55, `expected ~0.5 on the way back, got ${returning}`)
  system.tick(0.7)
  assert.equal(system.morphValue(), 0)
  system.dispose()
})

test("reduced motion snaps uMorph and a non-bust winner is the engaged end", () => {
  const system = cloud.createMorphablePresenceSystem(0.02, material(), "humanoid_bust")
  system.morphTo("hex_aegis", { immediate: true })
  assert.equal(system.currentShapeId, "hex_aegis")
  assert.equal(system.morphValue(), 0)
  system.setLifecycleTarget(1, { duration: 0, immediate: true })
  assert.equal(system.morphValue(), 1)
  assert.equal(system.currentShapeId, "hex_aegis")
  system.setLifecycleTarget(0, { immediate: true })
  assert.equal(system.morphValue(), 0)
  system.dispose()
})

test("morph is not skipped when requested presence is not galaxy", () => {
  for (const mode of ["neural", "humanoid", "particle_bust", "galaxy"]) {
    assert.equal(lifecycle.presenceLifecycleEnabled(mode), true)
  }
  assert.equal(lifecycle.presenceLifecycleEnabled("none"), false)
  assert.equal(lifecycle.lifecycleMorphTarget("idle"), 0)
  assert.equal(lifecycle.lifecycleMorphTarget("waiting"), 0)
  assert.equal(lifecycle.lifecycleMorphTarget("offline"), 0)
  for (const phase of ["thinking", "listening", "speaking", "executing", "alert", "error", "approval"]) {
    assert.equal(lifecycle.lifecycleMorphTarget(phase), 1)
  }

  const mat = material()
  assert.equal(mat.uniforms.uGalaxy.value, 0)
  const system = cloud.createMorphablePresenceSystem(0.02, mat, "stormbird")
  system.setLifecycleTarget(lifecycle.lifecycleMorphTarget("thinking"), { duration: 1.2 })
  system.tick(1.2)
  assert.equal(system.morphValue(), 1)
  assert.equal(system.currentShapeId, "stormbird")
  assert.equal(mat.uniforms.uGalaxy.value, 0)
  assert.match(cloud.particleVertexShader, /freeWeight/)
  assert.match(cloud.particleVertexShader, /pointerFalloff \* loose \* uPointerStrength/)
  assert.equal(cloud.particleVertexShader.match(/uniform float uMorph;/g)?.length, 1)
  system.dispose()
})

test("camera-unavailable attract stays on the pointer and does not invent a face", () => {
  const denied = lifecycle.resolvePresenceAttract({
    attentionMode: "camera",
    reduced: false,
    pointerX: 0.4,
    pointerY: -0.2,
    cameraX: 0.9,
    cameraY: 0.8,
    cameraConfidence: 0.95,
    cameraAvailable: false,
  })
  assert.equal(denied.source, "pointer")
  assert.equal(denied.chase, true)
  assert.equal(denied.x, 0.4)
  assert.equal(denied.y, -0.2)

  const zero = lifecycle.resolvePresenceAttract({
    attentionMode: "camera",
    reduced: false,
    pointerX: -0.3,
    pointerY: 0.1,
    cameraX: 0.7,
    cameraY: -0.6,
    cameraConfidence: 0,
    cameraAvailable: true,
  })
  assert.equal(zero.source, "pointer")
  assert.equal(zero.x, -0.3)

  const face = lifecycle.resolvePresenceAttract({
    attentionMode: "camera",
    reduced: false,
    pointerX: 0.1,
    pointerY: 0.1,
    cameraX: -0.55,
    cameraY: 0.25,
    cameraConfidence: 0.2,
    cameraAvailable: true,
  })
  assert.equal(face.source, "camera")
  assert.equal(face.x, -0.55)
  assert.equal(face.chase, true)

  const pointerMode = lifecycle.resolvePresenceAttract({
    attentionMode: "pointer",
    reduced: false,
    pointerX: 0.2,
    pointerY: 0.3,
    cameraX: 1,
    cameraY: 1,
    cameraConfidence: 1,
    cameraAvailable: true,
  })
  assert.equal(pointerMode.source, "pointer")
  assert.equal(pointerMode.x, 0.2)

  const off = lifecycle.resolvePresenceAttract({
    attentionMode: "off",
    reduced: false,
    pointerX: 0.5,
    pointerY: 0.5,
    cameraX: 0,
    cameraY: 0,
    cameraConfidence: 1,
    cameraAvailable: true,
  })
  assert.equal(off.chase, false)
  assert.equal(off.source, "hold")
  assert.equal(off.x, 0)

  const reduced = lifecycle.resolvePresenceAttract({
    attentionMode: "pointer",
    reduced: true,
    pointerX: 0.5,
    pointerY: 0.5,
    cameraX: 0,
    cameraY: 0,
    cameraConfidence: 1,
    cameraAvailable: true,
  })
  assert.equal(reduced.chase, false)
  assert.equal(reduced.source, "hold")
})

test("shared dot appearance supports optional profiles and bounded shader controls", () => {
  const shape = shapes.resolvePresenceShape("humanoid_bust")
  assert.equal(shape.appearance, undefined, "legacy shapes use neutral defaults")
  assert.match(cloud.particleVertexShader, /size \* uPointScale \* uPixelScale/)
  assert.match(cloud.particleFragmentShader, /uDepthSoftness/)
})

test("shared motion cues breathe without attention and keep alerts reduced-motion safe", async () => {
  assert.match(cloud.particleVertexShader, /uBreath/)
  assert.match(cloud.particleVertexShader, /uListen/)
  assert.match(cloud.particleFragmentShader, /alertRing/)
  const stage = await readFile(new URL("./src/presence/renderers/MorphablePresenceStage.tsx", import.meta.url), "utf8")
  assert.match(stage, /phase !== "idle" \? 0 : Math\.sin/)
  assert.match(stage, /if \(reduced\) alertAge = 4/)
  assert.match(stage, /meterNow\.attached && meterNow\.kind === "tts" && phase === "speaking"/)
})

test("auto presence quality adapts with sustained thresholds and fit bounds keep safe margins", () => {
  const controller = new quality.AutoPresenceQuality()
  for (let t = 0; t <= 5000; t += 100) controller.sample(t, 33)
  assert.equal(controller.current, 0, "sustained slow frames step down one tier")
  for (let t = 5100; t <= 18000; t += 100) controller.sample(t, 16)
  assert.equal(controller.current, 1, "sustained fast frames recover after cooldown")

  const fit = quality.normalizedPresenceFitScale(
    new Float32Array([-2, -1, 0, 2, 1, 0]), 1, 32, 5.6,
  )
  assert.ok(fit > 0 && fit < 1, `wide silhouettes should be scaled into the stage, got ${fit}`)
})

test("presence quality changes figure, field, and stars in place without resetting morph", () => {
  const system = cloud.createMorphablePresenceSystem(0.95, material(), "humanoid_bust", 1.15)
  const initial = system.setQuality(0.95)
  assert.deepEqual(initial, { figure: 77900, field: 14250, galaxyStars: 22800 })
  system.setLifecycleTarget(1, { duration: 1 })
  system.tick(0.25)
  const morph = system.morphValue()
  const low = system.setQuality(0.6)
  assert.ok(morph > 0 && morph < 1)
  assert.deepEqual(low, { figure: 49200, field: 9000, galaxyStars: 14400 })
  assert.equal(system.morphValue(), morph)
  system.dispose()
})

test("catalog shapes resolve a safe frame in desktop, ultrawide, portrait, and short stages", () => {
  for (const shape of shapes.listPresenceShapes()) {
    const orbs = shape.buildFigure(0.08)
    const samples = shapes.resampleOrbs(orbs, Math.min(600, Math.max(1, orbs.length)))
    const positions = new Float32Array(samples.length * 3)
    samples.forEach((orb, i) => positions.set([orb.x, orb.y, orb.z], i * 3))
    for (const [aspect, fov, distance] of [[1.7, 32, 5.6], [3.2, 32, 5.6], [0.58, 37, 6.15], [1.2, 32, 5.6]]) {
      const yaw = shape.framing?.yaw ?? 0
      const margin = shape.framing?.fitMargin ?? 0.88
      const scale = quality.normalizedPresenceFitScale(positions, aspect, fov, distance, yaw, margin)
      assert.ok(Number.isFinite(scale) && scale >= 0.45 && scale <= 1.35, `${shape.id} should fit at aspect ${aspect}`)
      const c = Math.cos(yaw)
      const s = Math.sin(yaw)
      let extentX = 0
      let extentY = 0
      for (let i = 0; i < positions.length; i += 3) {
        extentX = Math.max(extentX, Math.abs(positions[i] * c + positions[i + 2] * s))
        extentY = Math.max(extentY, Math.abs(positions[i + 1]))
      }
      const visibleHeight = 2 * distance * Math.tan((fov * Math.PI) / 360)
      assert.ok(extentX * scale <= visibleHeight * aspect * (margin / 2) + 0.02, `${shape.id} should fit stage width at aspect ${aspect}`)
      assert.ok(extentY * scale <= visibleHeight * (margin / 2) + 0.02, `${shape.id} should fit stage height at aspect ${aspect}`)
    }
  }
})

test("attention controller fails closed to the pointer without a webcam", () => {
  const previousWindow = globalThis.window
  globalThis.window = {
    addEventListener() {},
    removeEventListener() {},
    setInterval() { return 1 },
    clearInterval() {},
    requestAnimationFrame() { return 1 },
    cancelAnimationFrame() {},
    innerWidth: 800,
    innerHeight: 600,
  }
  const calls = []
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia() {
        calls.push("getUserMedia")
        return Promise.reject(new Error("denied"))
      },
    },
  })
  try {
    const pointerController = attention.createPresenceAttentionController({
      getMode: () => "pointer",
      getReducedMotion: () => false,
    })
    const pointerSample = pointerController.sample()
    assert.equal(pointerSample.source, "pointer")
    assert.equal(calls.length, 0, "pointer mode must not open the camera")
    pointerController.dispose()

    const cameraController = attention.createPresenceAttentionController({
      getMode: () => "camera",
      getReducedMotion: () => false,
    })
    const failed = cameraController.sample()
    assert.equal(failed.source, "pointer")
    assert.notEqual(failed.source, "camera")
    cameraController.dispose()

    const offController = attention.createPresenceAttentionController({
      getMode: () => "off",
      getReducedMotion: () => false,
    })
    const held = offController.sample()
    assert.equal(held.confidence, 0)
    assert.equal(held.x, 0)
    offController.dispose()
  } finally {
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined })
  }
})
