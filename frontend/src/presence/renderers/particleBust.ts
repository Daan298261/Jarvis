import * as THREE from "three"

// Original contour portrait, reconstructed from the owner's APEX humanoid reel.
// Skin contours, shoulder arcs, nerve filaments and loose particles are separate structures.
export function createParticleBust(density: number, material: THREE.ShaderMaterial) {
  let seed = 5103
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
  const gauss = (v: number, s: number) => Math.exp(-v * v / (s * s))
  type Emit = (x: number, y: number, z: number, gold: number, light: number, flow?: number, size?: number) => void
  function cloud(build: (emit: Emit) => void) {
    const position: number[] = [], sizes: number[] = [], golds: number[] = [], lights: number[] = [], flows: number[] = [], seeds: number[] = []
    build((x, y, z, gold, light, flow = 0, size = 1.6 + random() * 0.8) => {
      position.push(x, y, z); sizes.push(size / Math.sqrt(density)); golds.push(gold)
      lights.push(light); flows.push(flow); seeds.push(random())
    })
    const geometry = new THREE.BufferGeometry()
    for (const [name, array, stride] of [
      ["position", position, 3], ["aSize", sizes, 1], ["aGold", golds, 1],
      ["aLight", lights, 1], ["aFlow", flows, 1], ["aSeed", seeds, 1],
    ] as const) geometry.setAttribute(name, new THREE.Float32BufferAttribute(array, stride))
    return new THREE.Points(geometry, material)
  }
  const profile = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.08, 0.07, 0.19), new THREE.Vector3(0.27, 0.16, 0.27),
    new THREE.Vector3(0.44, 0.4, 0.35), new THREE.Vector3(0.51, 0.72, 0.40),
    new THREE.Vector3(0.52, 1.10, 0.40), new THREE.Vector3(0.44, 1.39, 0.35),
    new THREE.Vector3(0.27, 1.58, 0.24), new THREE.Vector3(0, 1.66, 0),
  ], false, "catmullrom", 0.3)
  const head = cloud((emit) => {
    const rows = Math.round(64 * density), columns = Math.round(180 * density)
    for (let row = 0; row < rows; row++) {
      const ring = profile.getPoint(row / rows)
      for (let col = 0; col < columns; col++) {
        const angle = (col + random() * 0.65) / columns * Math.PI * 2
        const front = Math.cos(angle), x = Math.sin(angle) * ring.x
        // Slightly flattened face with cheek, brow and nose relief, not an ellipsoid.
        const nose = gauss(x, 0.12) * gauss(ring.y - 0.65, 0.26) * 0.075
        const brow = gauss(ring.y - 1.0, 0.06) * gauss(x, 0.42) * 0.025
        const z = front * ring.z + Math.max(0, front) * (nose + brow)
        const mask = gauss(x, 0.38) * gauss(ring.y - 0.61, 0.39) * THREE.MathUtils.smoothstep(front, 0.3, 0.85)
        const rim = Math.pow(Math.abs(Math.sin(angle)), 14)
        const light = front < 0 ? 0.06 : 0.25 + rim * 4.5 + mask * 3.6
        // Fine broken contour strokes avoid a mechanical latitude/longitude grid.
        if (random() < 0.05 && rim < 0.7) continue
        emit(x, ring.y + Math.sin(angle * 3 + ring.y * 5) * 0.004, z,
          mask, light * (0.65 + random() * 0.55), 0, 1.4 + random() * 0.65)
      }
    }
    // Warm face bands are laid onto the facial surface, with feathered edges.
    for (let row = 0; row < 27 * density; row++) {
      const v = row / (27 * density) * 2 - 1
      const width = Math.sqrt(1 - v * v) * 0.34
      for (let i = 0; i < 150 * density; i++) {
        const u = i / (150 * density) * 2 - 1
        emit(u * width, 0.62 + v * 0.39 + Math.cos(u * Math.PI) * 0.013,
          0.47 - Math.abs(u) * 0.035, 1, (1 - Math.pow(Math.abs(u), 4)) * (1 - v * v) * 1.8,
          0, 1.4 + random() * 0.35)
      }
    }
    // Dense orange/gold brain cluster deeper in the cranium (ref focal).
    for (let i = 0; i < 2600 * density; i++) {
      const a = random() * Math.PI * 2
      const b = Math.acos(random() * 2 - 1)
      const r = Math.pow(random(), 0.5) * 0.24
      emit(
        Math.sin(b) * Math.cos(a) * r * 0.9,
        1.05 + Math.sin(b) * Math.sin(a) * r * 0.85,
        0.12 + Math.cos(b) * r * 0.7,
        1, 1.2 + (1 - r / 0.24) * 1.8, 0, 1.4 + random() * 0.7,
      )
    }
    emit(0, 0.62, 0.43, 1, 0.24, 0, 115)
    emit(0, 1.05, 0.12, 1, 0.35, 0, 90)
    // Sparse halo with a trailing, asymmetric edge (dissolve toward +X).
    for (let i = 0; i < 4200 * density; i++) {
      const ring = profile.getPoint(random()), angle = random() * Math.PI * 2
      const spread = Math.pow(random(), 2) * 0.30
      const trail = Math.pow(random(), 1.4) * 1.8
      const x = Math.sin(angle) * (ring.x + spread) + (angle > 0 ? trail * 0.55 : 0)
      emit(x, ring.y + spread * 0.9 + (random() - 0.5) * trail * 0.15,
        Math.cos(angle) * (ring.z + spread) - trail * 0.1,
        0, (0.15 + random() * 0.48) * Math.exp(-trail * 0.35), 0.4, 1.0 + random())
    }
  })
  const body = cloud((emit) => {
    const outline = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.28, 0.16, -0.02), new THREE.Vector3(0.24, -0.10, 0.04),
      new THREE.Vector3(0.31, -0.37, 0.09), new THREE.Vector3(0.62, -0.54, 0.05),
      new THREE.Vector3(1.10, -0.65, -0.02), new THREE.Vector3(1.43, -0.89, -0.08),
      new THREE.Vector3(1.55, -1.27, -0.15),
    ])
    for (const side of [-1, 1]) {
      // Nested outlines connect jaw, neck and shoulders as one organic surface.
      for (let contour = 0; contour < 7 * density; contour++) {
        for (let i = 0; i < 250 * density; i++) {
          const t = i / (250 * density), p = outline.getPoint(t)
          const inset = contour / density * 0.014
          emit(side * (p.x - inset), p.y - inset * t * 0.9, p.z + inset,
            0, (1 - contour / (9 * density)) * 2.0, 0, 1.4)
        }
      }
      // Rounded deltoid/chest contour arches, clipped into the outer shoulder silhouette.
      for (let row = 0; row < 20 * density; row++) {
        const r = 0.17 + row / density * 0.047
        for (let col = 0; col < 180 * density; col++) {
          const angle = (col + random() * 0.8) / (180 * density) * Math.PI
          const x = side * (0.83 + Math.cos(angle) * r)
          const y = -1.54 + Math.sin(angle) * r * 0.96
          const ax = Math.abs(x)
          const top = -0.29 - 0.32 * (1 - Math.exp(-Math.pow(Math.max(0, ax - 0.25) / 0.25, 2))) - 0.32 * Math.pow(ax / 1.6, 6)
          if (ax < 0.10 || ax > 1.53 || y > top) continue
          const fade = THREE.MathUtils.smoothstep(y, -1.54, -1.24)
          emit(x, y, 0.18 + Math.sin(angle) * 0.2, 0,
            fade * (0.3 + random() * 0.35), 0, 1.35)
        }
      }
      // Slender branching amber filaments connect the face to the sternum.
      for (let branch = 0; branch < 7; branch++) {
        for (let i = 0; i < 180 * density; i++) {
          const t = i / (180 * density)
          const y = -1.27 + t * 1.36
          const x = side * (0.015 + t * (0.035 + branch * 0.026) + Math.sin(t * 14 + branch) * 0.032 * Math.sin(t * Math.PI))
          emit(x, y, 0.29, 0.92, 0.65 + Math.sin(t * Math.PI) * 0.8, 0, 1.5)
        }
      }
    }
    // Transverse neck contours bow gently, rather than forming a bright cylinder.
    for (let row = 0; row < 27 * density; row++) {
      const t = row / (27 * density)
      for (let i = 0; i < 80 * density; i++) {
        const x = (i / (80 * density) * 2 - 1) * (0.23 + t * 0.09)
        const y = 0.10 - t * 0.59 - (1 - Math.pow(x / (0.23 + t * 0.09), 2)) * 0.07
        emit(x, y, 0.19, 0, 0.17 + random() * 0.18, 0, 1.25)
      }
    }
    for (let i = 0; i < 320 * density; i++) {
      const a = random() * Math.PI * 2, r = Math.pow(random(), 2) * 0.07
      emit(Math.cos(a) * r, -1.28 + Math.sin(a) * r, 0.40, 0.05, 2.3, 2, 2.4 + random() * 2.2)
    }
    // The emitter's soft halo is a single large point, not a solid sphere.
    emit(0, -1.28, 0.4, 0, 0.7, 2, 78)
  })
  const field = cloud((emit) => {
    // Side energy strands (ultrawide dissolve language).
    for (const side of [-1, 1]) {
      for (let strand = 0; strand < 48 * density; strand++) {
        const band = strand / (48 * density)
        for (let i = 0; i < 200 * density; i++) {
          const t = i / (200 * density)
          const x = side * (0.95 + t * 6.4)
          const crest = Math.sin(t * 12 + side * 0.4) * 0.28
            + Math.sin(t * 27 - band * 2) * 0.11 + Math.sin(t * 51 + band * 3) * 0.04
          const y = -0.89 + t * 0.96 + crest - band * (0.28 + Math.sin(t * Math.PI) * 1.3)
          const gold = strand % 17 < 2
          const bright = gold || strand % 11 === 0
          const fade = Math.sin(t * Math.PI) * (0.28 + random() * 0.65) * (bright ? 5.5 : 0.85)
          if (bright || random() > 0.25) emit(x, y, -0.75 - band * 0.7, gold ? 0.94 : 0, fade, 1, (bright ? 1.65 : 1.1) + random() * 0.8)
          if (random() < 0.22) emit(x, y + (random() - 0.5) * 0.22, -0.7,
            0, fade * 0.55, 1, 0.9 + random())
        }
      }
    }
    // Particle mountain range with warm ridge highlights (ref3).
    const peaks = [
      { x: -3.8, h: 0.85, w: 1.1 }, { x: -2.2, h: 1.2, w: 0.95 },
      { x: 2.0, h: 0.95, w: 1.0 }, { x: 3.6, h: 1.35, w: 1.15 }, { x: 5.0, h: 0.9, w: 0.9 },
    ]
    for (let i = 0; i < 5000 * density; i++) {
      const x = (random() - 0.5) * 11
      let height = 0.08, ridge = 0
      for (const peak of peaks) {
        const d = Math.abs(x - peak.x) / peak.w
        const contribution = peak.h * Math.exp(-d * d * 1.85)
        height = Math.max(height, contribution)
        ridge = Math.max(ridge, contribution * gauss(d, 0.22))
      }
      const y = -1.7 + height * random() + Math.sin(x * 7) * 0.03 * random()
      const nearRidge = ridge > height * 0.72
      emit(x, y, -1.55 - random() * 1.2,
        nearRidge && random() < 0.55 ? 0.94 : 0,
        nearRidge ? 1.8 + random() * 2 : 0.12 + random() * 0.35,
        1, nearRidge ? 1.6 : 1.0)
    }
    // Quiet interrupted concentric arcs behind the portrait, as in the reel.
    for (let ring = 0; ring < 5; ring++) {
      const radius = 0.98 + ring * 0.16
      for (let i = 0; i < 430 * density; i++) {
        const a = i / (430 * density) * Math.PI * 2
        if (Math.sin(a * 3 + ring * 0.7) > 0.91) continue
        const y = 0.64 + Math.cos(a) * radius
        if (y < -0.5) continue
        emit(Math.sin(a) * radius, y, -1.5, 0, 0.12 - ring * 0.014, 2, 1.15)
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
      p.y += (sin(p.x * 2.8 - t * 0.6) * 0.14 + sin(p.x * 6.5 + t * 0.45) * 0.06) * uMotion;
      p.z += sin(p.x * 1.8 + t * 0.25) * 0.1 * uMotion;
    } else if (aFlow < 0.8) {
      float loose = step(0.2, aFlow);
      p.x += sin(t * 0.55 + aSeed * 42.0) * 0.055 * loose * uMotion;
      p.y += cos(t * 0.45 + aSeed * 31.0) * 0.06 * loose * uMotion;
      float sweep = pow(max(0.0, sin(t * 0.4 + p.y * 0.8)), 5.0);
      float drift = loose * (0.08 + uActivity * 0.2) * sweep * uMotion;
      p.x += drift * (0.5 + aSeed) * smoothstep(-0.3, 0.5, p.x);
      float dissolve = smoothstep(0.65, 1.0, uActivity) * smoothstep(0.65, 0.95, aSeed) * uMotion;
      p.x += dissolve * (0.35 + sin(t * 0.7 + aSeed * 8.0) * 0.2);
      p.y += dissolve * sin(t * 0.55 + aSeed * 13.0) * 0.35;
      p.z += sin(p.y * 7.0 - t * 1.3) * (0.004 + uSpeech * 0.025) * uMotion;
      vec3 scattered = vec3(sin(aSeed * 75.0) * (0.4 + aSeed * 1.2),
        -1.28 + aSeed * 1.4, cos(aSeed * 43.0) * 0.6);
      float assemble = smoothstep(0.0, 1.0, clamp(uAssemble * 1.5 - aSeed * 0.5, 0.0, 1.0));
      p = mix(scattered, p, assemble);
    }
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * uPixelScale * 7.1 / -mv.z, 0.8, 120.0);
    vGold = aGold;
    float shimmer = 0.87 + 0.13 * sin(t * 1.2 + aSeed * 60.0);
    float wave = pow(max(0.0, sin(p.y * 3.5 - t * 1.1)), 8.0) * uActivity;
    vLight = aLight * (mix(1.0, shimmer, uMotion) + wave * uMotion * 0.24);
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
    float alpha = exp(-r * r * 4.0) * (1.0 - smoothstep(0.65, 1.0, r));
    vec3 color = mix(uColor, uGold, smoothstep(0.13, 0.75, vGold));
    gl_FragColor = vec4(color * vLight, alpha * uOpacity);
  }
`
