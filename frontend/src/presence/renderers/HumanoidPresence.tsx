import { useEffect, useRef, useState } from "react"
import * as THREE from "three"
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js"
import { RenderPass } from "three/addons/postprocessing/RenderPass.js"
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js"
import { OutputPass } from "three/addons/postprocessing/OutputPass.js"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { createParticleBust, particleFragmentShader, particleVertexShader } from "./particleBust"
import "./humanoid-presence.css"

type HumanoidPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
}

const PHASE_COLOR: Record<PresenceSnapshot["phase"], number> = {
  offline: 0x547084, idle: 0x00c8ff, listening: 0x2ad8ff, thinking: 0x1aa0ff,
  executing: 0x00bdff, speaking: 0x3ad4ff, waiting: 0x7996b3, alert: 0xff7957,
}

export function HumanoidPresence({ snapshot, settings }: HumanoidPresenceProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const stateRef = useRef({ snapshot, settings })
  const [failure, setFailure] = useState<Error | null>(null)

  useEffect(() => { stateRef.current = { snapshot, settings } }, [snapshot, settings])

  useEffect(() => {
    const canvas = canvasRef.current
    const stage = stageRef.current
    if (!canvas || !stage) return
    const efficient = settings.performancePreset === "efficient"
    const renderer = new THREE.WebGLRenderer({
      canvas, alpha: true, antialias: false,
      powerPreference: efficient ? "low-power" : "high-performance",
    })
    // Opaque void matches the reference dark HUD plate.
    renderer.setClearColor(0x03070b, 1)
    renderer.toneMapping = THREE.ReinhardToneMapping
    renderer.toneMappingExposure = 1.08
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 40)
    camera.position.set(0.55, 0.28, 5.6)
    camera.lookAt(0.05, 0.1, 0)
    const uniforms = {
      uTime: { value: 0 }, uMotion: { value: 1 }, uActivity: { value: 0 },
      uSpeech: { value: 0 }, uPixelScale: { value: 1 }, uOpacity: { value: 1 },
      uAssemble: { value: 1 },
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
    const { head, body, field } = createParticleBust(density, material)
    const bust = new THREE.Group()
    bust.add(head, body)
    // ¾ view so the cyan contour silhouette reads like the reference profile shots.
    bust.rotation.y = 0.95
    bust.position.set(0.15, 0.08, 0)
    scene.add(field, bust)

    const composer = efficient ? null : new EffectComposer(renderer)
    const bloom = efficient
      ? null
      : new UnrealBloomPass(new THREE.Vector2(1, 1), 0.62, 0.4, 0.78)
    const output = efficient ? null : new OutputPass()
    if (composer && bloom && output) {
      composer.addPass(new RenderPass(scene, camera))
      composer.addPass(bloom)
      composer.addPass(output)
    }

    const pointer = new THREE.Vector2()
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
      camera.aspect = Math.max(1, width) / Math.max(1, height)
      camera.position.z = Math.max(5.4, 4.6 / Math.min(camera.aspect, 2.1))
      camera.position.x = camera.aspect > 1.6 ? 0.75 : 0.45
      camera.position.y = 0.28
      camera.lookAt(0.05, 0.08, 0)
      camera.updateProjectionMatrix()
      uniforms.uPixelScale.value = renderer.getPixelRatio() * Math.max(0.8, height / 580)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(stage)
    resize()

    const onPointerMove = (event: PointerEvent) => {
      const rect = stage.getBoundingClientRect()
      pointer.set(
        THREE.MathUtils.clamp((event.clientX - rect.left) / rect.width * 2 - 1, -1, 1),
        THREE.MathUtils.clamp((event.clientY - rect.top) / rect.height * 2 - 1, -1, 1),
      )
    }
    const resetPointer = () => pointer.set(0, 0)
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
      const phase = current.snapshot.phase
      const activity = {
        offline: 0, idle: 0.18, listening: 0.45, thinking: 0.72,
        executing: 1, speaking: 0.68, waiting: 0.12, alert: 0.85,
      }[phase]
      uniforms.uTime.value = animationTime
      // Keep assembled for first paint; mild re-assemble only on cold starts is skipped.
      uniforms.uAssemble.value = 1
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
      const follow = !reduced && current.settings.attentionMode === "pointer"
      const baseYaw = 0.95
      if (reduced) {
        bust.rotation.set(0, baseYaw, 0)
      } else {
        bust.rotation.y += ((baseYaw + (follow ? pointer.x * 0.12 : 0)) - bust.rotation.y) * 0.05
        bust.rotation.x += ((follow ? pointer.y * 0.04 : 0) - bust.rotation.x) * 0.06
      }
      bust.position.y = reduced ? 0.08 : 0.08 + Math.sin(animationTime * 1.05) * 0.016
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
    stage.addEventListener("pointermove", onPointerMove, { passive: true })
    stage.addEventListener("pointerleave", resetPointer)
    canvas.addEventListener("webglcontextlost", onContextLost)
    document.addEventListener("visibilitychange", onVisibilityChange)
    if (!document.hidden) frame = window.requestAnimationFrame(render)

    return () => {
      disposed = true
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      stage.removeEventListener("pointermove", onPointerMove)
      stage.removeEventListener("pointerleave", resetPointer)
      canvas.removeEventListener("webglcontextlost", onContextLost)
      document.removeEventListener("visibilitychange", onVisibilityChange)
      head.geometry.dispose()
      body.geometry.dispose()
      field.geometry.dispose()
      material.dispose()
      bloom?.dispose()
      output?.dispose()
      composer?.dispose()
      renderer.dispose()
    }
  }, [settings.performancePreset])

  if (failure) throw failure
  return (
    <div
      ref={stageRef}
      className="jarvis-presence jarvis-presence-humanoid"
      data-phase={snapshot.phase}
      data-performance-preset={settings.performancePreset}
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
