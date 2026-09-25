import * as THREE from "three"
import { presenceBudgets } from "../galaxyPresence"
import { LIFECYCLE_MORPH_SECONDS } from "../presenceLifecycle"
import type { ParticleOrb } from "./particleTypes"
import { makeRng } from "./shapes/figureKit"
import {
  presenceShapeIdForAvatar,
  resampleOrbs,
  resolvePresenceShape,
} from "./shapes/catalog"
import type { PresenceShapeId } from "./particleTypes"

export const particleVertexShader = `
  attribute vec3 aPos;
  attribute vec3 bPos;
  attribute float aSize;
  attribute float bSize;
  attribute float aGold;
  attribute float bGold;
  attribute float aLight;
  attribute float bLight;
  attribute float aFlow;
  attribute float bFlow;
  attribute float aSeed;
  uniform float uTime;
  uniform float uMotion;
  uniform float uActivity;
  uniform float uSpeech;
  uniform float uPixelScale;
  uniform float uMorph;
  uniform float uPhaseKind;
  uniform float uGlow;
  uniform float uGalaxy;
  uniform float uGalaxyBust;
  uniform float uLattice;
  uniform vec2 uPointer;
  uniform float uPointerStrength;
  uniform float uGesture;
  varying float vGold;
  varying float vLight;
  varying float vFlow;
  varying float vDepth;
  varying vec3 vPos;
  varying float vSeed;
  void main() {
    float m = smoothstep(0.0, 1.0, uMorph);
    vec3 p = mix(aPos, bPos, m);
    float flow = mix(aFlow, bFlow, m);
    float size = mix(aSize, bSize, m);
    float t = uTime;
    if (flow > 0.8 && flow < 1.5) {
      p.y += (sin(p.x * 2.8 - t * 0.6) * 0.14 + sin(p.x * 6.5 + t * 0.45) * 0.06) * uMotion;
      p.z += sin(p.x * 1.8 + t * 0.25) * 0.1 * uMotion;
    } else if (flow < 0.8) {
      float loose = step(0.2, flow);
      p.x += sin(t * 0.55 + aSeed * 42.0) * 0.055 * loose * uMotion;
      p.y += cos(t * 0.45 + aSeed * 31.0) * 0.06 * loose * uMotion;
      float sweep = pow(max(0.0, sin(t * 0.4 + p.y * 0.8)), 5.0);
      float drift = loose * (0.08 + uActivity * 0.2 + uGesture * 0.14) * sweep * uMotion;
      p.x += drift * (0.5 + aSeed) * smoothstep(-0.3, 0.5, p.x);
      // State energy may loosen the halo, but must never tear the anatomical
      // head/shoulder cloud apart.
      float dissolve = loose * smoothstep(0.65, 1.0, uActivity) * smoothstep(0.65, 0.95, aSeed) * uMotion;
      p.x += dissolve * (0.35 + sin(t * 0.7 + aSeed * 8.0) * 0.2);
      p.y += dissolve * sin(t * 0.55 + aSeed * 13.0) * 0.35;
      p.z += sin(p.y * 7.0 - t * 1.3) * (0.004 + uSpeech * 0.025) * uMotion;
      // Pointer energy belongs to the loose halo, never the anatomical core.
      vec2 pointerDelta = p.xy - uPointer;
      float pointerDistance = length(pointerDelta);
      float pointerFalloff = 1.0 - smoothstep(0.12, 0.82, pointerDistance);
      vec2 pointerDirection = pointerDelta / max(pointerDistance, 0.045);
      p.xy += pointerDirection * pointerFalloff * loose * uPointerStrength * 0.065 * uMotion;
      p.z += pointerFalloff * loose * uPointerStrength * (0.012 + aSeed * 0.018) * uMotion;
    } else {
      p *= 1.0 + uSpeech * 0.03 * sin(t * 9.5);
    }
    // Free-float attract (RFC-0175). Idle orbs are drawn toward uPointer
    // (pointer, or a live camera face). The pull fades as uMorph reaches the figure.
    float freeWeight = 1.0 - m;
    if (freeWeight > 0.001 && uPointerStrength > 0.001) {
      vec2 towardPointer = uPointer - p.xy;
      float pointerReach = length(towardPointer);
      vec2 attractDir = towardPointer / max(pointerReach, 0.04);
      float attractFalloff = smoothstep(0.02, 1.85, pointerReach);
      float pull = freeWeight * uPointerStrength * attractFalloff * uMotion;
      p.xy += attractDir * pull * 0.72;
      p.z += pull * (0.015 + aSeed * 0.03);
    }
    float working = step(2.5, uPhaseKind) * (1.0 - step(3.5, uPhaseKind));
    float thinking = step(1.5, uPhaseKind) * (1.0 - step(2.5, uPhaseKind));
    if (flow > 0.22 && flow < 0.72) {
      float ang = t * (0.9 * working + 0.32 * thinking) * uMotion;
      float c = cos(ang);
      float s = sin(ang);
      float x = p.x;
      float z = p.z;
      p.x = x * c - z * s;
      p.z = x * s + z * c;
      p *= 1.0 + thinking * uMotion * 0.05 * sin(t * 1.6);
    }
    if (uGalaxy > 0.5) {
      float crown = smoothstep(1.05, 1.75, p.y);
      float side = smoothstep(0.7, 1.45, abs(p.x));
      float edge = max(crown, side);
      float amp = edge * mix(0.42, 0.22, uLattice);
      p.x += (aSeed - 0.5) * amp * 1.4;
      p.y += (fract(aSeed * 7.0) - 0.5) * amp;
      p.z += (fract(aSeed * 13.0) - 0.5) * amp * 0.6;
      p.x += sin(uTime * 0.22 + aSeed * 40.0) * 0.03 * uMotion;
      p.y += cos(uTime * 0.18 + aSeed * 19.0) * 0.02 * uMotion;
    }
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(size * uPixelScale * 6.6 / -mv.z, 0.72, 96.0);
    if (uGalaxyBust > 0.5) {
      float goldNow = mix(aGold, bGold, m);
      float neck = step(0.45, goldNow) * (1.0 - smoothstep(0.15, 0.45, p.y)) * smoothstep(-1.35, -0.2, p.y);
      float idleScale = mix(0.78, 1.0, uLattice);
      float neckScale = mix(1.0, 0.62, neck * uLattice);
      float band = pow(abs(sin(p.y * 52.0)), 8.0);
      float cranial = smoothstep(0.35, 0.6, p.y) * (1.0 - smoothstep(1.45, 1.75, p.y));
      float fiber = band * cranial * (1.0 - step(0.55, goldNow)) * uLattice;
      gl_PointSize *= idleScale * neckScale * mix(1.0, 1.35, fiber);
    }
    vGold = mix(aGold, bGold, m);
    vFlow = flow;
    vDepth = p.z;
    vPos = p;
    vSeed = aSeed;
    float shimmer = 0.87 + 0.13 * sin(t * 1.2 + aSeed * 60.0);
    float wave = pow(max(0.0, sin(p.y * 3.5 - t * 1.1)), 8.0) * (uActivity + uGesture * .35);
    float light = mix(aLight, bLight, m);
    vLight = light * (mix(1.0, shimmer, uMotion) + wave * uMotion * 0.24);
  }
`

