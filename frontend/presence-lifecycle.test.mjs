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
const personas = await import("./src/persona/namedPersonas.ts")
const THREE = await import("three")
const portraits = await import("./src/presence/renderers/shapes/portraitCloud.ts")
const variants = await import("./src/presence/mythicPersonaVariant.ts")

test("portrait particles preserve colour and aspect, discard black, and cache decoding", async () => {
  const previousImage = globalThis.Image
  const previousDocument = globalThis.document
  let decodes = 0
  globalThis.Image = class {
    width = 100
    height = 200
    async decode() { decodes++ }
  }
  globalThis.document = { createElement: () => ({ getContext: () => ({
    drawImage() {},
    getImageData(_x, _y, w, h) {
      const data = new Uint8ClampedArray(w * h * 4)
      data.set([0, 0, 0, 255], 0)
      data.set([255, 128, 0, 255], 4)
      return { data }
    },
  }) }) }
  try {
    const first = portraits.preparePortraitCloud("test-avatar", "sample_test")
    assert.equal(first, portraits.preparePortraitCloud("test-avatar", "sample_test"))
    const id = await first
    const points = shapes.resolvePresenceShape(id).buildFigure(1)
    assert.equal(decodes, 1)
    assert.equal(points.length, 1)
    assert.equal(points[0].color[0], 1)
    assert.equal(points[0].color[3], 1)
    assert.ok(points[0].color[1] > 0.21 && points[0].color[1] < 0.22)
    assert.equal(points[0].y, 3.1)
  } finally {
    globalThis.Image = previousImage
    globalThis.document = previousDocument
    shapes.unregisterPresenceShape("portrait_sample_test")
  }
})

test("avatar decoding failures are retryable", async () => {
  const previousImage = globalThis.Image
  let decodes = 0
  globalThis.Image = class {
    set src(_value) { queueMicrotask(() => this.onerror?.()) }
    async decode() { decodes++; throw new Error("unavailable") }
  }
  try {
    await assert.rejects(portraits.preparePortraitCloud("missing-avatar", "retry_test"), /unavailable/)
    await assert.rejects(portraits.preparePortraitCloud("missing-avatar", "retry_test"), /unavailable/)
    assert.equal(decodes, 2)
  } finally { globalThis.Image = previousImage }
})

test("portrait loading has an onload fallback for Windows embedded browsers", async () => {
  const source = await readFile(new URL("./src/presence/renderers/shapes/portraitCloud.ts", import.meta.url), "utf8")
  assert.match(source, /image\.onload = ready/)
  assert.match(source, /image\.decode\?\.\(\)\.then\(ready\)/)
  assert.match(source, /Some WebView builds reject decode/)
})

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

test("idle keeps rest tightness and morphs into the selected figure when engaged", () => {
  const system = cloud.createMorphablePresenceSystem(0.02, material(), "humanoid_bust")
  const geo = system.figure.geometry
  const aPos = geo.getAttribute("aPos")
  const bPos = geo.getAttribute("bPos")
  const aGold = geo.getAttribute("aGold")
  const bGold = geo.getAttribute("bGold")
  const restY = meanAxis(aPos, 1)
  const figureY = meanAxis(bPos, 1)
  const rest = lifecycle.REST_TIGHTNESS
  const engaged = lifecycle.ENGAGED_TIGHTNESS

  assert.equal(system.morphValue(), rest)
  assert.ok(rest >= lifecycle.REST_TIGHTNESS_MIN && rest <= lifecycle.REST_TIGHTNESS_MAX)
  assert.equal(system.currentShapeId, "humanoid_bust")
  assert.equal(lifecycle.lifecycleMorphBlend(rest), 0)
  assert.equal(lifecycle.lifecycleMorphBlend(engaged), 1)
  assert.ok(meanGold(aGold) > 0.01, "rest pose keeps a dim amber core")
  assert.ok(meanGold(bGold) > meanGold(aGold), "engage brightens gold vs rest")
  assert.ok(Math.abs(restY - figureY) < 0.2, `rest ${restY} must stay on the bust ${figureY}`)
  assert.equal(lifecycle.lifecycleMorphTarget("idle"), rest)
  assert.notEqual(lifecycle.lifecycleMorphTarget("idle"), 0)

  system.setLifecycleTarget(engaged, { duration: 1.2 })
  system.tick(0.6)
  const mid = system.morphValue()
  const expectedMid = rest + (engaged - rest) * 0.5
  assert.ok(Math.abs(mid - expectedMid) < 0.02, `expected ~${expectedMid}, got ${mid}`)
  system.tick(0.7)
  assert.equal(system.morphValue(), engaged)
  assert.equal(system.currentShapeId, "humanoid_bust")

  system.setLifecycleTarget(rest, { duration: 1.2 })
  system.tick(0.6)
  const returning = system.morphValue()
  assert.ok(Math.abs(returning - expectedMid) < 0.02, `expected ~${expectedMid} on the way back, got ${returning}`)
  system.tick(0.7)
  assert.equal(system.morphValue(), rest)
  assert.notEqual(system.morphValue(), 0)
  system.dispose()
})

