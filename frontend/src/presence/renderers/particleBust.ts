import * as THREE from "three"

// Left-facing particle portrait matched to the owner reference reel:
// cyan silhouette contours, orange brain cluster, bright chest core,
// rightward dissolve trail, and cyan/gold mountain ridges.
export function createParticleBust(density: number, material: THREE.ShaderMaterial) {
  let seed = 5103
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  const gauss = (v: number, s: number) => Math.exp(-(v * v) / (s * s))

  type Emit = (
    x: number, y: number, z: number,
    gold: number, light: number, flow?: number, size?: number,
  ) => void

  function cloud(build: (emit: Emit) => void) {
    const position: number[] = []
    const sizes: number[] = []
    const golds: number[] = []
    const lights: number[] = []
    const flows: number[] = []
    const seeds: number[] = []
    build((x, y, z, gold, light, flow = 0, size = 1.55 + random() * 0.75) => {
      position.push(x, y, z)
      sizes.push(size / Math.sqrt(density))
      golds.push(gold)
      lights.push(light)
      flows.push(flow)
      seeds.push(random())
    })
    const geometry = new THREE.BufferGeometry()
    for (const [name, array, stride] of [
      ["position", position, 3], ["aSize", sizes, 1], ["aGold", golds, 1],
      ["aLight", lights, 1], ["aFlow", flows, 1], ["aSeed", seeds, 1],
    ] as const) {
      geometry.setAttribute(name, new THREE.Float32BufferAttribute(array, stride))
    }
    return new THREE.Points(geometry, material)
  }

  // Face silhouette facing screen-left (−X). Dense front edge, softer skull.
  const faceProfile = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.22, 1.68, 0.02),
    new THREE.Vector3(-0.08, 1.74, 0.04),
    new THREE.Vector3(-0.38, 1.58, 0.08),
    new THREE.Vector3(-0.48, 1.36, 0.12),
    new THREE.Vector3(-0.52, 1.14, 0.14),
    new THREE.Vector3(-0.68, 0.98, 0.16),
    new THREE.Vector3(-0.54, 0.86, 0.14),
    new THREE.Vector3(-0.58, 0.74, 0.12),
    new THREE.Vector3(-0.50, 0.58, 0.10),
    new THREE.Vector3(-0.34, 0.42, 0.08),
    new THREE.Vector3(-0.22, 0.18, 0.06),
  ], false, "catmullrom", 0.25)

  const skullBack = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.22, 1.68, 0.02),
    new THREE.Vector3(0.42, 1.52, -0.04),
    new THREE.Vector3(0.52, 1.22, -0.08),
    new THREE.Vector3(0.48, 0.88, -0.06),
    new THREE.Vector3(0.34, 0.55, -0.02),
    new THREE.Vector3(0.18, 0.28, 0.02),
  ], false, "catmullrom", 0.25)

  const head = cloud((emit) => {
    const outlineSamples = Math.round(520 * density)
    for (let i = 0; i < outlineSamples; i++) {
      const t = i / outlineSamples
      const p = faceProfile.getPoint(t)
      const depth = (random() - 0.5) * 0.08
      // Bright cyan rim along forehead → nose → chin.
      emit(p.x + (random() - 0.5) * 0.01, p.y + (random() - 0.5) * 0.01, p.z + depth,
        0, 1.8 + random() * 1.4, 0, 1.7 + random() * 0.6)
      if (random() < 0.45) {
        emit(p.x + 0.03 + random() * 0.04, p.y, p.z + depth * 0.6,
          0, 0.55 + random() * 0.4, 0, 1.2)
      }
    }

    // Topographic streamlines fill the head volume between face and skull.
    const bands = Math.round(34 * density)
    const along = Math.round(90 * density)
    for (let band = 0; band < bands; band++) {
      const u = band / bands
      for (let i = 0; i < along; i++) {
        const t = i / along
        const front = faceProfile.getPoint(t)
        const back = skullBack.getPoint(t)
        const mix = 0.12 + u * 0.78
        const x = THREE.MathUtils.lerp(front.x, back.x, mix)
        const y = THREE.MathUtils.lerp(front.y, back.y, mix) + Math.sin(t * 9 + u * 4) * 0.008
        const z = THREE.MathUtils.lerp(front.z, back.z, mix) + (u - 0.5) * 0.22
        const edge = gauss(mix - 0.18, 0.14) + gauss(mix - 0.85, 0.12)
        const faceGold = gauss(t - 0.42, 0.18) * gauss(mix - 0.28, 0.2) * 0.35
        if (random() < 0.08 && mix > 0.25 && mix < 0.75) continue
        emit(x, y, z, faceGold, 0.22 + edge * 1.1 + (1 - mix) * 0.55, 0.05, 1.25 + random() * 0.55)
      }
    }

    // Dense orange/gold brain cluster — secondary focal point inside the cranium.
    for (let i = 0; i < 2800 * density; i++) {
      const a = random() * Math.PI * 2
      const b = Math.acos(random() * 2 - 1)
      const r = Math.pow(random(), 0.55) * 0.22
      const x = 0.02 + Math.sin(b) * Math.cos(a) * r * 1.05
      const y = 1.12 + Math.sin(b) * Math.sin(a) * r * 0.9
      const z = 0.02 + Math.cos(b) * r * 0.85
      const core = 1 - r / 0.22
      emit(x, y, z, 1, 0.9 + core * 1.8, 0, 1.35 + random() * 0.7)
    }
    emit(0.02, 1.12, 0.02, 1, 0.35, 0, 95)

    // Soft halo + asymmetric dissolve trail drifting screen-right (+X).
    for (let i = 0; i < 4200 * density; i++) {
      const t = random()
      const back = skullBack.getPoint(t)
      const trail = Math.pow(random(), 1.35) * 2.4
      const lift = (random() - 0.35) * 0.55
      const y = back.y + lift + Math.sin(trail * 2.2) * 0.12
      const x = back.x + 0.08 + trail
      const z = back.z - 0.05 - random() * 0.35
      const fade = Math.exp(-trail * 0.55) * (0.2 + random() * 0.55)
      emit(x, y, z, 0, fade, 0.35 + random() * 0.25, 0.95 + random() * 0.9)
    }
  })

  const body = cloud((emit) => {
    const neck = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-0.22, 0.18, 0.06),
      new THREE.Vector3(-0.14, -0.05, 0.08),
      new THREE.Vector3(-0.06, -0.32, 0.10),
      new THREE.Vector3(0.02, -0.62, 0.12),
      new THREE.Vector3(0.06, -0.95, 0.14),
    ], false, "catmullrom", 0.2)

    const shoulder = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.02, -0.55, 0.10),
      new THREE.Vector3(0.35, -0.68, 0.06),
      new THREE.Vector3(0.78, -0.82, 0.0),
      new THREE.Vector3(1.18, -1.05, -0.06),
      new THREE.Vector3(1.42, -1.38, -0.12),
    ], false, "catmullrom", 0.25)

    // Nested neck / chest contour strokes.
    for (let contour = 0; contour < 9 * density; contour++) {
      const inset = contour / density * 0.012
      for (let i = 0; i < 220 * density; i++) {
        const t = i / (220 * density)
        const p = neck.getPoint(t)
        emit(p.x + inset * 0.4, p.y - inset * 0.3, p.z + inset,
          0, (1.1 - contour / (12 * density)) * (0.7 + random() * 0.5), 0, 1.35)
      }
    }

    for (const side of [-1, 1]) {
      // Shoulder arcs; front (−X) denser like the reference bust.
      for (let contour = 0; contour < 6 * density; contour++) {
        for (let i = 0; i < 260 * density; i++) {
          const t = i / (260 * density)
          const p = shoulder.getPoint(t)
          const x = side === -1
            ? -0.12 - t * 0.55 - contour * 0.01
            : p.x + contour * 0.012
          const y = p.y - (side === -1 ? t * 0.08 : 0) - contour * 0.01
          const z = p.z + (side === -1 ? 0.04 : 0) + contour * 0.008
          const light = side === -1
            ? 1.4 * (1 - t * 0.35)
            : 0.55 * (1 - t * 0.5) * (1 - contour / (8 * density))
          if (side === 1 && random() < 0.2) continue
          emit(x, y, z, 0, light, side === 1 ? 0.2 : 0, 1.3 + random() * 0.4)
        }
      }

      // Amber neural filaments: chest core → neck → brain.
      for (let branch = 0; branch < 8; branch++) {
        for (let i = 0; i < 200 * density; i++) {
          const t = i / (200 * density)
          const y = -0.95 + t * 2.05
          const sway = Math.sin(t * 14 + branch) * 0.028 * Math.sin(t * Math.PI)
          const x = side * (0.02 + t * (0.04 + branch * 0.018) + sway) - 0.04 * (1 - t)
          const z = 0.12 + Math.sin(t * Math.PI) * 0.06
          emit(x, y, z, 0.95, 0.55 + Math.sin(t * Math.PI) * 1.1, 0, 1.45)
        }
      }
    }

    // Deltoid / upper-chest surface fill.
    for (let row = 0; row < 28 * density; row++) {
      const t = row / (28 * density)
      for (let col = 0; col < 120 * density; col++) {
        const u = col / (120 * density)
        const x = THREE.MathUtils.lerp(-0.55, 1.35, u)
        const shoulderDrop = Math.pow(Math.max(0, Math.abs(x) - 0.15) / 1.2, 1.6) * 0.55
        const y = -0.45 - t * 1.05 - shoulderDrop
        const frontBias = gauss(x + 0.15, 0.55)
        if (y < -1.55 || (x > 0.9 && random() < 0.35)) continue
        const z = 0.05 + (0.5 - t) * 0.12 + (random() - 0.5) * 0.04
        emit(x, y, z, 0, (0.18 + frontBias * 0.55) * (1 - t * 0.55), 0.08, 1.2)
      }
    }

    // Bright cyan-white chest core.
    for (let i = 0; i < 320 * density; i++) {
      const a = random() * Math.PI * 2
      const r = Math.pow(random(), 2) * 0.07
      emit(Math.cos(a) * r - 0.02, -0.98 + Math.sin(a) * r, 0.16 + random() * 0.04,
        0.05, 2.2, 2, 2.2 + random() * 2.5)
    }
    emit(-0.02, -0.98, 0.18, 0, 0.7, 2, 78)
  })

  const field = cloud((emit) => {
    // Ultrawide particle mountain range with warm ridge highlights (ref3).
    const peaks = [
      { x: -4.2, h: 1.15, w: 1.1 },
      { x: -2.6, h: 1.55, w: 0.95 },
      { x: -1.3, h: 1.05, w: 0.8 },
      { x: 1.6, h: 1.25, w: 1.0 },
      { x: 3.1, h: 1.7, w: 1.15 },
      { x: 4.6, h: 1.2, w: 0.9 },
    ]
    for (let i = 0; i < 9000 * density; i++) {
      const x = (random() - 0.5) * 11
      let height = 0.15 + random() * 0.12
      let ridge = 0
      for (const peak of peaks) {
        const d = Math.abs(x - peak.x) / peak.w
        const contribution = peak.h * Math.exp(-d * d * 1.8)
        height = Math.max(height, contribution)
        ridge = Math.max(ridge, contribution * gauss(d, 0.22))
      }
      const jagged = Math.sin(x * 6.5) * 0.05 + Math.sin(x * 17.0) * 0.025
      const y = -1.55 + height * random() + jagged * random()
      const z = -1.35 - random() * 1.4
      const nearRidge = ridge > height * 0.72
      const gold = nearRidge && random() < 0.55 ? 0.92 : 0
      const light = nearRidge ? 1.8 + random() * 2.2 : 0.18 + random() * 0.45
      emit(x, y, z, gold, light, 1, nearRidge ? 1.7 : 1.05 + random() * 0.5)
    }

    // Loose energy wisps continuing the dissolve language into the void.
    for (const side of [-1, 1]) {
      for (let strand = 0; strand < 28 * density; strand++) {
        const band = strand / (28 * density)
        for (let i = 0; i < 120 * density; i++) {
          const t = i / (120 * density)
          const x = side * (1.1 + t * 5.2)
          const y = -0.4 + t * 0.7 + Math.sin(t * 10 + band * 3) * 0.22 - band * 0.9
          const fade = Math.sin(t * Math.PI) * (0.25 + random() * 0.5)
          if (random() > 0.55) continue
          emit(x, y, -0.9 - band * 0.5, strand % 13 === 0 ? 0.9 : 0, fade, 1, 1.1)
        }
      }
    }

    // Quiet interrupted arcs behind the bust (TEM HUD feel in particle form).
    for (let ring = 0; ring < 4; ring++) {
      const radius = 1.05 + ring * 0.18
      for (let i = 0; i < 360 * density; i++) {
        const a = i / (360 * density) * Math.PI * 2
        if (Math.sin(a * 3 + ring) > 0.88) continue
        const y = 0.7 + Math.cos(a) * radius
        if (y < -0.2) continue
        emit(Math.sin(a) * radius * 0.55, y, -1.7, 0, 0.1 - ring * 0.015, 2, 1.05)
      }
    }
  })

  return { head, body, field }
}

