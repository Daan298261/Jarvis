import * as THREE from "three"
import type { ParticleOrb } from "./particleTypes"
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
  varying float vGold;
  varying float vLight;
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
      float drift = loose * (0.08 + uActivity * 0.2) * sweep * uMotion;
      p.x += drift * (0.5 + aSeed) * smoothstep(-0.3, 0.5, p.x);
      float dissolve = smoothstep(0.65, 1.0, uActivity) * smoothstep(0.65, 0.95, aSeed) * uMotion;
      p.x += dissolve * (0.35 + sin(t * 0.7 + aSeed * 8.0) * 0.2);
      p.y += dissolve * sin(t * 0.55 + aSeed * 13.0) * 0.35;
      p.z += sin(p.y * 7.0 - t * 1.3) * (0.004 + uSpeech * 0.025) * uMotion;
    } else {
      p *= 1.0 + uSpeech * 0.03 * sin(t * 9.5);
    }
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(size * uPixelScale * 7.1 / -mv.z, 0.8, 120.0);
    vGold = mix(aGold, bGold, m);
    float shimmer = 0.87 + 0.13 * sin(t * 1.2 + aSeed * 60.0);
    float wave = pow(max(0.0, sin(p.y * 3.5 - t * 1.1)), 8.0) * uActivity;
    float light = mix(aLight, bLight, m);
    vLight = light * (mix(1.0, shimmer, uMotion) + wave * uMotion * 0.24);
  }
`

export const particleFragmentShader = `
  uniform vec3 uColor;
  uniform vec3 uGold;
  uniform float uOpacity;
  varying float vGold;
  varying float vLight;
  void main() {
    float r = length(gl_PointCoord - 0.5) * 2.0;
    if (r > 1.0) discard;
    // Soft glowing orb (not a hard mesh texel).
    float core = exp(-r * r * 18.0);
    float halo = exp(-r * r * 3.6) * 0.45;
    float alpha = (core + halo) * (1.0 - smoothstep(0.6, 1.0, r)) * vLight * uOpacity;
    vec3 color = mix(uColor, uGold, smoothstep(0.13, 0.75, vGold));
    gl_FragColor = vec4(color + vec3(core * 0.18), alpha);
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

function geometryFromOrbs(orbs: ParticleOrb[], material: THREE.ShaderMaterial): THREE.Points {
  const count = orbs.length
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
  writeSlot(orbs, bPos, bSize, bGold, bLight, bFlow)
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

export type MorphablePresenceSystem = {
  group: THREE.Group
  bust: THREE.Group
  figure: THREE.Points
  field: THREE.Points | null
  currentShapeId: PresenceShapeId
  morphTo: (shapeId: PresenceShapeId, opts?: { duration?: number; immediate?: boolean }) => void
  tick: (delta: number) => void
  dispose: () => void
}

export function createMorphablePresenceSystem(
  density: number,
  material: THREE.ShaderMaterial,
  initialShapeId?: PresenceShapeId,
): MorphablePresenceSystem {
  const figureBudget = Math.round(28000 * density)
  const fieldBudget = Math.round(18000 * density)
  let shape = resolvePresenceShape(initialShapeId)
  const figureOrbs = resampleOrbs(shape.buildFigure(density), figureBudget)
  const figure = geometryFromOrbs(figureOrbs, material)
  let field: THREE.Points | null = null
  if (shape.buildField) {
    field = geometryFromOrbs(resampleOrbs(shape.buildField(density), fieldBudget), material)
  }

  const group = new THREE.Group()
  const bust = new THREE.Group()
  bust.add(figure)
  group.add(bust)
  if (field) group.add(field)

  let morph = 1
  let morphDuration = 0
  let morphElapsed = 0
  let morphing = false
  const uniforms = material.uniforms
  uniforms.uMorph = uniforms.uMorph ?? { value: 1 }
  uniforms.uMorph.value = 1

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

  const writeB = (points: THREE.Points, orbs: ParticleOrb[]) => {
    const geo = points.geometry
    const bPos = geo.getAttribute("bPos") as THREE.BufferAttribute
    const bSize = geo.getAttribute("bSize") as THREE.BufferAttribute
    const bGold = geo.getAttribute("bGold") as THREE.BufferAttribute
    const bLight = geo.getAttribute("bLight") as THREE.BufferAttribute
    const bFlow = geo.getAttribute("bFlow") as THREE.BufferAttribute
    for (let i = 0; i < orbs.length; i++) {
      const orb = orbs[i]
      const i3 = i * 3
      bPos.array[i3] = orb.x
      bPos.array[i3 + 1] = orb.y
      bPos.array[i3 + 2] = orb.z
      bSize.array[i] = orb.size
      bGold.array[i] = orb.gold
      bLight.array[i] = orb.light
      bFlow.array[i] = orb.flow
    }
    bPos.needsUpdate = true
    bSize.needsUpdate = true
    bGold.needsUpdate = true
    bLight.needsUpdate = true
    bFlow.needsUpdate = true
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
    currentShapeId: shape.id,
    morphTo(shapeId, opts) {
      if (shapeId === system.currentShapeId && !morphing) return
      const next = resolvePresenceShape(shapeId)
      copyCurrentToA(figure)
      writeB(figure, resampleOrbs(next.buildFigure(density), figureBudget))

      // Field swaps immediately (environment of the target shape).
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
      applyFraming(bust)
      if (opts?.immediate || (opts?.duration ?? 1.15) <= 0) {
        morph = 1
        morphing = false
        uniforms.uMorph.value = 1
        // Snap A/B to the target so subsequent morphs start clean.
        copyCurrentToA(figure)
        writeB(figure, resampleOrbs(next.buildFigure(density), figureBudget))
        return
      }
      morph = 0
      morphElapsed = 0
      morphDuration = opts?.duration ?? 1.15
      morphing = true
      uniforms.uMorph.value = 0
    },
    tick(delta) {
      if (!morphing) return
      morphElapsed += delta
      morph = Math.min(1, morphElapsed / Math.max(0.0001, morphDuration))
      uniforms.uMorph.value = morph
      if (morph >= 1) morphing = false
    },
    dispose() {
      figure.geometry.dispose()
      field?.geometry.dispose()
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
