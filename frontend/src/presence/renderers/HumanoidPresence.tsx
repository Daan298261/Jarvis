import { useEffect, useRef, useState } from "react"
import * as THREE from "three"
import { createPresenceAttentionController, type AttentionVector } from "../presenceAttention"
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js"
import { RenderPass } from "three/addons/postprocessing/RenderPass.js"
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js"
import { OutputPass } from "three/addons/postprocessing/OutputPass.js"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import {
  createMorphablePresenceSystem,
  particleFragmentShader,
  particleVertexShader,
} from "./morphableOrbCloud"
import { presenceShapeIdForAvatar, resolvePresenceShape } from "./shapes/catalog"
import "./humanoid-presence.css"

type HumanoidPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
  /** Optional override for harness / morph demos; defaults from settings.avatarId. */
  shapeId?: string
}

const PHASE_COLOR: Record<PresenceSnapshot["phase"], number> = {
  offline: 0x547084, idle: 0x00c8ff, listening: 0x2ad8ff, thinking: 0x1aa0ff,
  executing: 0x00bdff, speaking: 0x3ad4ff, waiting: 0x7996b3, alert: 0xff7957,
}

export function HumanoidPresence({ snapshot, settings, shapeId }: HumanoidPresenceProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const attentionRef = useRef<AttentionVector>({ x: 0, y: 0, confidence: 0, source: "pointer" })
  const stateRef = useRef({ snapshot, settings, shapeId })
  const [failure, setFailure] = useState<Error | null>(null)
  const [activeShapeId, setActiveShapeId] = useState(
    () => shapeId || presenceShapeIdForAvatar(settings.avatarId),
  )

  useEffect(() => {
    stateRef.current = { snapshot, settings, shapeId }
  }, [snapshot, settings, shapeId])

  useEffect(() => {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)")
    const controller = createPresenceAttentionController({
      getMode: () => stateRef.current.settings.attentionMode,
      anchor: () => stageRef.current,
      getReducedMotion: () => {
        const rm = stateRef.current.settings.reducedMotion
        if (rm === "reduce") return true
        if (rm === "full") return false
        return motionQuery.matches
      },
    })
    let frame = 0
    const tick = () => {
      frame = window.requestAnimationFrame(tick)
      attentionRef.current = controller.sample()
    }
    frame = window.requestAnimationFrame(tick)
    return () => {
      window.cancelAnimationFrame(frame)
      controller.dispose()
    }
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    const stage = stageRef.current
    if (!canvas || !stage) return
    const efficient = settings.performancePreset === "efficient"
    const renderer = new THREE.WebGLRenderer({
      canvas, alpha: true, antialias: false,
      powerPreference: efficient ? "low-power" : "high-performance",
    })
    renderer.setClearColor(0x03070b, 1)
    renderer.toneMapping = THREE.ReinhardToneMapping
    renderer.toneMappingExposure = 0.96
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 40)
    camera.position.set(0.55, 0.28, 5.6)
    camera.lookAt(0.05, 0.1, 0)
    const uniforms = {
      uTime: { value: 0 }, uMotion: { value: 1 }, uActivity: { value: 0 },
      uSpeech: { value: 0 }, uPixelScale: { value: 1 }, uOpacity: { value: 1 },
      uMorph: { value: 1 },
      uPointer: { value: new THREE.Vector2(0, 0) },
      uPointerStrength: { value: 0 },
      uColor: { value: new THREE.Color(PHASE_COLOR.idle) },
      uGold: { value: new THREE.Color(0xff941f) },
    }
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: particleVertexShader,
      fragmentShader: particleFragmentShader,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    })
    const density = efficient ? 0.6 : settings.performancePreset === "cinematic" ? 1.15 : 0.95
    const initialId = shapeId || presenceShapeIdForAvatar(settings.avatarId)
    const system = createMorphablePresenceSystem(density, material, initialId)
    const bust = system.bust
    scene.add(system.group)
    setActiveShapeId(system.currentShapeId)

    const composer = efficient ? null : new EffectComposer(renderer)
    const bloom = efficient
      ? null
      : new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.32, 0.82)
    const output = efficient ? null : new OutputPass()
    if (composer && bloom && output) {
      composer.addPass(new RenderPass(scene, camera))
      composer.addPass(bloom)
      composer.addPass(output)
    }

    const color = new THREE.Color()
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)")
    let frame = 0
    let disposed = false
    let lastRender = 0
    let animationTime = 0

    const resize = () => {
      const { width, height } = stage.getBoundingClientRect()
      const preset = stateRef.current.settings.performancePreset
      const cap = preset === "efficient" ? 1 : preset === "cinematic" ? 1.5 : 1.25
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap))
      renderer.setSize(Math.max(1, width), Math.max(1, height), false)
      composer?.setPixelRatio(renderer.getPixelRatio())
      composer?.setSize(Math.max(1, width), Math.max(1, height))
      const aspect = Math.max(1, width) / Math.max(1, height)
      camera.aspect = aspect
      camera.fov = aspect < 0.85 ? 37 : 32
      camera.position.set(0, 0.12, aspect < 0.85 ? 6.15 : 5.6)
      camera.lookAt(0, 0.06, 0)
      // Keep the environment full-bleed. Only the bust is framed to occupy roughly
      // three quarters of the stage height on desktop.
      bust.scale.setScalar(aspect < 0.85 ? 0.9 : aspect > 2.05 ? 0.8 : 0.84)
      camera.updateProjectionMatrix()
      const scaleCap = aspect > 2.05 ? 720 : 580
      uniforms.uPixelScale.value = renderer.getPixelRatio() * Math.max(0.72, height / scaleCap)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(stage)
    resize()

    const onContextLost = (event: Event) => {
      event.preventDefault()
      window.cancelAnimationFrame(frame)
      setFailure(new Error("Particle presence WebGL context lost"))
    }

    const render = (time: number) => {
      if (disposed || document.hidden) return
      frame = window.requestAnimationFrame(render)
      const current = stateRef.current
      const reduced = current.settings.reducedMotion === "reduce"
        || (current.settings.reducedMotion === "system" && motionQuery.matches)
      const interval = reduced ? 100 : efficient ? 33 : 16
      if (time - lastRender < interval) return
      const delta = Math.min((time - lastRender) / 1000, 0.05)
      lastRender = time
      if (!reduced) animationTime += delta

      const desiredShape = current.shapeId
        || presenceShapeIdForAvatar(current.settings.avatarId)
      if (desiredShape !== system.currentShapeId) {
        system.morphTo(desiredShape, { duration: reduced ? 0 : 1.2, immediate: reduced })
        setActiveShapeId(system.currentShapeId)
      }
      system.tick(delta)

      const phase = current.snapshot.phase
      const activity = {
        offline: 0, idle: 0.18, listening: 0.45, thinking: 0.72,
        executing: 1, speaking: 0.68, waiting: 0.12, alert: 0.85,
      }[phase]
      uniforms.uTime.value = animationTime
      uniforms.uMotion.value = reduced ? 0 : 1
      uniforms.uActivity.value += (activity - uniforms.uActivity.value)
        * (reduced ? 1 : Math.min(1, delta * 3))
      uniforms.uSpeech.value = !reduced && phase === "speaking"
        ? THREE.MathUtils.clamp(current.snapshot.audioLevel, 0, 1) : 0
      uniforms.uOpacity.value = phase === "offline" ? 0.35 : phase === "waiting" ? 0.72 : 1
      color.setHex(PHASE_COLOR[phase])
      uniforms.uColor.value.lerp(color, reduced ? 1 : 0.12)
      uniforms.uGold.value.setHex(
        phase === "alert" ? 0xff543b : phase === "offline" ? 0x607580 : 0xff941f,
      )

      const framing = resolvePresenceShape(system.currentShapeId).framing
      const baseYaw = framing?.yaw ?? 0.06
      const basePos = framing?.position ?? [0, 0.08, 0]
      const mode = current.settings.attentionMode
      const follow = !reduced && mode !== "off"
      const att = attentionRef.current
      const yawGain = THREE.MathUtils.degToRad(6)
      const pitchGain = THREE.MathUtils.degToRad(3.5)
      const rotationLerp = 1 - Math.exp(-delta * 5.5)
      if (reduced) {
        bust.rotation.set(0, baseYaw, 0)
        bust.position.set(basePos[0], basePos[1], basePos[2])
        uniforms.uPointerStrength.value = 0
      } else {
        const ax = follow ? att.x : 0
        const ay = follow ? att.y : 0
        bust.rotation.y += ((baseYaw + ax * yawGain) - bust.rotation.y) * rotationLerp
        bust.rotation.x += ((-ay * pitchGain) - bust.rotation.x) * rotationLerp
        bust.position.x = basePos[0]
        bust.position.z = basePos[2]
        bust.position.y = basePos[1] + Math.sin(animationTime * 1.05) * 0.016
        uniforms.uPointer.value.set(ax * 1.75, 0.08 - ay * 1.6)
        uniforms.uPointerStrength.value += ((follow ? 1 : 0) - uniforms.uPointerStrength.value)
          * Math.min(1, delta * 5)
      }
      try {
        if (composer) composer.render()
        else renderer.render(scene, camera)
      } catch (error) {
        window.cancelAnimationFrame(frame)
        setFailure(error instanceof Error ? error : new Error("Particle presence render failed"))
      }
    }

    const onVisibilityChange = () => {
      window.cancelAnimationFrame(frame)
      if (!document.hidden) {
        lastRender = performance.now()
        frame = window.requestAnimationFrame(render)
      }
    }
    canvas.addEventListener("webglcontextlost", onContextLost)
    document.addEventListener("visibilitychange", onVisibilityChange)
    if (!document.hidden) frame = window.requestAnimationFrame(render)

    return () => {
      disposed = true
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      canvas.removeEventListener("webglcontextlost", onContextLost)
      document.removeEventListener("visibilitychange", onVisibilityChange)
      system.dispose()
      material.dispose()
      bloom?.dispose()
      output?.dispose()
      composer?.dispose()
      renderer.dispose()
    }
  // avatarId/shapeId morph inside the frame loop — remounting would drop the cloud.
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.performancePreset])

  if (failure) throw failure
  return (
    <div
      ref={stageRef}
      className="jarvis-presence jarvis-presence-humanoid"
      data-phase={snapshot.phase}
      data-performance-preset={settings.performancePreset}
      data-attention-mode={settings.attentionMode}
      data-presence-shape={activeShapeId}
      role="img"
      aria-label={`Jarvis particle presence is ${snapshot.phase}`}
    >
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="jarvis-humanoid-hud" aria-hidden="true">
        <span className="jarvis-humanoid-hud-tl" />
        <span className="jarvis-humanoid-hud-tr">
          TEM // PRESENCE
          <br />
          {snapshot.phase.toUpperCase()}
        </span>
        <span className="jarvis-humanoid-hud-bl" />
      </div>
      <div className="jarvis-humanoid-label" aria-hidden="true">
        <span>JARVIS</span><i /><span>NEURAL PRESENCE</span>
      </div>
    </div>
  )
}

export default HumanoidPresence
