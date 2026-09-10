import { useEffect, useRef, useState } from "react"
import * as THREE from "three"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { createParticleBust, particleFragmentShader, particleVertexShader } from "./particleBust"
import "./humanoid-presence.css"

type HumanoidPresenceProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  size?: number
}

const PHASE_COLOR: Record<PresenceSnapshot["phase"], number> = {
  offline: 0x547084, idle: 0x00cfff, listening: 0x42edff, thinking: 0x24aeff,
  executing: 0x20ddff, speaking: 0x57e6ff, waiting: 0x8bb4d2, alert: 0xff7957,
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
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false,
      powerPreference: efficient ? "low-power" : "high-performance" })
    renderer.setClearColor(0x000000, 0)
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 40)
    camera.position.set(0, 0.08, 7.1)
    const uniforms = {
      uTime: { value: 0 }, uMotion: { value: 1 }, uActivity: { value: 0 },
      uSpeech: { value: 0 }, uPixelScale: { value: 1 }, uOpacity: { value: 1 },
      uSize: { value: 1 }, uGain: { value: 1 },
      uColor: { value: new THREE.Color(PHASE_COLOR.idle) },
      uGold: { value: new THREE.Color(0xffb33f) },
    }
    const material = new THREE.ShaderMaterial({
      uniforms, vertexShader: particleVertexShader, fragmentShader: particleFragmentShader,
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    })
    const density = efficient ? 0.65 : settings.performancePreset === "cinematic" ? 1.2 : 1
    const { head, body, field } = createParticleBust(density, material)
    // A soft sprite pass gives the point cloud bloom without full-screen render targets.
    const glowMaterial = new THREE.ShaderMaterial({
      uniforms: { ...uniforms, uSize: { value: 3.5 }, uGain: { value: 0.055 } },
      vertexShader: particleVertexShader, fragmentShader: particleFragmentShader,
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    })
    if (!efficient) {
      for (const points of [head, body, field]) points.add(new THREE.Points(points.geometry, glowMaterial))
    }
    const bust = new THREE.Group()
    bust.add(head, body)
    scene.add(field, bust)
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
      const cap = preset === "efficient" ? 1 : preset === "cinematic" ? 2 : 1.5
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap))
      renderer.setSize(Math.max(1, width), Math.max(1, height), false)
      camera.aspect = Math.max(1, width) / Math.max(1, height)
      // Fit shoulders on phones; preserve portrait scale as a desktop gets wider.
      camera.position.z = Math.max(7.1, 5.6 / camera.aspect)
      camera.updateProjectionMatrix()
      uniforms.uPixelScale.value = renderer.getPixelRatio() * Math.max(0.75, height / 620)
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
      const activity = { offline: 0, idle: 0.15, listening: 0.45, thinking: 0.7,
        executing: 1, speaking: 0.65, waiting: 0.1, alert: 0.8 }[phase]
      uniforms.uTime.value = animationTime
      uniforms.uMotion.value = reduced ? 0 : 1
      uniforms.uActivity.value = activity
      uniforms.uSpeech.value = !reduced && phase === "speaking"
        ? THREE.MathUtils.clamp(current.snapshot.audioLevel, 0, 1) : 0
      uniforms.uOpacity.value = phase === "offline" ? 0.35 : phase === "waiting" ? 0.7 : 1
      color.setHex(PHASE_COLOR[phase])
      uniforms.uColor.value.lerp(color, reduced ? 1 : 0.12)
      uniforms.uGold.value.setHex(phase === "alert" ? 0xff543b : phase === "offline" ? 0x607580 : 0xffb33f)
      const follow = !reduced && current.settings.attentionMode === "pointer"
      if (reduced) head.rotation.set(0, 0, 0)
      else {
        head.rotation.y += ((follow ? pointer.x * 0.16 : 0) - head.rotation.y) * 0.08
        head.rotation.x += ((follow ? pointer.y * 0.045 : 0) - head.rotation.x) * 0.08
      }
      bust.position.y = reduced ? 0 : Math.sin(animationTime * 1.1) * 0.018
      try { renderer.render(scene, camera) } catch (error) {
        window.cancelAnimationFrame(frame)
        setFailure(error instanceof Error ? error : new Error("Particle presence render failed"))
      }
    }
    const onVisibilityChange = () => {
      window.cancelAnimationFrame(frame)
      if (!document.hidden) { lastRender = performance.now(); frame = window.requestAnimationFrame(render) }
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
      head.geometry.dispose(); body.geometry.dispose(); field.geometry.dispose()
      material.dispose()
      glowMaterial.dispose()
      renderer.dispose()
    }
  }, [settings.performancePreset])

  if (failure) throw failure
  return (
    <div ref={stageRef} className="jarvis-presence jarvis-presence-humanoid"
      data-phase={snapshot.phase} data-performance-preset={settings.performancePreset}
      role="img" aria-label={`Jarvis particle presence is ${snapshot.phase}`}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="jarvis-humanoid-label" aria-hidden="true">
        <span>JARVIS</span><i /><span>NEURAL PRESENCE</span>
      </div>
    </div>
  )
}

export default HumanoidPresence
