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
const THREE = await import("three")

function material() {
  return new THREE.ShaderMaterial({
    uniforms: { uMorph: { value: 0 }, uGalaxy: { value: 0 } },
    vertexShader: "void main(){}",
    fragmentShader: "void main(){}",
  })
}

function positionsOf(orbs) {
  const positions = new Float32Array(orbs.length * 3)
  orbs.forEach((orb, i) => positions.set([orb.x, orb.y, orb.z], i * 3))
  return positions
}

function meanGold(attribute) {
  let sum = 0
  for (let i = 0; i < attribute.count; i++) sum += attribute.getX(i)
  return sum / attribute.count
}

function figureOrbs(id, density = 0.1) {
  return shapes.resolvePresenceShape(id).buildFigure(density)
}

test("lifecycle blend maps rest tightness to the rest pose, not a 0.82 smear toward engaged", () => {
  const rest = lifecycle.REST_TIGHTNESS
  assert.equal(lifecycle.lifecycleMorphBlend(rest), 0)
  assert.equal(lifecycle.lifecycleMorphBlend(0), 0)
  assert.equal(lifecycle.lifecycleMorphBlend(0.5), 0)
  assert.equal(lifecycle.lifecycleMorphBlend(1), 1)
  const midMorph = rest + (1 - rest) * 0.5
  assert.ok(Math.abs(lifecycle.lifecycleMorphBlend(midMorph) - 0.5) < 0.02)
  assert.ok(lifecycle.restAttractGain(rest) < 0.4)
  assert.equal(lifecycle.restAttractGain(1), 1)
})

test("humanoid rest pose is a loosened bust, not a spherical free cloud", () => {
  const figure = figureOrbs("humanoid_bust", 0.12)
  const rest = cloud.buildRestSilhouette(figure)
  const anonymous = cloud.buildFreeFloatCloud(figure.length)
  const report = silhouette.evaluateRestIdentity({
    figure,
    rest,
    anonymous,
    morph: lifecycle.REST_TIGHTNESS,
    bloomStrength: 0.38,
    pointScale: 0.95,
    glow: 0.85,
  })
  assert.equal(report.readable, true, report.failReasons.join("; "))
  assert.ok(report.restToFigureDisplacement < 0.35, `rest displacement ${report.restToFigureDisplacement}`)
  assert.ok(report.anonymousDisplacement > report.restToFigureDisplacement * 3)
  assert.ok(report.restAnatomy.goldMean < report.figureAnatomy.goldMean)
  assert.ok(report.restAnatomy.goldMean > 0)
  assert.ok(report.restAnatomy.radialRms >= report.figureAnatomy.radialRms * 0.92)
})

test("idle mix of a spherical free cloud fails rest identity (seat 2 residual)", () => {
  const figure = figureOrbs("humanoid_bust", 0.1)
  const blob = cloud.buildFreeFloatCloud(figure.length)
  const report = silhouette.evaluateRestIdentity({
    figure,
    rest: blob,
    anonymous: blob,
    morph: lifecycle.REST_TIGHTNESS,
    bloomStrength: 0.38,
    pointScale: 0.95,
    glow: 0.85,
  })
  assert.equal(report.readable, false)
  assert.ok(report.failReasons.length > 0)
})

test("rest identity holds for catalog shapes at REST_TIGHTNESS", () => {
  for (const shape of shapes.listPresenceShapes()) {
    const figure = shape.buildFigure(0.08)
    const rest = cloud.buildRestSilhouette(figure)
    const anonymous = cloud.buildFreeFloatCloud(Math.min(figure.length, 4000))
    const sampleFigure = figure.slice(0, anonymous.length)
    const sampleRest = rest.slice(0, anonymous.length)
    const report = silhouette.evaluateRestIdentity({
      figure: sampleFigure,
      rest: sampleRest,
      anonymous,
      morph: lifecycle.REST_TIGHTNESS,
      bloomStrength: 0.38,
      pointScale: 0.9,
      glow: 0.85,
    })
    assert.equal(report.readable, true, `${shape.id}: ${report.failReasons.join("; ")}`)
    assert.equal(silhouette.restSilhouetteOrAnonymous(lifecycle.REST_TIGHTNESS), "silhouette")
  }
})