test("portrait-backed avatars retain authored colour in the idle silhouette", () => {
  const color = [0.1, 0.7, 1, 1]
  const [rest] = cloud.buildRestSilhouette([{
    x: 1, y: 1, z: 0, size: 2, light: 1, gold: 0, flow: 0, color,
  }])
  assert.deepEqual(rest.color, color)
})

test("reduced motion snaps uMorph to a static readable rest pose", () => {
  const system = cloud.createMorphablePresenceSystem(0.02, material(), "humanoid_bust")
  system.morphTo("hex_aegis", { immediate: true })
  assert.equal(system.currentShapeId, "hex_aegis")
  assert.equal(system.morphValue(), lifecycle.REST_TIGHTNESS)
  system.setLifecycleTarget(lifecycle.ENGAGED_TIGHTNESS, { duration: 0, immediate: true })
  assert.equal(system.morphValue(), lifecycle.ENGAGED_TIGHTNESS)
  assert.equal(system.currentShapeId, "hex_aegis")
  system.setLifecycleTarget(lifecycle.REST_TIGHTNESS, { immediate: true })
  assert.equal(system.morphValue(), lifecycle.REST_TIGHTNESS)
  assert.notEqual(system.morphValue(), 0)
  const attract = lifecycle.resolvePresenceAttract({
    attentionMode: "pointer",
    reduced: true,
    pointerX: 0.8,
    pointerY: 0.8,
    cameraX: 0,
    cameraY: 0,
    cameraConfidence: 1,
    cameraAvailable: true,
  })
  assert.equal(attract.chase, false)
  assert.equal(attract.source, "hold")
  system.dispose()
})

test("lifecycle rest phases keep identity tightness and engaged phases go to 1", () => {
  for (const mode of ["neural", "humanoid", "particle_bust", "galaxy"]) {
    assert.equal(lifecycle.presenceLifecycleEnabled(mode), true)
  }
  assert.equal(lifecycle.presenceLifecycleEnabled("none"), false)
  assert.equal(lifecycle.lifecycleMorphTarget("idle"), lifecycle.REST_TIGHTNESS)
  assert.equal(lifecycle.lifecycleMorphTarget("waiting"), lifecycle.REST_TIGHTNESS)
  assert.equal(lifecycle.lifecycleMorphTarget("offline"), lifecycle.REST_TIGHTNESS)
  assert.notEqual(lifecycle.lifecycleMorphTarget("idle"), 0)
  for (const phase of ["thinking", "listening", "speaking", "executing", "alert", "error", "approval"]) {
    assert.equal(lifecycle.lifecycleMorphTarget(phase), lifecycle.ENGAGED_TIGHTNESS)
  }

  const mat = material()
  assert.equal(mat.uniforms.uGalaxy.value, 0)
  const system = cloud.createMorphablePresenceSystem(0.02, mat, "stormbird")
  system.setLifecycleTarget(lifecycle.lifecycleMorphTarget("thinking"), { duration: 1.2 })
  system.tick(1.2)
  assert.equal(system.morphValue(), 1)
  assert.equal(system.currentShapeId, "stormbird")
  assert.equal(mat.uniforms.uGalaxy.value, 0)
  assert.match(cloud.particleVertexShader, /restHalo/)
  assert.match(cloud.particleVertexShader, /uRestTightness/)
  assert.match(cloud.particleVertexShader, /uRestRemap/)
  assert.match(cloud.particleVertexShader, /pointerFalloff \* loose \* uPointerStrength/)
  assert.equal(cloud.particleVertexShader.match(/uniform float uMorph;/g)?.length, 1)
  system.dispose()
})

