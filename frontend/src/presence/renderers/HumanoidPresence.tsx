import { useEffect, useRef, type CSSProperties } from "react"
import * as THREE from "three"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import "./humanoid-presence.css"

type HumanoidPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
}

type Rig = {
  root: THREE.Group
  torso: THREE.Group
  head: THREE.Group
  leftArm: THREE.Group
  rightArm: THREE.Group
  chestCore: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>
  halo: THREE.Mesh<THREE.TorusGeometry, THREE.MeshBasicMaterial>
  field: THREE.Points<THREE.BufferGeometry, THREE.PointsMaterial>
}

const PHASE_COLOR: Record<PresenceSnapshot["phase"], number> = {
  offline: 0x6e7782,
  idle: 0x4cdcf5,
  listening: 0x58e7ff,
  thinking: 0xf1a43a,
  executing: 0xf1a43a,
  speaking: 0x76f2d1,
  waiting: 0x9eb8c6,
  alert: 0xff704d,
}

function mesh(
  geometry: THREE.BufferGeometry,
  material: THREE.Material,
  parent: THREE.Object3D,
  position: [number, number, number],
): THREE.Mesh {
  const part = new THREE.Mesh(geometry, material)
  part.position.set(...position)
  parent.add(part)
  return part
}

function buildRig(scene: THREE.Scene): Rig {
  const root = new THREE.Group()
  root.position.y = -0.42
  scene.add(root)

  const shell = new THREE.MeshStandardMaterial({
    color: 0x162c38,
    metalness: 0.78,
    roughness: 0.28,
    emissive: 0x061119,
    emissiveIntensity: 0.8,
  })
  const dark = new THREE.MeshStandardMaterial({
    color: 0x071016,
    metalness: 0.9,
    roughness: 0.22,
  })
  const glow = new THREE.MeshStandardMaterial({
    color: 0x8cecff,
    emissive: 0x28c6ec,
    emissiveIntensity: 2.1,
    metalness: 0.1,
    roughness: 0.2,
  })

  const torso = new THREE.Group()
  root.add(torso)
  mesh(new THREE.CapsuleGeometry(0.7, 1.03, 8, 20), shell, torso, [0, 0.62, 0])
  const chestPlate = mesh(new THREE.SphereGeometry(0.58, 24, 16), dark, torso, [0, 0.82, 0.42])
  chestPlate.scale.set(1, 0.65, 0.16)
  mesh(new THREE.CylinderGeometry(0.27, 0.34, 0.35, 20), dark, torso, [0, 1.47, 0])

  const chestCore = mesh(
    new THREE.SphereGeometry(0.12, 24, 16),
    glow.clone(),
    torso,
    [0, 0.91, 0.55],
  ) as THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>
  const chestRing = mesh(new THREE.TorusGeometry(0.24, 0.025, 10, 48), glow, torso, [0, 0.91, 0.53])
  chestRing.rotation.x = Math.PI / 2

  const head = new THREE.Group()
  head.position.set(0, 1.92, 0)
  root.add(head)
  const skull = mesh(new THREE.CapsuleGeometry(0.43, 0.35, 8, 24), shell, head, [0, 0, 0])
  skull.scale.z = 0.86
  const face = mesh(new THREE.SphereGeometry(0.38, 24, 16), dark, head, [0, -0.01, 0.23])
  face.scale.set(0.92, 0.75, 0.32)
  const visor = mesh(new THREE.BoxGeometry(0.58, 0.085, 0.035), glow.clone(), head, [0, 0.07, 0.51])
  visor.scale.x = 0.94
  mesh(new THREE.CylinderGeometry(0.12, 0.16, 0.18, 16), dark, head, [0, -0.47, 0])

  function arm(side: -1 | 1): THREE.Group {
    const shoulder = new THREE.Group()
    shoulder.position.set(side * 0.83, 1.2, 0)
    root.add(shoulder)
    mesh(new THREE.SphereGeometry(0.25, 18, 12), shell, shoulder, [0, 0, 0])
    const upper = mesh(new THREE.CapsuleGeometry(0.16, 0.56, 6, 14), shell, shoulder, [0, -0.48, 0])
    upper.rotation.z = side * -0.08
    const elbow = new THREE.Group()
    elbow.position.set(side * 0.04, -0.93, 0)
    shoulder.add(elbow)
    mesh(new THREE.SphereGeometry(0.18, 16, 10), dark, elbow, [0, 0, 0])
    mesh(new THREE.CapsuleGeometry(0.13, 0.5, 6, 14), shell, elbow, [0, -0.42, 0.03])
    mesh(new THREE.SphereGeometry(0.16, 16, 10), dark, elbow, [0, -0.82, 0.04])
    return shoulder
  }

  const leftArm = arm(-1)
  const rightArm = arm(1)

  const hips = new THREE.Group()
  hips.position.y = -0.25
  root.add(hips)
  mesh(new THREE.CapsuleGeometry(0.46, 0.22, 6, 18), dark, hips, [0, 0, 0])
  for (const side of [-1, 1] as const) {
    const leg = new THREE.Group()
    leg.position.set(side * 0.35, -0.25, 0)
    hips.add(leg)
    mesh(new THREE.CapsuleGeometry(0.21, 0.68, 6, 16), shell, leg, [0, -0.48, 0])
    mesh(new THREE.SphereGeometry(0.2, 16, 10), dark, leg, [0, -0.95, 0])
    mesh(new THREE.CapsuleGeometry(0.17, 0.61, 6, 14), shell, leg, [0, -1.34, 0.02])
    const foot = mesh(new THREE.CapsuleGeometry(0.18, 0.32, 6, 14), dark, leg, [0, -1.75, 0.16])
    foot.rotation.x = Math.PI / 2
  }

  const haloMaterial = new THREE.MeshBasicMaterial({ color: 0x42d9f5, transparent: true, opacity: 0.34 })
  const halo = new THREE.Mesh(new THREE.TorusGeometry(1.78, 0.012, 8, 96), haloMaterial)
  halo.rotation.x = Math.PI / 2.35
  halo.position.y = 0.35
  root.add(halo)

  const positions = new Float32Array(240 * 3)
  for (let index = 0; index < 240; index += 1) {
    const radius = 2.3 + Math.random() * 2.6
    const angle = Math.random() * Math.PI * 2
    positions[index * 3] = Math.cos(angle) * radius
    positions[index * 3 + 1] = (Math.random() - 0.45) * 5.4
    positions[index * 3 + 2] = Math.sin(angle) * radius - 1.2
  }
  const fieldGeometry = new THREE.BufferGeometry()
  fieldGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3))
  const field = new THREE.Points(
    fieldGeometry,
    new THREE.PointsMaterial({ color: 0x5bdcf4, size: 0.018, transparent: true, opacity: 0.36 }),
  )
  scene.add(field)

  return { root, torso, head, leftArm, rightArm, chestCore, halo, field }
}