export const particleFragmentShader = `
  uniform vec3 uColor;
  uniform vec3 uGold;
  uniform vec3 uAccent;
  uniform float uOpacity;
  uniform float uTime;
  uniform float uMotion;
  uniform float uSpeech;
  uniform float uPhaseKind;
  uniform float uGlow;
  uniform float uGalaxy;
  uniform float uGalaxyBust;
  uniform float uLattice;
  varying float vGold;
  varying float vLight;
  varying float vFlow;
  varying float vDepth;
  varying vec3 vPos;
  varying float vSeed;
  void main() {
    float r = length(gl_PointCoord - 0.5) * 2.0;
    if (r > 1.0) discard;
    // Soft glowing orb (not a hard mesh texel).
    float loose = step(0.2, vFlow) * (1.0 - step(0.8, vFlow));
    float environment = step(0.8, vFlow);
    float core = exp(-r * r * 18.0) * mix(1.0, 0.42, loose);
    float halo = exp(-r * r * 3.6) * mix(0.45, 0.62, loose);
    float depthWeight = mix(clamp(0.72 + vDepth * 0.52, 0.52, 1.12), 1.0, environment);
    float alpha = (core + halo) * (1.0 - smoothstep(0.6, 1.0, r))
      * vLight * uOpacity * depthWeight * mix(1.0, 0.72, loose);
    float errorPhase = step(6.5, uPhaseKind) * (1.0 - step(7.5, uPhaseKind)) * step(0.01, uMotion);
    float flicker = mix(1.0, 0.42 + 0.58 * step(0.55, fract(sin(uTime * 23.0 + vDepth * 12.0) * 43758.5)), errorPhase);
    alpha *= flicker * mix(1.0, uGlow, 0.65);
    float goldAmt = vGold;
    float cranial = smoothstep(0.45, 0.7, vPos.y) * (1.0 - smoothstep(1.35, 1.7, vPos.y));
    cranial *= 1.0 - smoothstep(0.42, 0.75, abs(vPos.x));
    float neckGold = step(0.45, vGold) * smoothstep(0.28, -0.15, vPos.y) * smoothstep(-1.4, -0.15, vPos.y);
    if (uGalaxyBust > 0.5) {
      float goldKeep = mix(0.0, mix(neckGold * 0.72, 1.0, cranial), uLattice);
      goldAmt *= goldKeep;
      float corePulse = step(1.5, vFlow);
      alpha *= mix(1.0, mix(0.12, 1.0, uLattice), corePulse);
      if (uLattice < 0.5 && environment < 0.5) alpha *= 0.48;
      if (uLattice < 0.5 && vGold > 0.45) alpha *= 0.12;
      if (environment > 0.5) alpha *= mix(0.16, 1.0, uLattice);
      alpha *= 1.0 + uSpeech * cranial * uLattice * 0.9;
    }
    if (uGalaxy > 0.5 && environment < 0.5) {
      float crown = smoothstep(1.15, 1.9, vPos.y);
      float side = smoothstep(0.8, 1.7, abs(vPos.x));
      alpha *= 1.0 - max(crown, side) * mix(0.9, 0.42, uLattice);
    }
    vec3 color = mix(uColor, uGold, smoothstep(0.13, 0.75, goldAmt));
    if (uGalaxyBust > 0.5 && uLattice > 0.5) {
      float fiber = pow(abs(sin(vPos.y * 55.0)), 6.0);
      float shell = 1.0 - smoothstep(0.2, 0.7, goldAmt);
      float head = smoothstep(0.25, 0.55, vPos.y) * (1.0 - smoothstep(1.55, 1.85, vPos.y));
      color = mix(color, uColor * 1.35, fiber * shell * head * 0.75);
      alpha *= mix(1.0, 1.18, fiber * shell * head);
    }
    if (uGalaxy > 0.5) {
      float highlight = step(0.93, vSeed) * (1.0 - smoothstep(0.2, 0.55, goldAmt));
      color = mix(color, uAccent, highlight * 0.7);
    }
    float hot = smoothstep(2.4, 4.5, vLight);
    gl_FragColor = vec4(color + vec3(core * (0.18 + hot * 0.42)), alpha);
  }
`

