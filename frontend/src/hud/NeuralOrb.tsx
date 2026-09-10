import { useEffect, useRef, type CSSProperties } from "react"
import * as THREE from "three"
import type { OrbMood } from "./orbMood"

type NeuralOrbProps = {
  mood?: OrbMood
  size?: number
}

const CYAN = new THREE.Color(0x67dcff)
const ALERT = new THREE.Color(0xff8a3d)
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))

function fract(value: number): number {
  return value - Math.floor(value)
}

function hash(index: number, salt: number): number {
  return fract(Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453)
}

function shellPositions(count: number, radius: number, jitter = 0): Float32Array {
  const positions = new Float32Array(count * 3)
  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2
    const planar = Math.sqrt(Math.max(0, 1 - y * y))
    const theta = GOLDEN_ANGLE * i
    const r = radius + (hash(i, radius) - 0.5) * jitter
    positions[i * 3] = Math.cos(theta) * planar * r
    positions[i * 3 + 1] = y * r
    positions[i * 3 + 2] = Math.sin(theta) * planar * r
  }
  return positions
}

function volumePositions(count: number, radius: number): Float32Array {
  const positions = new Float32Array(count * 3)
  for (let i = 0; i < count; i += 1) {
    const u = hash(i, 1.7)
    const v = hash(i, 4.3)
    const w = hash(i, 8.9)
    const theta = u * Math.PI * 2
    const phi = Math.acos(2 * v - 1)
    const r = radius * Math.cbrt(w)
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta)
    positions[i * 3 + 1] = r * Math.cos(phi)
    positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
  }
  return positions
}