export const particleVertexShader = `
  attribute float aSize;
  attribute float aGold;
  attribute float aLight;
  attribute float aFlow;
  attribute float aSeed;
  uniform float uTime;
  uniform float uMotion;
  uniform float uActivity;
  uniform float uSpeech;
  uniform float uPixelScale;
  uniform float uAssemble;
  varying float vGold;
  varying float vLight;
  void main() {
    vec3 p = position;
    float t = uTime;
    if (aFlow > 0.8 && aFlow < 1.5) {
      // Mountain / field drift — slow breathing ridges.
      p.y += (sin(p.x * 1.8 - t * 0.35) * 0.05 + sin(p.x * 4.2 + t * 0.22) * 0.02) * uMotion;
      p.z += sin(p.x * 1.2 + t * 0.18) * 0.04 * uMotion;
    } else if (aFlow < 0.8) {
      float loose = step(0.15, aFlow);
      p.x += sin(t * 0.45 + aSeed * 42.0) * 0.04 * loose * uMotion;
      p.y += cos(t * 0.38 + aSeed * 31.0) * 0.05 * loose * uMotion;
      // Rightward dissolve intensifies with activity.
      float sweep = pow(max(0.0, sin(t * 0.35 + p.y * 0.7)), 5.0);
      p.x += loose * (0.06 + uActivity * 0.18) * sweep * uMotion * (0.4 + aSeed);
      float dissolve = smoothstep(0.55, 1.0, uActivity) * smoothstep(0.6, 0.95, aSeed) * uMotion;
      p.x += dissolve * (0.4 + sin(t * 0.65 + aSeed * 8.0) * 0.18);
      p.y += dissolve * sin(t * 0.5 + aSeed * 13.0) * 0.28;
      p.z += sin(p.y * 6.5 - t * 1.2) * (0.004 + uSpeech * 0.02) * uMotion;
      vec3 scattered = vec3(
        0.4 + sin(aSeed * 75.0) * (0.5 + aSeed * 1.4),
        -0.2 + aSeed * 1.5,
        cos(aSeed * 43.0) * 0.5
      );
      float assemble = smoothstep(0.0, 1.0, clamp(uAssemble * 1.5 - aSeed * 0.5, 0.0, 1.0));
      p = mix(scattered, p, assemble);
    } else {
      // Chest core pulse.
      p *= 1.0 + uSpeech * 0.04 * sin(t * 10.0);
      p.xy *= 1.0 + sin(t * (2.0 + uActivity)) * 0.012 * uMotion;
    }
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * uPixelScale * 7.0 / -mv.z, 0.8, 120.0);
    vGold = aGold;
    float shimmer = 0.88 + 0.12 * sin(t * 1.15 + aSeed * 60.0);
    float wave = pow(max(0.0, sin(p.y * 3.2 - t * 1.0)), 9.0) * uActivity;
    vLight = aLight * (mix(1.0, shimmer, uMotion) + wave * uMotion * 0.22);
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
    float core = exp(-r * r * 18.0);
    float halo = exp(-r * r * 3.8) * 0.42;
    float alpha = (core + halo) * (1.0 - smoothstep(0.62, 1.0, r)) * vLight * uOpacity;
    vec3 color = mix(uColor, uGold, smoothstep(0.12, 0.78, vGold));
    gl_FragColor = vec4(color + vec3(core * 0.16), alpha);
  }
`