function writeSlot(
  orbs: ParticleOrb[],
  pos: Float32Array,
  size: Float32Array,
  gold: Float32Array,
  light: Float32Array,
  flow: Float32Array,
) {
  for (let i = 0; i < orbs.length; i++) {
    const orb = orbs[i]
    const i3 = i * 3
    pos[i3] = orb.x
    pos[i3 + 1] = orb.y
    pos[i3 + 2] = orb.z
    size[i] = orb.size
    gold[i] = orb.gold
    light[i] = orb.light
    flow[i] = orb.flow
  }
}

/**
 * Idle end of uMorph. Scattered cool orbs — not a head-and-shoulders bust.
 * Gold stays off so the amber core appears only as the figure wins.
 */
export function buildFreeFloatCloud(count: number): ParticleOrb[] {
  const random = makeRng(1750917)
  const orbs: ParticleOrb[] = []
  for (let i = 0; i < count; i++) {
    const angle = random() * Math.PI * 2
    const radius = Math.pow(random(), 0.55) * 1.7
    const y = (random() - 0.42) * 1.55
    const z = (random() - 0.5) * 1.1
    const edge = radius / 1.7
    orbs.push({
      x: Math.cos(angle) * radius,
      y,
      z,
      gold: 0,
      light: 0.25 + (1 - edge) * 0.85,
      flow: 0.34 + random() * 0.28,
      size: 0.85 + random() * 1.25,
    })
  }
  return orbs
}