function disposeScene(scene: THREE.Scene): void {
  const materials = new Set<THREE.Material>()
  scene.traverse((object) => {
    const item = object as THREE.Mesh
    item.geometry?.dispose()
    const material = item.material
    if (Array.isArray(material)) material.forEach((value) => materials.add(value))
    else if (material) materials.add(material)
  })
  materials.forEach((material) => material.dispose())
}

export function HumanoidPresence({ snapshot, settings, size = 720 }: HumanoidPresenceProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const stageRef = useRef<HTMLDivElement | null>(null)
  const stateRef = useRef({ snapshot, settings })

  useEffect(() => {
    stateRef.current = { snapshot, settings }
  }, [snapshot, settings])

  useEffect(() => {
    const canvas = canvasRef.current
    const stage = stageRef.current
    if (!canvas || !stage) return

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: settings.performancePreset !== "efficient",
      powerPreference: settings.performancePreset === "efficient" ? "low-power" : "high-performance",
    })
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.08

    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2(0x02070b, 0.055)
    const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 40)
    camera.position.set(0, 0.62, 8.4)

    scene.add(new THREE.HemisphereLight(0x8defff, 0x071018, 1.65))
    const key = new THREE.DirectionalLight(0xffb25a, 2.7)
    key.position.set(3.8, 4.5, 5)
    scene.add(key)
    const rim = new THREE.DirectionalLight(0x2ccfed, 3.1)
    rim.position.set(-4, 2, -3)
    scene.add(rim)

    const floor = new THREE.Mesh(
      new THREE.RingGeometry(1.15, 3.8, 96),
      new THREE.MeshBasicMaterial({ color: 0x0d6378, transparent: true, opacity: 0.08, side: THREE.DoubleSide }),
    )
    floor.rotation.x = -Math.PI / 2
    floor.position.y = -2.43
    scene.add(floor)

    const rig = buildRig(scene)
    const pointer = new THREE.Vector2(0, 0)
    let frame = 0
    let lastRender = 0
    let disposed = false

    const resize = () => {
      const rect = stage.getBoundingClientRect()
      const width = Math.max(1, Math.round(rect.width))
      const height = Math.max(1, Math.round(rect.height))
      const preset = stateRef.current.settings.performancePreset
      const ratioCap = preset === "efficient" ? 1 : preset === "cinematic" ? 2 : 1.5
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, ratioCap))
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(stage)
    resize()

    const onPointerMove = (event: PointerEvent) => {
      if (stateRef.current.settings.attentionMode !== "pointer") return
      const rect = stage.getBoundingClientRect()
      pointer.x = THREE.MathUtils.clamp(((event.clientX - rect.left) / rect.width - 0.5) * 2, -1, 1)
      pointer.y = THREE.MathUtils.clamp(((event.clientY - rect.top) / rect.height - 0.5) * 2, -1, 1)
    }
    stage.addEventListener("pointermove", onPointerMove, { passive: true })

    const render = (time: number) => {
      if (disposed) return
      frame = window.requestAnimationFrame(render)
      if (document.hidden) return

      const current = stateRef.current
      const efficient = current.settings.performancePreset === "efficient"
      const reduced = current.settings.reducedMotion === "reduce"
        || (current.settings.reducedMotion === "system" && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
      const frameInterval = reduced ? 120 : efficient ? 34 : 16
      if (time - lastRender < frameInterval) return
      lastRender = time

      const seconds = time / 1000
      const phase = current.snapshot.phase
      const active = ["thinking", "executing", "listening", "speaking"].includes(phase)
      const motion = reduced ? 0 : 1
      const breath = Math.sin(seconds * (phase === "speaking" ? 4.4 : 1.35)) * 0.018 * motion
      const speech = phase === "speaking" ? Math.sin(seconds * 9.5) * 0.035 * motion : 0
      const thinking = ["thinking", "executing"].includes(phase) ? Math.sin(seconds * 2.2) * 0.08 * motion : 0
      const gazeX = current.settings.attentionMode === "pointer" ? pointer.x * 0.24 : thinking
      const gazeY = current.settings.attentionMode === "pointer" ? -pointer.y * 0.12 : 0

      rig.root.position.y = -0.42 + breath
      rig.root.rotation.y += ((gazeX * 0.18) - rig.root.rotation.y) * 0.045
      rig.head.rotation.y += (gazeX - rig.head.rotation.y) * 0.075
      rig.head.rotation.x += (gazeY + speech - rig.head.rotation.x) * 0.075
      rig.torso.rotation.z = Math.sin(seconds * 0.72) * 0.008 * motion
      rig.leftArm.rotation.z = 0.07 + (active ? Math.sin(seconds * 1.7) * 0.035 * motion : 0)
      rig.rightArm.rotation.z = -0.07 - (phase === "speaking" ? Math.sin(seconds * 2.8) * 0.09 * motion : 0)
      rig.rightArm.rotation.x = phase === "speaking" ? 0.08 + Math.sin(seconds * 2.1) * 0.04 * motion : 0
      rig.halo.rotation.z += (active ? 0.0045 : 0.0015) * motion
      rig.field.rotation.y += (active ? 0.0008 : 0.00025) * motion

      const color = new THREE.Color(PHASE_COLOR[phase])
      rig.chestCore.material.color.lerp(color, 0.16)
      rig.chestCore.material.emissive.lerp(color, 0.16)
      rig.chestCore.material.emissiveIntensity = phase === "offline" ? 0.35 : active ? 2.9 : 1.75
      const pulse = phase === "speaking" ? 1.12 + Math.abs(Math.sin(seconds * 8)) * 0.16 : active ? 1.08 : 1
      rig.chestCore.scale.setScalar(reduced ? 1 : pulse)
      rig.halo.material.color.lerp(color, 0.12)
      rig.halo.material.opacity = phase === "offline" ? 0.12 : active ? 0.48 : 0.28
      rig.field.material.color.lerp(color, 0.08)

      renderer.render(scene, camera)
    }
    frame = window.requestAnimationFrame(render)

    return () => {
      disposed = true
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      stage.removeEventListener("pointermove", onPointerMove)
      disposeScene(scene)
      renderer.dispose()
      renderer.forceContextLoss()
    }
  }, [settings.performancePreset])

  return (
    <div
      ref={stageRef}
      className="jarvis-presence jarvis-presence-humanoid"
      data-phase={snapshot.phase}
      data-performance-preset={settings.performancePreset}
      aria-label={`Jarvis humanoid is ${snapshot.phase}`}
      style={{ "--jarvis-humanoid-size": `${size}px` } as CSSProperties}
    >
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="jarvis-humanoid-scanline" aria-hidden="true" />
      <div className="jarvis-humanoid-label" aria-hidden="true">
        <span>JARVIS // HUMANOID</span>
        <i />
        <span>{snapshot.phase.toUpperCase()}</span>
      </div>
    </div>
  )
}

export default HumanoidPresence