function pointsFromPositions(
  positions: Float32Array,
  size: number,
  opacity: number,
  color: THREE.Color,
): { points: THREE.Points; geometry: THREE.BufferGeometry; material: THREE.PointsMaterial } {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3))
  const material = new THREE.PointsMaterial({
    color: color.clone(),
    size,
    sizeAttenuation: true,
    transparent: true,
    opacity,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  return { points: new THREE.Points(geometry, material), geometry, material }
}

function energyForMood(mood: OrbMood): number {
  switch (mood) {
    case "listening": return 0.52
    case "thinking": return 0.66
    case "speaking": return 0.92
    case "alert": return 0.76
    default: return 0.24
  }
}

function speedForMood(mood: OrbMood): number {
  switch (mood) {
    case "listening": return 0.42
    case "thinking": return 0.68
    case "speaking": return 0.9
    case "alert": return 0.78
    default: return 0.18
  }
}

export function NeuralOrb({ mood = "idle", size = 520 }: NeuralOrbProps) {
  const mountRef = useRef<HTMLDivElement>(null)
  const moodRef = useRef<OrbMood>(mood)

  useEffect(() => {
    moodRef.current = mood
  }, [mood])

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      })
    } catch {
      return
    }

    renderer.setClearColor(0x000000, 0)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.65))
    renderer.domElement.className = "jarvis-neural-canvas"
    mount.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(39, 1, 0.1, 20)
    camera.position.set(0, 0, 3.35)

    const root = new THREE.Group()
    const sphere = new THREE.Group()
    root.add(sphere)
    scene.add(root)

    const outer = pointsFromPositions(shellPositions(2600, 1.02, 0.035), 0.017, 0.72, CYAN)
    const middle = pointsFromPositions(shellPositions(1500, 0.84, 0.05), 0.013, 0.36, CYAN)
    const volume = pointsFromPositions(volumePositions(1050, 0.72), 0.012, 0.24, CYAN)
    sphere.add(outer.points, middle.points, volume.points)

    const coreGeometry = new THREE.SphereGeometry(0.78, 64, 64)
    const coreMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uEnergy: { value: energyForMood(moodRef.current) },
        uColor: { value: CYAN.clone() },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexShader: `
        varying vec3 vNormalView;
        varying vec3 vPositionLocal;
        void main() {
          vNormalView = normalize(normalMatrix * normal);
          vPositionLocal = position;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        precision mediump float;
        varying vec3 vNormalView;
        varying vec3 vPositionLocal;
        uniform float uTime;
        uniform float uEnergy;
        uniform vec3 uColor;

        void main() {
          float facing = clamp(vNormalView.z, 0.0, 1.0);
          float fresnel = pow(1.0 - facing, 2.45);
          float lat = sin(vPositionLocal.y * 23.0 + sin(vPositionLocal.x * 8.0 + uTime * 0.7) * 2.2);
          float lon = sin(atan(vPositionLocal.x, vPositionLocal.z) * 7.0 - uTime * 0.34);
          float filament = smoothstep(0.76, 0.99, abs(lat * lon));
          float shimmer = 0.5 + 0.5 * sin(uTime * 1.7 + vPositionLocal.y * 8.0);
          float alpha = 0.055 + fresnel * 0.54 + filament * (0.07 + uEnergy * 0.17);
          vec3 color = uColor * (0.34 + fresnel * 1.75 + filament * (0.75 + uEnergy) + shimmer * 0.08);
          gl_FragColor = vec4(color, alpha);
        }
      `,
    })
    const core = new THREE.Mesh(coreGeometry, coreMaterial)
    sphere.add(core)

    const innerGeometry = new THREE.SphereGeometry(0.49, 40, 40)
    const innerMaterial = new THREE.MeshBasicMaterial({
      color: CYAN.clone(),
      transparent: true,
      opacity: 0.075,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const inner = new THREE.Mesh(innerGeometry, innerMaterial)
    sphere.add(inner)

    const ringGeometry = new THREE.TorusGeometry(1.14, 0.0045, 8, 180)
    const ringMaterials: THREE.MeshBasicMaterial[] = []
    const rings: THREE.Mesh[] = []
    const rotations: Array<[number, number, number]> = [
      [0.42, 0.28, 0.08],
      [1.08, -0.36, 0.64],
      [-0.74, 0.92, -0.28],
      [0.22, -1.12, 1.04],
    ]
    rotations.forEach((rotation, index) => {
      const material = new THREE.MeshBasicMaterial({
        color: CYAN.clone(),
        transparent: true,
        opacity: 0.1 - index * 0.012,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
      const ring = new THREE.Mesh(ringGeometry, material)
      ring.rotation.set(...rotation)
      ring.scale.setScalar(1 + index * 0.025)
      root.add(ring)
      ringMaterials.push(material)
      rings.push(ring)
    })

    const resize = () => {
      const rect = mount.getBoundingClientRect()
      const next = Math.max(180, Math.round(Math.min(rect.width || size, rect.height || size)))
      renderer.setSize(next, next, false)
      camera.aspect = 1
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null
    observer?.observe(mount)

    let pointerX = 0
    let pointerY = 0
    const onPointerMove = (event: PointerEvent) => {
      pointerX = (event.clientX / Math.max(1, window.innerWidth) - 0.5) * 2
      pointerY = (event.clientY / Math.max(1, window.innerHeight) - 0.5) * 2
    }
    window.addEventListener("pointermove", onPointerMove, { passive: true })

    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
    const clock = new THREE.Clock()
    let raf = 0
    let energy = energyForMood(moodRef.current)
    let speed = speedForMood(moodRef.current)
    const liveColor = CYAN.clone()

    const render = () => {
      const elapsed = clock.getElapsedTime()
      const currentMood = moodRef.current
      const targetEnergy = energyForMood(currentMood)
      const targetSpeed = speedForMood(currentMood)
      energy += (targetEnergy - energy) * 0.045
      speed += (targetSpeed - speed) * 0.045

      const targetColor = currentMood === "alert" ? ALERT : CYAN
      liveColor.lerp(targetColor, 0.06)
      outer.material.color.copy(liveColor)
      middle.material.color.copy(liveColor)
      volume.material.color.copy(liveColor)
      innerMaterial.color.copy(liveColor)
      ringMaterials.forEach((material) => material.color.copy(liveColor))
      coreMaterial.uniforms.uColor.value.copy(liveColor)
      coreMaterial.uniforms.uTime.value = elapsed
      coreMaterial.uniforms.uEnergy.value = energy

      const pulse = 1 + Math.sin(elapsed * (0.8 + speed * 1.3)) * (0.006 + energy * 0.014)
      sphere.scale.setScalar(pulse)
      sphere.rotation.y += 0.0015 + speed * 0.0025
      sphere.rotation.x += (pointerY * 0.22 - sphere.rotation.x) * 0.1
      root.rotation.y += (pointerX * 0.32 - root.rotation.y) * 0.085

      outer.material.opacity = 0.58 + energy * 0.24
      middle.material.opacity = 0.23 + energy * 0.28
      volume.material.opacity = 0.14 + energy * 0.22
      outer.material.size = 0.015 + energy * 0.005
      middle.material.size = 0.011 + energy * 0.004
      volume.material.size = 0.01 + energy * 0.004
      innerMaterial.opacity = 0.045 + energy * 0.075

      rings.forEach((ring, index) => {
        ring.rotation.z += (0.00055 + speed * 0.0011) * (index % 2 === 0 ? 1 : -1)
        ringMaterials[index].opacity = 0.055 + energy * (0.075 - index * 0.008)
      })

      renderer.render(scene, camera)
      if (!reducedMotion) raf = window.requestAnimationFrame(render)
    }
    render()

    return () => {
      if (raf) window.cancelAnimationFrame(raf)
      observer?.disconnect()
      window.removeEventListener("pointermove", onPointerMove)
      outer.geometry.dispose()
      middle.geometry.dispose()
      volume.geometry.dispose()
      outer.material.dispose()
      middle.material.dispose()
      volume.material.dispose()
      coreGeometry.dispose()
      coreMaterial.dispose()
      innerGeometry.dispose()
      innerMaterial.dispose()
      ringGeometry.dispose()
      ringMaterials.forEach((material) => material.dispose())
      renderer.dispose()
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement)
    }
  }, [size])

  return (
    <div
      className={`jarvis-neural-orb mood-${mood}`}
      style={{ "--jarvis-orb-size": `${size}px` } as CSSProperties}
      role="img"
      aria-label={`Jarvis neural core: ${mood}`}
    >
      <div className="jarvis-orb-aura" aria-hidden />
      <div className="jarvis-orb-fallback" aria-hidden />
      <div className="jarvis-orb-orbit jarvis-orb-orbit-a" aria-hidden />
      <div className="jarvis-orb-orbit jarvis-orb-orbit-b" aria-hidden />
      <div className="jarvis-orb-orbit jarvis-orb-orbit-c" aria-hidden />
      <div ref={mountRef} className="jarvis-orb-webgl" aria-hidden />
      <div className="jarvis-orb-glass" aria-hidden />
    </div>
  )
}