function geometryFromOrbs(
  orbs: ParticleOrb[],
  material: THREE.ShaderMaterial,
  targetOrbs?: ParticleOrb[],
): THREE.Points {
  const count = orbs.length
  const bOrbs = targetOrbs && targetOrbs.length === count ? targetOrbs : orbs
  const aPos = new Float32Array(count * 3)
  const bPos = new Float32Array(count * 3)
  const aSize = new Float32Array(count)
  const bSize = new Float32Array(count)
  const aGold = new Float32Array(count)
  const bGold = new Float32Array(count)
  const aLight = new Float32Array(count)
  const bLight = new Float32Array(count)
  const aFlow = new Float32Array(count)
  const bFlow = new Float32Array(count)
  const seeds = new Float32Array(count)
  writeSlot(orbs, aPos, aSize, aGold, aLight, aFlow)
  writeSlot(bOrbs, bPos, bSize, bGold, bLight, bFlow)
  for (let i = 0; i < count; i++) seeds[i] = (i * 0.618033) % 1

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute("position", new THREE.BufferAttribute(aPos.slice(), 3))
  geometry.setAttribute("aPos", new THREE.BufferAttribute(aPos, 3))
  geometry.setAttribute("bPos", new THREE.BufferAttribute(bPos, 3))
  geometry.setAttribute("aSize", new THREE.BufferAttribute(aSize, 1))
  geometry.setAttribute("bSize", new THREE.BufferAttribute(bSize, 1))
  geometry.setAttribute("aGold", new THREE.BufferAttribute(aGold, 1))
  geometry.setAttribute("bGold", new THREE.BufferAttribute(bGold, 1))
  geometry.setAttribute("aLight", new THREE.BufferAttribute(aLight, 1))
  geometry.setAttribute("bLight", new THREE.BufferAttribute(bLight, 1))
  geometry.setAttribute("aFlow", new THREE.BufferAttribute(aFlow, 1))
  geometry.setAttribute("bFlow", new THREE.BufferAttribute(bFlow, 1))
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1))
  return new THREE.Points(geometry, material)
}

