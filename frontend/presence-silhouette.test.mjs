import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"
import { readFile } from "node:fs/promises"

await register("./presence-lifecycle-loader.mjs", import.meta.url)

const lifecycle = await import("./src/presence/presenceLifecycle.ts")
const quality = await import("./src/presence/presenceQuality.ts")
const silhouette = await import("./src/presence/presenceSilhouette.ts")
const shapes = await import("./src/presence/renderers/shapes/catalog.ts")
const cloud = await import("./src/presence/renderers/morphableOrbCloud.ts")
const personas = await import("./src/persona/namedPersonas.ts")
const THREE = await import("three")

function material() {
  return new THREE.ShaderMaterial({
    uniforms: { uMorph: { value: 0 }, uGalaxy: { value: 0 } },
    vertexShader: "void main(){}",
    fragmentShader: "void main(){}",
  })
}

function figureOrbs(id, density = 0.12) {
  return shapes.resolvePresenceShape(id).buildFigure(density)
}

test("RFC-0195 rest tightness is locked in band and idle is never 0", () => {
  const rest = lifecycle.REST_TIGHTNESS
  assert.ok(rest >= 0.72 && rest <= 0.92)
  assert.equal(rest, 0.82)
  assert.equal(lifecycle.ENGAGED_TIGHTNESS, 1)
  for (const phase of ["idle", "waiting", "offline"]) {
    assert.equal(lifecycle.lifecycleMorphTarget(phase), rest)
    assert.notEqual(lifecycle.lifecycleMorphTarget(phase), 0)
  }
  assert.equal(lifecycle.clampLifecycleMorph(0), rest)
  assert.equal(lifecycle.clampLifecycleMorph(-1), rest)
  assert.equal(lifecycle.clampLifecycleMorph(1), 1)
  assert.equal(silhouette.restSilhouetteOrAnonymous(0), "anonymous")
  assert.equal(silhouette.restSilhouetteOrAnonymous(rest), "silhouette")
})