test("union rest+engaged fit keeps crown and chin on camera look-at", () => {
  const shape = shapes.resolvePresenceShape("humanoid_bust")
  const figure = shape.buildFigure(0.08)
  const rest = cloud.buildRestSilhouette(figure)
  const yaw = shape.framing?.yaw ?? quality.PRESENCE_DEFAULT_FRAMING_YAW
  const margin = shape.framing?.fitMargin ?? 0.88
  const restPos = positionsOf(rest)
  const figurePos = positionsOf(figure)
  const union = quality.unionPresencePositions(restPos, figurePos)
  for (const [aspect, fov, distance] of [[1.7, 32, 5.6], [3.2, 32, 5.6], [0.58, 37, 6.15], [1.2, 32, 5.6]]) {
    const fit = quality.normalizedPresenceFitScale(
      union, aspect, fov, distance, yaw, margin, shape.framing?.landmarks,
    )
    assert.ok(fit.scale >= 0.45 && fit.scale <= 1.35, `scale ${fit.scale} at aspect ${aspect}`)
    const restFrame = quality.identityOnLookAtAfterFit({
      positions: restPos, fit, fovDegrees: fov, cameraDistance: distance, yaw, aspect,
    })
    const figureFrame = quality.identityOnLookAtAfterFit({
      positions: figurePos, fit, fovDegrees: fov, cameraDistance: distance, yaw, aspect,
    })
    assert.equal(restFrame.onFrame, true, `rest crop at aspect ${aspect} crown=${restFrame.crownY} chin=${restFrame.chinY}`)
    assert.equal(figureFrame.onFrame, true, `engaged crop at aspect ${aspect}`)
    assert.ok(restFrame.crownY > restFrame.chinY)
  }
})

test("morph system rest slot is the humanoid pose and engage still tightens", () => {
  const system = cloud.createMorphablePresenceSystem(0.02, material(), "humanoid_bust")
  const geo = system.figure.geometry
  const aPos = geo.getAttribute("aPos")
  const bPos = geo.getAttribute("bPos")
  const aGold = geo.getAttribute("aGold")
  const bGold = geo.getAttribute("bGold")
  const rest = lifecycle.REST_TIGHTNESS
  assert.equal(system.morphValue(), rest)
  assert.equal(lifecycle.lifecycleMorphBlend(system.morphValue()), 0)

  let restToFig = 0
  let restY = 0
  let figY = 0
  const n = Math.min(aPos.count, 400)
  for (let i = 0; i < n; i++) {
    const i3 = i * 3
    restToFig += Math.hypot(
      aPos.array[i3] - bPos.array[i3],
      aPos.array[i3 + 1] - bPos.array[i3 + 1],
      aPos.array[i3 + 2] - bPos.array[i3 + 2],
    )
    restY += aPos.array[i3 + 1]
    figY += bPos.array[i3 + 1]
  }
  assert.ok(restToFig / n < 0.45, `rest slot must stay on the bust, mean ${restToFig / n}`)
  assert.ok(Math.abs(restY / n - figY / n) < 0.2, "rest centroid Y stays on the figure")
  assert.ok(meanGold(aGold) > 0 && meanGold(aGold) < meanGold(bGold))

  system.setLifecycleTarget(1, { duration: 1.2 })
  system.tick(1.2)
  assert.equal(system.morphValue(), 1)
  assert.equal(lifecycle.lifecycleMorphBlend(system.morphValue()), 1)
  system.setLifecycleTarget(rest, { duration: 1.2 })
  system.tick(1.2)
  assert.equal(system.morphValue(), rest)
  assert.notEqual(system.morphValue(), 0)
  assert.equal(lifecycle.lifecycleMorphBlend(system.morphValue()), 0)
  system.dispose()
})

test("attract at rest does not drop tightness or remap to identity-hide", () => {
  const attract = lifecycle.resolvePresenceAttract({
    attentionMode: "pointer",
    reduced: false,
    pointerX: 0.9,
    pointerY: -0.4,
    cameraX: 0,
    cameraY: 0,
    cameraConfidence: 0,
    cameraAvailable: false,
  })
  assert.equal(attract.chase, true)
  assert.equal(attract.source, "pointer")
  assert.equal(lifecycle.lifecycleMorphTarget("idle"), lifecycle.REST_TIGHTNESS)
  assert.ok(lifecycle.restAttractGain(lifecycle.REST_TIGHTNESS) < 0.4)
  const hold = lifecycle.resolvePresenceAttract({
    attentionMode: "off",
    reduced: false,
    pointerX: 1,
    pointerY: 1,
    cameraX: 0,
    cameraY: 0,
    cameraConfidence: 1,
    cameraAvailable: true,
  })
  assert.equal(hold.chase, false)
  assert.equal(hold.source, "hold")
})

test("stage wires rest-identity framing and capped rest attract", async () => {
  const stage = await readFile(new URL("./src/presence/renderers/MorphablePresenceStage.tsx", import.meta.url), "utf8")
  assert.match(stage, /unionPresencePositions/)
  assert.match(stage, /restAttractGain/)
  assert.match(stage, /lifecycleMorphBlend/)
  assert.match(stage, /dataset\.restIdentity/)
  assert.match(stage, /uRestTightness/)
  assert.doesNotMatch(stage, /free > 0\.15 \? 1 : 0\.42/)
  const shader = cloud.particleVertexShader
  assert.match(shader, /uRestTightness/)
  assert.match(shader, /restHalo/)
  assert.doesNotMatch(shader, /float freeWeight = 1\.0 - m;/)
})