const galaxyStarVertexShader = `
  attribute float aSeed;
  attribute float aSize;
  attribute float aWarm;
  uniform float uTime;
  uniform float uMotion;
  varying float vWarm;
  varying float vSeed;
  void main() {
    vec3 p = position;
    p.x += sin(uTime * 0.05 + aSeed * 20.0) * 0.12 * uMotion;
    p.y += cos(uTime * 0.04 + aSeed * 12.0) * 0.08 * uMotion;
    p.z += uTime * 0.06 * uMotion;
    p.x = mod(p.x + 14.0, 28.0) - 14.0;
    p.y = mod(p.y + 8.0, 16.0) - 8.0;
    p.z = mod(p.z + 2.0, 18.0) - 20.0;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * 18.0 / -mv.z, 0.4, 3.2);
    vWarm = aWarm;
    vSeed = aSeed;
  }
`

const galaxyStarFragmentShader = `
  varying float vWarm;
  varying float vSeed;
  void main() {
    float r = length(gl_PointCoord - 0.5) * 2.0;
    if (r > 1.0) discard;
    float core = exp(-r * r * 14.0);
    float alpha = core * (0.35 + vSeed * 0.65);
    vec3 cool = vec3(0.72, 0.86, 1.0);
    vec3 warm = vec3(1.0, 0.78, 0.42);
    gl_FragColor = vec4(mix(cool, warm, vWarm) * (0.7 + core), alpha);
  }
`

function createGalaxyStarLayer(density: number): { points: THREE.Points; material: THREE.ShaderMaterial } {
  const count = presenceBudgets(density).galaxyStars
  const positions = new Float32Array(count * 3)
  const seeds = new Float32Array(count)
  const sizes = new Float32Array(count)
  const warm = new Float32Array(count)
  for (let i = 0; i < count; i++) {
    const s = (i * 0.61803398875) % 1
    const s2 = ((i + 17) * 0.41421356237) % 1
    const s3 = ((i + 91) * 0.70710678118) % 1
    const inView = s < 0.72
    positions[i * 3] = (s2 - 0.5) * (inView ? 9 : 28)
    positions[i * 3 + 1] = (s3 - 0.46) * (inView ? 7.2 : 16)
    positions[i * 3 + 2] = -1.6 - ((i * 0.173) % 1) * (inView ? 12 : 18)
    seeds[i] = s
    sizes[i] = 0.28 + s3 * (inView ? 1.15 : 0.7)
    warm[i] = s2 < 0.07 ? 1 : 0
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1))
  geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1))
  geometry.setAttribute("aWarm", new THREE.BufferAttribute(warm, 1))
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uMotion: { value: 1 },
    },
    vertexShader: galaxyStarVertexShader,
    fragmentShader: galaxyStarFragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
  })
  const points = new THREE.Points(geometry, material)
  points.visible = false
  points.frustumCulled = false
  return { points, material }
}

export type MorphablePresenceSystem = {
  group: THREE.Group
  bust: THREE.Group
  figure: THREE.Points
  field: THREE.Points | null
  stars: THREE.Points
  currentShapeId: PresenceShapeId
  morphTo: (shapeId: PresenceShapeId, opts?: { duration?: number; immediate?: boolean }) => void
  /** 0 = free cloud, 1 = winning figure. One uniform. Does not remount the cloud. */
  setLifecycleTarget: (target: 0 | 1, opts?: { duration?: number; immediate?: boolean }) => void
  morphValue: () => number
  tick: (delta: number) => void
  setGalaxy: (on: boolean) => void
  syncStars: (time: number, motion: number) => void
  dispose: () => void
}