test("supersession: presence tests do not require idle morph 0", async () => {
  const lifecycleTest = await readFile(new URL("./presence-lifecycle.test.mjs", import.meta.url), "utf8")
  const self = await readFile(new URL(import.meta.url), "utf8")
    for (const src of [lifecycleTest, self]) {
      assert.doesNotMatch(src, /assert\.equal\(\s*lifecycle\.lifecycleMorphTarget\(["']idle["']\)\s*,\s*0\s*\)/)
      assert.doesNotMatch(src, /lifecycleMorphTarget\(["']idle["']\)\s*===\s*0/)
      assert.doesNotMatch(src, /assert\.equal\(\s*lifecycle\.lifecycleMorphTarget\(["']waiting["']\)\s*,\s*0\s*\)/)
      assert.doesNotMatch(src, /assert\.equal\(\s*lifecycle\.lifecycleMorphTarget\(["']offline["']\)\s*,\s*0\s*\)/)
    }
  const moduleSrc = await readFile(new URL("./src/presence/presenceLifecycle.ts", import.meta.url), "utf8")
  assert.match(moduleSrc, /REST_TIGHTNESS = 0\.82/)
  assert.match(moduleSrc, /must not target `uMorph` 0/)
})

test("catalog shapes expose crown/chin/motif landmarks for AABB look-at", () => {
  for (const shape of shapes.listPresenceShapes()) {
    const orbs = shape.buildFigure(0.08)
    const positions = new Float32Array(orbs.length * 3)
    orbs.forEach((orb, i) => positions.set([orb.x, orb.y, orb.z], i * 3))
    const yaw = shape.framing?.yaw ?? quality.PRESENCE_DEFAULT_FRAMING_YAW
    const marks = quality.resolveShapeLandmarks(shape.framing?.landmarks, positions, yaw)
    assert.ok(Number.isFinite(marks.crown), `${shape.id} crown`)
    assert.ok(Number.isFinite(marks.chin), `${shape.id} chin`)
    assert.ok(marks.crown > marks.chin, `${shape.id} crown above chin`)
    assert.ok(marks.motifBounds.maxX >= marks.motifBounds.minX, `${shape.id} motif X`)
    assert.ok(marks.motifBounds.maxY >= marks.motifBounds.minY, `${shape.id} motif Y`)
    const look = quality.presenceLookAtFromFit({ centerX: 0.4, centerY: 0.2, centerZ: -0.1 })
    assert.deepEqual(look, { x: 0, y: 0, z: 0 })
  }
  const bust = shapes.resolvePresenceShape("humanoid_bust")
  assert.ok(bust.framing?.landmarks?.crown)
  const mestor = shapes.resolvePresenceShape("command_facet")
  assert.ok(mestor.framing?.landmarks?.motifBounds)
  assert.ok(mestor.appearance?.bloomStrength)
})

test("command_facet profile keeps hex-ring gold and does not drop motif", () => {
  const shape = shapes.resolvePresenceShape("command_facet")
  const orbs = shape.buildFigure(0.25)
  const gold = orbs.filter((orb) => orb.gold >= 0.5)
  assert.ok(gold.length > 40, "hex rings must survive as gold motif orbs")
  const appearance = quality.resolveDotAppearance(shape.appearance, { glow: 1.8, pointScale: 1.5 })
  assert.ok(appearance.pointScale <= quality.PRESENCE_POINT_SCALE_MAX)
  assert.ok(appearance.glow <= quality.PRESENCE_GLOW_MAX)
  assert.ok(appearance.bloomStrength <= quality.PRESENCE_BLOOM_STRENGTH_MAX)
  assert.ok(appearance.depthSoftness <= quality.PRESENCE_DEPTH_SOFTNESS_MAX)
})

test("Mestor-like overexposure fails even at 165 FPS / 94k particles", () => {
  const figure = figureOrbs("command_facet", 0.2)
  const washed = silhouette.evaluateSilhouetteQuality({
    figure,
    morph: 1,
    bloomStrength: 1.45,
    pointScale: 1.55,
    glow: 1.9,
    depthSoftness: 1,
    fps: 165,
    particleCount: 94000,
  })
  assert.equal(washed.readable, false)
  assert.ok(
    washed.failReasons.some((reason) => /overexposure|edge contrast|motif|slab/.test(reason)),
    washed.failReasons.join("; "),
  )
  assert.ok(
    washed.failReasons.some((reason) => /FPS|particle/.test(reason)),
    "high FPS must not rescue a slab",
  )
})

test("capped bloom/profile keeps a readable command_facet rest silhouette", () => {
  const shape = shapes.resolvePresenceShape("command_facet")
  const figure = shape.buildFigure(0.2)
  const appearance = quality.resolveDotAppearance(shape.appearance)
  const bloom = quality.resolvePresenceBloom({
    appearance,
    performancePreset: "balanced",
    autoTier: 1,
    rest: true,
  })
  const report = silhouette.evaluateSilhouetteQuality({
    figure,
    morph: lifecycle.REST_TIGHTNESS,
    bloomStrength: bloom.strength,
    pointScale: appearance.pointScale,
    glow: appearance.glow,
    depthSoftness: appearance.depthSoftness,
  })
  assert.equal(report.readable, true, report.failReasons.join("; "))
  assert.ok(report.restTightness >= 0.72)
})

test("lowest auto tier bypasses bloom without flattening the persona", () => {
  const appearance = quality.resolveDotAppearance({ glow: 1, bloomStrength: 0.5, pointScale: 1 })
  const low = quality.resolvePresenceBloom({
    appearance,
    performancePreset: "auto",
    autoTier: 0,
    rest: false,
  })
  assert.equal(low.enabled, false)
  assert.equal(low.strength, 0)
  const system = cloud.createMorphablePresenceSystem(0.95, material(), "command_facet", 1.15)
  const before = system.currentShapeId
  const morph = system.morphValue()
  const counts = system.setQuality(0.6)
  assert.equal(system.currentShapeId, before)
  assert.equal(system.morphValue(), morph)
  assert.ok(counts.figure > 0)
  const figure = figureOrbs("command_facet", 0.15)
  const report = silhouette.evaluateSilhouetteQuality({
    figure,
    morph: lifecycle.REST_TIGHTNESS,
    bloomStrength: 0,
    pointScale: appearance.pointScale,
    glow: appearance.glow,
  })
  assert.equal(report.readable, true, report.failReasons.join("; "))
  system.dispose()
})

test("near-white Mestor accent is pulled back so rings keep edge contrast", () => {
  const safe = quality.motifSafeAccentHex("#F8FAFC", "#1E3A8A")
  assert.notEqual(safe.toLowerCase(), "#f8fafc")
  const raw = quality.motifSafeAccentHex("#D4A017")
  assert.match(raw, /#d4a017/i)
})

test("roster rest stills stay on the winning figure, not an anonymous cloud", () => {
  const rest = lifecycle.REST_TIGHTNESS
  for (const id of personas.ROSTER_IDS) {
    const shapeId = personas.PERSONA_VISUALS[id].shapeId
    const figure = figureOrbs(shapeId, 0.1)
    const report = silhouette.evaluateSilhouetteQuality({
      figure,
      morph: rest,
      bloomStrength: 0.38,
      pointScale: 0.95,
      glow: 0.85,
    })
    assert.equal(
      silhouette.restSilhouetteOrAnonymous(rest),
      "silhouette",
      `${id} rest must not be anonymous`,
    )
    assert.ok(report.silhouetteOccupancy > 0.02, `${id} occupancy ${report.silhouetteOccupancy}`)
    assert.notEqual(shapeId, "", `${id} has a shape`)
  }
})