test("all named personas expose their own registered visual avatar", async () => {
  const shapeIds = personas.ROSTER_IDS.map((id) => personas.PERSONA_VISUALS[id].shapeId)
  assert.equal(personas.ROSTER_IDS.length, 14)
  assert.equal(shapeIds.length, 14)
  assert.equal(new Set(shapeIds).size, 14, "Umi must not clone Nabu")
  assert.equal(personas.PERSONA_VISUALS.umi.shapeId, "opus_tide")
  for (const shapeId of shapeIds) {
    assert.equal(shapes.resolvePresenceShape(shapeId).id, shapeId)
    const variantId = variants.mythicLiveVariantShapeId(shapeId)
    const variant = shapes.resolvePresenceShape(variantId)
    assert.equal(variant.id, variantId)
    assert.equal(variant.framing?.yaw, 0, `${variantId} faces the camera`)
  }

  const controls = await readFile(new URL("./src/persona/NamedPersonaControls.tsx", import.meta.url), "utf8")
  assert.match(controls, /Named persona avatars/)
  assert.match(controls, /SpecialistShapeMark/)

  const portraits = await readFile(new URL("./src/persona/personaPortraits.ts", import.meta.url), "utf8")
  assert.match(portraits, /anzu\.png/)
  assert.match(portraits, /nabu\.png/)
  assert.doesNotMatch(portraits, /assets\/persona\/[^"']+\.webp/)
  for (const id of personas.ROSTER_IDS) {
    const bytes = await readFile(new URL(`./src/assets/persona/${id}.png`, import.meta.url))
    assert.ok(bytes.length > 40_000, `${id} portrait should retain showcase detail`)
  }
})

test("persona selection activates mythic mode on the shared morphable stage", async () => {
  const home = await readFile(new URL("./src/hud/HudChatHome.tsx", import.meta.url), "utf8")
  const settings = await readFile(new URL("./src/settings/AppearanceSettingsPane.tsx", import.meta.url), "utf8")
  const activation = await readFile(new URL("./src/persona/activateNamedPersona.ts", import.meta.url), "utf8")
  const controls = await readFile(new URL("./src/persona/NamedPersonaControls.tsx", import.meta.url), "utf8")
  const host = await readFile(new URL("./src/presence/PresenceHost.tsx", import.meta.url), "utf8")
  assert.match(home, /presentation\.requestedPresence === "humanoid"/)
  assert.match(home, /\? "humanoid_bust"/)
  assert.match(settings, /Mythic persona A · portrait cloud/)
  assert.match(settings, /Mythic persona B · live gaze/)
  assert.match(activation, /requestedPresence: "particle_bust"/)
  assert.match(activation, /avatarId: MYTHIC_LIVE_B_AVATAR_ID/)
  assert.match(activation, /Promise\.allSettled/)
  assert.match(controls, /chooseRevision\.current/)
  assert.doesNotMatch(controls, /className={`named-persona-card\$\{selected \? " active" : ""}`}[\s\S]{0,180}disabled={busy}/)
  assert.match(host, /resolved\.effective === "particle_bust"/)
  assert.doesNotMatch(host, /ParticleBustPresence/)
  assert.match(host, /key="morphable-presence"/)
  assert.equal(lifecycle.PERSONA_MORPH_SECONDS, 0.22)

  const humanoid = await readFile(new URL("./src/presence/renderers/HumanoidPresence.tsx", import.meta.url), "utf8")
  const stageCss = await readFile(new URL("./src/presence/renderers/presence-stage.css", import.meta.url), "utf8")
  assert.doesNotMatch(humanoid, /jarvis-mythic-avatar-shell/)
  assert.match(humanoid, /Portrait sampling unavailable · using the live particle avatar/)
  assert.doesNotMatch(humanoid, /preparing \|\| prepareError/)
  assert.match(stageCss, /position: absolute;/)
  assert.match(stageCss, /overflow: hidden;/)
})

test("the README muscular humanoid is additive and the production humanoid stays the default", async () => {
  const settings = await readFile(new URL("./src/settings/AppearanceSettingsPane.tsx", import.meta.url), "utf8")
  const humanoid = await readFile(new URL("./src/presence/renderers/HumanoidPresence.tsx", import.meta.url), "utf8")
  assert.match(settings, /Humanoid HUD · built in/)
  assert.match(settings, /Muscular humanoid · showcase/)
  assert.match(settings, /avatarId: "jarvis_base"/)
  assert.match(settings, /MUSCULAR_HUMANOID_AVATAR_ID/)
  assert.match(humanoid, /CURRENT_HUMANOID_ARTWORK = "\/presence\/jarvis-original\/humanoid\.webp"/)
  assert.match(humanoid, /MUSCULAR_HUMANOID_ARTWORK = "\/presence\/jarvis-original\/humanoid-muscular\.png"/)
  assert.match(humanoid, /settings\.avatarId === MUSCULAR_HUMANOID_AVATAR_ID/)
})

test("the README muscular humanoid is additive and the production humanoid stays the default", async () => {
  const settings = await readFile(new URL("./src/settings/AppearanceSettingsPane.tsx", import.meta.url), "utf8")
  const humanoid = await readFile(new URL("./src/presence/renderers/HumanoidPresence.tsx", import.meta.url), "utf8")
  assert.match(settings, /Humanoid HUD · built in/)
  assert.match(settings, /Muscular humanoid · showcase/)
  assert.match(settings, /avatarId: "jarvis_base"/)
  assert.match(settings, /MUSCULAR_HUMANOID_AVATAR_ID/)
  assert.match(humanoid, /CURRENT_HUMANOID_ARTWORK = "\/presence\/jarvis-original\/humanoid\.webp"/)
  assert.match(humanoid, /MUSCULAR_HUMANOID_ARTWORK = "\/presence\/jarvis-original\/humanoid-muscular\.png"/)
  assert.match(humanoid, /settings\.avatarId === MUSCULAR_HUMANOID_AVATAR_ID/)
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
  assert.match(cloud.particleVertexShader, /restPulse/)
  assert.match(cloud.particleVertexShader, /uListen/)
  assert.match(cloud.particleFragmentShader, /alertRing/)
  const stage = await readFile(new URL("./src/presence/renderers/MorphablePresenceStage.tsx", import.meta.url), "utf8")
  assert.match(stage, /0\.5 \+ 0\.5 \* Math\.sin\(animationTime \* 0\.92\)/)
  assert.match(stage, /if \(reduced\) alertAge = 4/)
  assert.match(stage, /meterNow\.attached && meterNow\.kind === "tts" && phase === "speaking"/)
})

test("opening HUD settings morphs the live cloud without a background starfield swap", async () => {
  const home = await readFile(new URL("./src/hud/HudChatHome.tsx", import.meta.url), "utf8")
  const shell = await readFile(new URL("./src/hud/HudShell.tsx", import.meta.url), "utf8")
  const controls = await readFile(new URL("./src/presence/AppearancePresenceControls.tsx", import.meta.url), "utf8")
  const hudCss = await readFile(new URL("./src/hud/hud-v2.css", import.meta.url), "utf8")
  const humanoidCss = await readFile(new URL("./src/presence/renderers/humanoid-presence.css", import.meta.url), "utf8")
  assert.match(home, /settingsPanelOpen \? SETTINGS_CLOUD_SHAPE_ID/)
  assert.match(controls, /onOpenChange\?\.\(openMenu !== null, openMenu\)/)
  assert.match(home, /setSettingsPanelOpen\(open && menu !== "persona"\)/)
  assert.equal(shapes.resolvePresenceShape(variants.SETTINGS_CLOUD_SHAPE_ID).id, "settings_cloud")
  assert.match(shell, /!isChat && <HudStarfield/)
  assert.match(hudCss, /inset: 0;/)
  assert.doesNotMatch(humanoidCss, /jarvis-humanoid-hud-tl::before/)
})

test("mythic live variants use distinct named-being silhouettes", async () => {
  const variantsSource = await readFile(new URL("./src/presence/renderers/shapes/mythicVariants.ts", import.meta.url), "utf8")
  for (const archetype of ["stormbird", "strategist", "owl", "water_sage", "serpent", "justice",
    "sea_giant", "bard", "messenger", "guardian", "healer", "celestial", "forge", "abyss"]) {
    assert.match(variantsSource, new RegExp(`archetype: "${archetype}"`))
  }
  assert.match(variantsSource, /buildOwlLiveFigure/)
  assert.match(variantsSource, /base\.id === "memory_rings"/)
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
  assert.ok(fit.scale > 0 && fit.scale < 1, `wide silhouettes should be scaled into the stage, got ${fit.scale}`)
  assert.equal(fit.centerX, 0)
  assert.equal(fit.centerY, 0)
  assert.equal(fit.centerZ, 0)

  const offset = quality.normalizedPresenceFitScale(
    new Float32Array([0.2, 0.4, 0, 1.2, 1.6, 0]), 1, 32, 5.6,
  )
  assert.ok(offset.scale >= 0.45 && offset.scale <= 1.35)
  assert.ok(Math.abs(offset.centerX - 0.7) < 1e-6, `AABB center X, got ${offset.centerX}`)
  assert.ok(Math.abs(offset.centerY - 1.0) < 1e-6, `AABB center Y, got ${offset.centerY}`)
  assert.equal(offset.centerZ, 0)
})

test("yaw-frame fit offset cancels AABB center under Three.js T*R*S", () => {
  // Asymmetric bust: local +X/+Z mass so yaw≈0.06 moves the silhouette center.
  const positions = new Float32Array([
    -0.8, -1.0, -0.3,
    0.8, -1.0, -0.3,
    -0.5, 1.2, -0.2,
    0.9, 1.2, 0.1,
    0.15, 0.4, 0.95,
    0.35, 0.1, 0.55,
  ])
  const yaw = quality.PRESENCE_DEFAULT_FRAMING_YAW
  const fit = quality.normalizedPresenceFitScale(positions, 680 / 480, 32, 5.6, yaw, 0.88)
  assert.ok(Math.abs(fit.centerX) > 1e-4 || Math.abs(fit.centerZ) > 1e-4, "fixture must be off-center under yaw")

  const scale = fit.scale
  const parent = quality.presenceFitYawFrameOffset(fit, scale)
  // Parent translation stays in the yaw frame (not pre-rotate local X).
  assert.ok(Math.abs(parent.x + fit.centerX * scale) < 1e-9)
  assert.ok(Math.abs(parent.y + fit.centerY * scale) < 1e-9)
  assert.ok(Math.abs(parent.z + fit.centerZ * scale) < 1e-9)

  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  let minZ = Number.POSITIVE_INFINITY
  let maxZ = Number.NEGATIVE_INFINITY
  for (let i = 0; i < positions.length; i += 3) {
    const lx = positions[i] * scale
    const ly = positions[i + 1] * scale
    const lz = positions[i + 2] * scale
    // T * R_yaw * S — same composition as MorphablePresenceStage bust.
    const xr = lx * c + lz * s
    const zr = -lx * s + lz * c
    const x = parent.x + xr
    const y = parent.y + ly
    const z = parent.z + zr
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
    minZ = Math.min(minZ, z)
    maxZ = Math.max(maxZ, z)
  }
  assert.ok(Math.abs((minX + maxX) * 0.5) < 1e-6, `yaw-frame center X should land on origin, got ${(minX + maxX) * 0.5}`)
  assert.ok(Math.abs((minY + maxY) * 0.5) < 1e-6, `yaw-frame center Y should land on origin, got ${(minY + maxY) * 0.5}`)
  assert.ok(Math.abs((minZ + maxZ) * 0.5) < 1e-6, `yaw-frame center Z should land on origin, got ${(minZ + maxZ) * 0.5}`)

  // Wrong frame: treating yawed centerX as pre-rotate local X leaves residual at yaw≈0.06.
  const wrongLocal = -fit.centerX * scale
  let wMinX = Number.POSITIVE_INFINITY
  let wMaxX = Number.NEGATIVE_INFINITY
  for (let i = 0; i < positions.length; i += 3) {
    const lx = (positions[i] + wrongLocal / scale) * scale
    const lz = positions[i + 2] * scale
    const x = lx * c + lz * s
    wMinX = Math.min(wMinX, x)
    wMaxX = Math.max(wMaxX, x)
  }
  assert.ok(
    Math.abs((wMinX + wMaxX) * 0.5) > 1e-4,
    "pre-rotate misuse of yawed centerX must remain off-center (guards the harden)",
  )
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

test("catalog shapes resolve a safe AABB frame in desktop, ultrawide, portrait, and short stages", () => {
  for (const shape of shapes.listPresenceShapes()) {
    const orbs = shape.buildFigure(0.08)
    const samples = shapes.resampleOrbs(orbs, Math.min(600, Math.max(1, orbs.length)))
    const positions = new Float32Array(samples.length * 3)
    samples.forEach((orb, i) => positions.set([orb.x, orb.y, orb.z], i * 3))
    for (const [aspect, fov, distance] of [[1.7, 32, 5.6], [3.2, 32, 5.6], [0.58, 37, 6.15], [1.2, 32, 5.6]]) {
      // Match MorphablePresenceStage: missing yaw uses PRESENCE_DEFAULT_FRAMING_YAW.
      const yaw = shape.framing?.yaw ?? quality.PRESENCE_DEFAULT_FRAMING_YAW
      const margin = shape.framing?.fitMargin ?? 0.88
      const landmarks = quality.resolveShapeLandmarks(shape.framing?.landmarks, positions, yaw)
      const fit = quality.normalizedPresenceFitScale(
        positions, aspect, fov, distance, yaw, margin, shape.framing?.landmarks,
      )
      assert.ok(Number.isFinite(fit.scale) && fit.scale >= 0.45 && fit.scale <= 1.35, `${shape.id} should fit at aspect ${aspect}`)
      assert.ok(Number.isFinite(landmarks.crown) && landmarks.crown > landmarks.chin, `${shape.id} crown/chin`)
      const c = Math.cos(yaw)
      const s = Math.sin(yaw)
      let minX = Number.POSITIVE_INFINITY
      let maxX = Number.NEGATIVE_INFINITY
      let minY = Number.POSITIVE_INFINITY
      let maxY = Number.NEGATIVE_INFINITY
      let minZ = Number.POSITIVE_INFINITY
      let maxZ = Number.NEGATIVE_INFINITY
      for (let i = 0; i < positions.length; i += 3) {
        const lx = positions[i]
        const ly = positions[i + 1]
        const lz = positions[i + 2]
        const x = lx * c + lz * s
        const z = -lx * s + lz * c
        minX = Math.min(minX, x)
        maxX = Math.max(maxX, x)
        minY = Math.min(minY, ly)
        maxY = Math.max(maxY, ly)
        minZ = Math.min(minZ, z)
        maxZ = Math.max(maxZ, z)
      }
      minY = Math.min(minY, landmarks.chin, landmarks.motifBounds.minY)
      maxY = Math.max(maxY, landmarks.crown, landmarks.motifBounds.maxY)
      minX = Math.min(minX, landmarks.motifBounds.minX)
      maxX = Math.max(maxX, landmarks.motifBounds.maxX)
      minZ = Math.min(minZ, landmarks.motifBounds.minZ)
      maxZ = Math.max(maxZ, landmarks.motifBounds.maxZ)
      const spanX = maxX - minX
      const spanY = maxY - minY
      const visibleHeight = 2 * distance * Math.tan((fov * Math.PI) / 360)
      const visibleWidth = visibleHeight * aspect
      assert.ok(spanX * fit.scale <= visibleWidth * margin + 0.02, `${shape.id} should fit stage width at aspect ${aspect}`)
      assert.ok(spanY * fit.scale <= visibleHeight * margin + 0.02, `${shape.id} should fit stage height at aspect ${aspect}`)
      assert.ok(Math.abs(fit.centerX - (minX + maxX) * 0.5) < 1e-6, `${shape.id} centerX`)
      assert.ok(Math.abs(fit.centerY - (minY + maxY) * 0.5) < 1e-6, `${shape.id} centerY`)
      assert.ok(Math.abs(fit.centerZ - (minZ + maxZ) * 0.5) < 1e-6, `${shape.id} centerZ`)
      const parent = quality.presenceFitYawFrameOffset(fit, fit.scale)
      assert.ok(Math.abs((minX + maxX) * 0.5 * fit.scale + parent.x) < 1e-6, `${shape.id} yaw-frame offset X`)
      assert.ok(Math.abs((minY + maxY) * 0.5 * fit.scale + parent.y) < 1e-6, `${shape.id} yaw-frame offset Y`)
      assert.ok(Math.abs((minZ + maxZ) * 0.5 * fit.scale + parent.z) < 1e-6, `${shape.id} yaw-frame offset Z`)
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