export function createMorphablePresenceSystem(
  density: number,
  material: THREE.ShaderMaterial,
  initialShapeId?: PresenceShapeId,
): MorphablePresenceSystem {
  // Put the budget where the user reads identity: the face and shoulders.
  // The flowing environment stays intact but no longer outnumbers the bust.
  // Galaxy stars are a separate layer (presenceBudgets) and do not reduce these.
  const figureBudget = Math.round(82000 * density)
  const fieldBudget = Math.round(15000 * density)
  let shape = resolvePresenceShape(initialShapeId)
  let figureOrbs = resampleOrbs(shape.buildFigure(density), figureBudget)
  const freeOrbs = buildFreeFloatCloud(figureBudget)
  // aPos = free cloud (uMorph 0). bPos = winning figure (uMorph 1).
  const figure = geometryFromOrbs(freeOrbs, material, figureOrbs)
  let field: THREE.Points | null = null
  if (shape.buildField) {
    field = geometryFromOrbs(resampleOrbs(shape.buildField(density), fieldBudget), material)
  }
  const galaxyStars = createGalaxyStarLayer(density)

  const group = new THREE.Group()
  const bust = new THREE.Group()
  bust.add(figure)
  group.add(bust)
  if (field) group.add(field)
  group.add(galaxyStars.points)

  let lifecycleTarget: 0 | 1 = 0
  let animFrom = 0
  let animTo = 0
  let animElapsed = 0
  let animDuration = 0
  let animating = false
  let shapeBlendActive = false
  let pendingFigureRestore = false
  let restoreFreeOnArrive = false
  const uniforms = material.uniforms
  uniforms.uMorph = uniforms.uMorph ?? { value: 0 }
  uniforms.uMorph.value = 0

  const copyCurrentToA = (points: THREE.Points) => {
    const geo = points.geometry
    const aPos = geo.getAttribute("aPos") as THREE.BufferAttribute
    const bPos = geo.getAttribute("bPos") as THREE.BufferAttribute
    const aSize = geo.getAttribute("aSize") as THREE.BufferAttribute
    const bSize = geo.getAttribute("bSize") as THREE.BufferAttribute
    const aGold = geo.getAttribute("aGold") as THREE.BufferAttribute
    const bGold = geo.getAttribute("bGold") as THREE.BufferAttribute
    const aLight = geo.getAttribute("aLight") as THREE.BufferAttribute
    const bLight = geo.getAttribute("bLight") as THREE.BufferAttribute
    const aFlow = geo.getAttribute("aFlow") as THREE.BufferAttribute
    const bFlow = geo.getAttribute("bFlow") as THREE.BufferAttribute
    const m = uniforms.uMorph.value as number
    for (let i = 0; i < aPos.count; i++) {
      const i3 = i * 3
      aPos.array[i3] = aPos.array[i3] * (1 - m) + bPos.array[i3] * m
      aPos.array[i3 + 1] = aPos.array[i3 + 1] * (1 - m) + bPos.array[i3 + 1] * m
      aPos.array[i3 + 2] = aPos.array[i3 + 2] * (1 - m) + bPos.array[i3 + 2] * m
      aSize.array[i] = aSize.array[i] * (1 - m) + bSize.array[i] * m
      aGold.array[i] = aGold.array[i] * (1 - m) + bGold.array[i] * m
      aLight.array[i] = aLight.array[i] * (1 - m) + bLight.array[i] * m
      aFlow.array[i] = aFlow.array[i] * (1 - m) + bFlow.array[i] * m
    }
    aPos.needsUpdate = true
    aSize.needsUpdate = true
    aGold.needsUpdate = true
    aLight.needsUpdate = true
    aFlow.needsUpdate = true
  }

  const writeSlotAttr = (points: THREE.Points, orbs: ParticleOrb[], slot: "a" | "b") => {
    const geo = points.geometry
    const pos = geo.getAttribute(`${slot}Pos`) as THREE.BufferAttribute
    const size = geo.getAttribute(`${slot}Size`) as THREE.BufferAttribute
    const gold = geo.getAttribute(`${slot}Gold`) as THREE.BufferAttribute
    const light = geo.getAttribute(`${slot}Light`) as THREE.BufferAttribute
    const flow = geo.getAttribute(`${slot}Flow`) as THREE.BufferAttribute
    const n = Math.min(orbs.length, pos.count)
    for (let i = 0; i < n; i++) {
      const orb = orbs[i]
      const i3 = i * 3
      pos.array[i3] = orb.x
      pos.array[i3 + 1] = orb.y
      pos.array[i3 + 2] = orb.z
      size.array[i] = orb.size
      gold.array[i] = orb.gold
      light.array[i] = orb.light
      flow.array[i] = orb.flow
    }
    pos.needsUpdate = true
    size.needsUpdate = true
    gold.needsUpdate = true
    light.needsUpdate = true
    flow.needsUpdate = true
  }

  const anchorFreeAndFigure = () => {
    writeSlotAttr(figure, freeOrbs, "a")
    writeSlotAttr(figure, figureOrbs, "b")
  }

  const captureDisplayed = (): ParticleOrb[] => {
    const geo = figure.geometry
    const aPos = geo.getAttribute("aPos") as THREE.BufferAttribute
    const bPos = geo.getAttribute("bPos") as THREE.BufferAttribute
    const aSize = geo.getAttribute("aSize") as THREE.BufferAttribute
    const bSize = geo.getAttribute("bSize") as THREE.BufferAttribute
    const aGold = geo.getAttribute("aGold") as THREE.BufferAttribute
    const bGold = geo.getAttribute("bGold") as THREE.BufferAttribute
    const aLight = geo.getAttribute("aLight") as THREE.BufferAttribute
    const bLight = geo.getAttribute("bLight") as THREE.BufferAttribute
    const aFlow = geo.getAttribute("aFlow") as THREE.BufferAttribute
    const bFlow = geo.getAttribute("bFlow") as THREE.BufferAttribute
    const m = uniforms.uMorph.value as number
    const out: ParticleOrb[] = []
    for (let i = 0; i < aPos.count; i++) {
      const i3 = i * 3
      out.push({
        x: aPos.array[i3] * (1 - m) + bPos.array[i3] * m,
        y: aPos.array[i3 + 1] * (1 - m) + bPos.array[i3 + 1] * m,
        z: aPos.array[i3 + 2] * (1 - m) + bPos.array[i3 + 2] * m,
        size: aSize.array[i] * (1 - m) + bSize.array[i] * m,
        gold: aGold.array[i] * (1 - m) + bGold.array[i] * m,
        light: aLight.array[i] * (1 - m) + bLight.array[i] * m,
        flow: aFlow.array[i] * (1 - m) + bFlow.array[i] * m,
      })
    }
    return out
  }

  const beginReturnToFree = (duration: number) => {
    const current = captureDisplayed()
    writeSlotAttr(figure, freeOrbs, "a")
    writeSlotAttr(figure, current, "b")
    uniforms.uMorph.value = 1
    animFrom = 1
    animTo = 0
    animElapsed = 0
    animDuration = duration
    animating = true
    shapeBlendActive = false
    pendingFigureRestore = true
    restoreFreeOnArrive = false
  }

  const applyFraming = (target: THREE.Object3D) => {
    const framing = shape.framing
    target.rotation.y = framing?.yaw ?? 0
    const pos = framing?.position ?? [0, 0, 0]
    target.position.set(pos[0], pos[1], pos[2])
  }
  applyFraming(bust)

  const system: MorphablePresenceSystem = {
    group,
    bust,
    figure,
    field,
    stars: galaxyStars.points,
    currentShapeId: shape.id,
    morphValue() {
      return uniforms.uMorph.value as number
    },
    setLifecycleTarget(target, opts) {
      const duration = opts?.duration ?? LIFECYCLE_MORPH_SECONDS
      const immediate = Boolean(opts?.immediate) || duration <= 0
      const previous = lifecycleTarget
      lifecycleTarget = target
      const current = uniforms.uMorph.value as number
      if (
        previous === target
        && !animating
        && !shapeBlendActive
        && !pendingFigureRestore
        && !restoreFreeOnArrive
        && Math.abs(current - target) < 0.0008
      ) {
        return
      }
      if (immediate) {
        anchorFreeAndFigure()
        uniforms.uMorph.value = target
        animating = false
        shapeBlendActive = false
        pendingFigureRestore = false
        restoreFreeOnArrive = false
        return
      }
      if (shapeBlendActive && target === 1) return
      if (shapeBlendActive && target === 0) {
        beginReturnToFree(duration)
        return
      }
      if (pendingFigureRestore && target === 0) return
      if (restoreFreeOnArrive && target === 1) return
      if (animating && animTo === target && !shapeBlendActive) return
      if (!animating && Math.abs(current - target) < 0.0008) return
      animFrom = current
      animTo = target
      animElapsed = 0
      animDuration = duration
      animating = true
    },
    morphTo(shapeId, opts) {
      if (shapeId === system.currentShapeId) return
      const next = resolvePresenceShape(shapeId)
      const nextOrbs = resampleOrbs(next.buildFigure(density), figureBudget)

      // Field swaps immediately (environment of the target shape). Figure lerps.
      if (field) {
        group.remove(field)
        field.geometry.dispose()
        field = null
        system.field = null
      }
      if (next.buildField) {
        field = geometryFromOrbs(resampleOrbs(next.buildField(density), fieldBudget), material)
        group.add(field)
        system.field = field
      }

      shape = next
      system.currentShapeId = next.id
      figureOrbs = nextOrbs
      applyFraming(bust)

      const immediate = Boolean(opts?.immediate) || (opts?.duration ?? LIFECYCLE_MORPH_SECONDS) <= 0
      const morphNow = uniforms.uMorph.value as number
      if (immediate) {
        anchorFreeAndFigure()
        uniforms.uMorph.value = lifecycleTarget
        animating = false
        shapeBlendActive = false
        pendingFigureRestore = false
        restoreFreeOnArrive = false
        return
      }
      // Still on the free cloud: keep aPos free and retarget bPos. Lifecycle drives uMorph.
      if (morphNow <= 0.001 && !shapeBlendActive) {
        writeSlotAttr(figure, freeOrbs, "a")
        writeSlotAttr(figure, figureOrbs, "b")
        return
      }
      copyCurrentToA(figure)
      writeSlotAttr(figure, figureOrbs, "b")
      shapeBlendActive = true
      pendingFigureRestore = false
      restoreFreeOnArrive = true
      animFrom = 0
      animTo = 1
      animElapsed = 0
      animDuration = opts?.duration ?? LIFECYCLE_MORPH_SECONDS
      animating = true
      uniforms.uMorph.value = 0
    },
    tick(delta) {
      if (!animating) return
      animElapsed += delta
      const t = Math.min(1, animElapsed / Math.max(0.0001, animDuration))
      const morph = animFrom + (animTo - animFrom) * t
      uniforms.uMorph.value = morph
      if (t < 1) return
      animating = false
      uniforms.uMorph.value = animTo
      if (shapeBlendActive || restoreFreeOnArrive) {
        anchorFreeAndFigure()
        uniforms.uMorph.value = 1
        shapeBlendActive = false
        restoreFreeOnArrive = false
        return
      }
      if (pendingFigureRestore) {
        writeSlotAttr(figure, figureOrbs, "b")
        uniforms.uMorph.value = 0
        pendingFigureRestore = false
      }
    },
    setGalaxy(on) {
      galaxyStars.points.visible = on
    },
    syncStars(time, motion) {
      galaxyStars.material.uniforms.uTime.value = time
      galaxyStars.material.uniforms.uMotion.value = motion
    },
    dispose() {
      figure.geometry.dispose()
      field?.geometry.dispose()
      galaxyStars.points.geometry.dispose()
      galaxyStars.material.dispose()
    },
  }

  return system
}

export function createPresenceSystemForAvatar(
  density: number,
  material: THREE.ShaderMaterial,
  avatarId: string | undefined,
) {
  return createMorphablePresenceSystem(density, material, presenceShapeIdForAvatar(avatarId))
}
