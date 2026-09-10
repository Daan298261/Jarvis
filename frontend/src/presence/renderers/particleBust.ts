import * as THREE from "three"

// Original point-sampled portrait. All surfaces and light fields are luminous dots.
export function createParticleBust(density: number, material: THREE.ShaderMaterial) {
  let seed = 51
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
  const gaussian = (value: number, width: number) => Math.exp(-(value * value) / (width * width))
  function cloud(build: (point: (x: number, y: number, z: number, gold: number, brightness: number, flow?: number) => void) => void) {
    const positions: number[] = [], sizes: number[] = [], golds: number[] = [], lights: number[] = [], flows: number[] = []
    build((x, y, z, gold, brightness, flow = 0) => {
      positions.push(x, y, z)
      sizes.push((random() > 0.985 ? 8 : 3.2 + random() * 2.0) / Math.sqrt(density))
      golds.push(gold); lights.push(brightness); flows.push(flow)
    })
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3))
    geometry.setAttribute("aSize", new THREE.Float32BufferAttribute(sizes, 1))
    geometry.setAttribute("aGold", new THREE.Float32BufferAttribute(golds, 1))
    geometry.setAttribute("aLight", new THREE.Float32BufferAttribute(lights, 1))
    geometry.setAttribute("aFlow", new THREE.Float32BufferAttribute(flows, 1))
    return new THREE.Points(geometry, material)
  }
  const head = cloud((point) => {
    const rows = Math.round(88 * density), columns = Math.round(100 * density)
    for (let row = 1; row < rows; row++) {
      const v = row / rows * 2 - 1
      const y = 1 + v * 0.98
      const radius = Math.sqrt(1 - v * v)
      const jaw = 0.8 + 0.2 * THREE.MathUtils.smoothstep(v, -0.75, 0.1)
      for (let col = 0; col < columns; col++) {
        const angle = (col + (row % 2) * 0.5) / columns * Math.PI * 2
        const x = Math.sin(angle) * 0.64 * radius * jaw
        const z = Math.cos(angle) * 0.53 * radius
        const front = THREE.MathUtils.smoothstep(Math.cos(angle), 0.25, 0.85)
        const mask = gaussian(x, 0.4) * gaussian(y - 0.76, 0.43) * front
        const edge = Math.pow(Math.abs(Math.sin(angle)), 10)
        point(x + (random() - 0.5) * 0.007, y, z, mask,
          (0.25 + edge * 1.45 + front * 0.5 + mask * 2.0) * (0.8 + random() * 0.4))
      }
    }
    // Warm inner face core glows through the cyan surface contours.
    for (let i = 0; i < 2400 * density; i++) {
      const angle = random() * Math.PI * 2, r = Math.sqrt(random())
      point(Math.cos(angle) * r * 0.38, 0.76 + Math.sin(angle) * r * 0.43,
        0.49 + random() * 0.06, 1, Math.pow(1 - r * r, 1.5) * 1.3)
    }
    for (let i = 0; i < 1100 * density; i++) {
      const angle = random() * Math.PI * 2, v = random() * 2 - 1
      const r = Math.sqrt(1 - v * v) * (1.04 + random() * 0.13)
      point(Math.sin(angle) * 0.66 * r, 1 + v * 1.05, Math.cos(angle) * 0.55 * r,
        0, 0.12 + random() * 0.32, 0.15)
    }
  })
  const body = cloud((point) => {
    // Sloping shoulder contours flow continuously into a narrow neck.
    const rows = Math.round(66 * density), columns = Math.round(160 * density)
    for (let row = 0; row < rows; row++) {
      const t = row / (rows - 1)
      for (let col = 0; col < columns; col++) {
        const angle = col / columns * Math.PI * 2
        const s = Math.sin(angle), c = Math.cos(angle)
        const width = 0.2 + 1.52 * THREE.MathUtils.smoothstep(t, 0.2, 0.62)
          - 0.13 * THREE.MathUtils.smoothstep(t, 0.7, 1)
        const x = s * width
        const shoulder = THREE.MathUtils.smoothstep(t, 0.3, 0.7) * Math.pow(Math.abs(s), 0.65)
        const y = 0.03 - t * 1.62 - shoulder * 0.15
        const z = c * (0.23 + t * 0.4)
        const gold = gaussian(x - Math.sin(t * 12) * 0.08, 0.024) * Math.max(0, c) * 0.9
        const fade = 1 - THREE.MathUtils.smoothstep(t, 0.78, 1) * 0.88
        const neckLight = 0.45 + THREE.MathUtils.smoothstep(t, 0.16, 0.4) * 0.55
        point(x, y, z, gold, (0.25 + Math.max(0, c) * 0.85 + gold * 0.6) * fade * neckLight)
      }
    }
    for (let i = 0; i < 350 * density; i++) {
      const a = random() * Math.PI * 2, r = Math.pow(random(), 2) * 0.11
      point(Math.cos(a) * r, -1.2 + Math.sin(a) * r, 0.68, 0.05, 1.3)
    }
  })
  const field = cloud((point) => {
    const strands = Math.round(28 * density), samples = Math.round(140 * density)
    for (const side of [-1, 1]) {
      for (let strand = 0; strand < strands; strand++) {
        const band = strand / strands
        for (let i = 0; i < samples; i++) {
          const t = i / (samples - 1)
          const x = side * (1.1 + t * 6.3)
          const wave = Math.sin(t * 10.5 - band * 3.5) * Math.sin(t * Math.PI) * 0.38
          const y = -1.12 + t * 1.5 + wave - band * (0.2 + Math.sin(t * Math.PI) * 1.4)
          const fade = Math.sin(t * Math.PI) * (0.75 + 0.6 * random())
          point(x, y, -0.7 - band * 0.8, strand % 9 === 0 ? 0.95 : 0, fade, 1)
          if (i % 3 === 0) point(x + (random() - 0.5) * 0.1, y + (random() - 0.5) * 0.28,
            -1.1, 0, fade * 0.45, 1)
        }
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
  uniform float uTime;
  uniform float uMotion;
  uniform float uActivity;
  uniform float uSpeech;
  uniform float uPixelScale;
  uniform float uSize;
  varying float vGold;
  varying float vLight;
  void main() {
    vec3 p = position;
    float wave = sin(p.x * 2.1 + uTime * (0.55 + uActivity * 0.6) + p.y * 2.0);
    p.y += wave * aFlow * 0.07 * uMotion;
    p.z += sin(p.y * 6.0 - uTime * 1.6) * 0.009 * uMotion * (1.0 - aFlow);
    p.xy *= 1.0 + uSpeech * 0.012 * sin(p.y * 8.0 + uTime * 9.0);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * uSize * uPixelScale * 7.1 / -mv.z, 1.0, 64.0);
    vGold = aGold;
    float shimmer = 0.88 + 0.12 * sin(uTime * 1.8 + p.y * 5.0 + p.x * 3.0);
    float scan = pow(max(0.0, sin(p.y * 3.0 - uTime * 1.5)), 12.0) * uActivity;
    vLight = aLight * (mix(1.0, shimmer, uMotion) + scan * uMotion * 0.28);
  }
`

export const particleFragmentShader = `
  uniform vec3 uColor;
  uniform vec3 uGold;
  uniform float uOpacity;
  uniform float uGain;
  varying float vGold;
  varying float vLight;
  void main() {
    float radius = length(gl_PointCoord - 0.5) * 2.0;
    if (radius > 1.0) discard;
    float core = exp(-radius * radius * 22.0);
    float halo = exp(-radius * radius * 4.0) * 0.38;
    float alpha = (core + halo) * (1.0 - smoothstep(0.65, 1.0, radius)) * vLight * uOpacity * uGain;
    vec3 color = mix(uColor, uGold, smoothstep(0.15, 0.8, vGold));
    gl_FragColor = vec4(color + vec3(core * 0.14), alpha);
  }
`
