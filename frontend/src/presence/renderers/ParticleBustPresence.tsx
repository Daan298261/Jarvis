import { useEffect, useRef, useState } from "react"
import * as THREE from "three"
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js"
import { OutputPass } from "three/addons/postprocessing/OutputPass.js"
import { RenderPass } from "three/addons/postprocessing/RenderPass.js"
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js"
import { createPresenceAttentionController, type AttentionVector } from "../presenceAttention"
import type { PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { createApexParticleBust, particleFragmentShader, particleVertexShader } from "./particleBust"
import "./humanoid-presence.css"

type Props = { snapshot: PresenceSnapshot; settings: PresentationSettings; size?: number }

const COLORS: Record<PresenceSnapshot["phase"], number> = {
  offline: 0x547084, idle: 0x00c8ff, listening: 0x2ad8ff, thinking: 0x1aa0ff,
  executing: 0x00bdff, speaking: 0x3ad4ff, waiting: 0x7996b3, alert: 0xff7957,
}

export function ParticleBustPresence({ snapshot, settings }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const stateRef = useRef({ snapshot, settings })
  const attentionRef = useRef<AttentionVector>({ x: 0, y: 0, confidence: 0, source: "pointer" })
  const [failure, setFailure] = useState<Error | null>(null)
  useEffect(() => { stateRef.current = { snapshot, settings } }, [snapshot, settings])

  useEffect(() => {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)")
    const controller = createPresenceAttentionController({
      getMode: () => stateRef.current.settings.attentionMode,
      anchor: () => stageRef.current,
      getReducedMotion: () => stateRef.current.settings.reducedMotion === "reduce"
        || (stateRef.current.settings.reducedMotion === "system" && motionQuery.matches),
    })
    let frame = 0
    const sample = () => { attentionRef.current = controller.sample(); frame = requestAnimationFrame(sample) }
    frame = requestAnimationFrame(sample)
    return () => { cancelAnimationFrame(frame); controller.dispose() }
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    const stage = stageRef.current
    if (!canvas || !stage) return
    const efficient = settings.performancePreset === "efficient"
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: efficient ? "low-power" : "high-performance" })
    renderer.setClearColor(0x03070b, 1)
    renderer.toneMapping = THREE.ReinhardToneMapping
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 40)
    camera.position.set(0, 0.05, 6.25)
    const uniforms = {
      uTime: { value: 0 }, uMotion: { value: 1 }, uActivity: { value: 0 }, uSpeech: { value: 0 },
      uPixelScale: { value: 1 }, uOpacity: { value: 1 }, uMorph: { value: 1 },
      uPointer: { value: new THREE.Vector2() }, uPointerStrength: { value: 0 },
      uColor: { value: new THREE.Color(COLORS.idle) }, uGold: { value: new THREE.Color(0xff941f) },
    }
    const material = new THREE.ShaderMaterial({ uniforms, vertexShader: particleVertexShader, fragmentShader: particleFragmentShader, transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending })
    const density = efficient ? 0.55 : settings.performancePreset === "cinematic" ? 1 : 0.75
    const { head, body, field } = createApexParticleBust(density, material)
    const bust = new THREE.Group()
    bust.add(head, body); scene.add(field, bust)
    const composer = efficient ? null : new EffectComposer(renderer)
    const bloom = efficient ? null : new UnrealBloomPass(new THREE.Vector2(1, 1), 0.75, 0.55, 0.7)
    const output = efficient ? null : new OutputPass()
    if (composer && bloom && output) { composer.addPass(new RenderPass(scene, camera)); composer.addPass(bloom); composer.addPass(output) }
    const color = new THREE.Color(); const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)")
    let frame = 0; let disposed = false; let last = 0; let animationTime = 0
    const resize = () => {
      const { width, height } = stage.getBoundingClientRect(); const aspect = Math.max(1, width) / Math.max(1, height)
      const cap = stateRef.current.settings.performancePreset === "cinematic" ? 1.5 : efficient ? 1 : 1.25
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap)); renderer.setSize(Math.max(1, width), Math.max(1, height), false)
      composer?.setPixelRatio(renderer.getPixelRatio()); composer?.setSize(Math.max(1, width), Math.max(1, height))
      camera.aspect = aspect; camera.position.z = aspect < 0.85 ? 6.8 : 6.25; camera.updateProjectionMatrix()
      uniforms.uPixelScale.value = renderer.getPixelRatio() * Math.max(0.72, height / 650)
    }
    const observer = new ResizeObserver(resize); observer.observe(stage); resize()
    const onLost = (event: Event) => { event.preventDefault(); cancelAnimationFrame(frame); setFailure(new Error("Particle bust WebGL context lost")) }
    const render = (time: number) => {
      if (disposed || document.hidden) return
      frame = requestAnimationFrame(render)
      const current = stateRef.current; const reduced = current.settings.reducedMotion === "reduce" || (current.settings.reducedMotion === "system" && motionQuery.matches)
      const interval = reduced ? 100 : efficient ? 33 : 16
      if (time - last < interval) return
      const delta = Math.min((time - last) / 1000, 0.05); last = time; if (!reduced) animationTime += delta
      const activity = { offline: 0, idle: .18, listening: .45, thinking: .72, executing: 1, speaking: .68, waiting: .12, alert: .85 }[current.snapshot.phase]
      uniforms.uTime.value = animationTime; uniforms.uMotion.value = reduced ? 0 : 1; uniforms.uActivity.value += (activity - uniforms.uActivity.value) * (reduced ? 1 : Math.min(1, delta * 3))
      uniforms.uSpeech.value = !reduced && current.snapshot.phase === "speaking" ? THREE.MathUtils.clamp(current.snapshot.audioLevel, 0, 1) : 0
      uniforms.uOpacity.value = current.snapshot.phase === "offline" ? .35 : current.snapshot.phase === "waiting" ? .72 : 1
      color.setHex(COLORS[current.snapshot.phase]); uniforms.uColor.value.lerp(color, reduced ? 1 : .12)
      uniforms.uGold.value.setHex(current.snapshot.phase === "alert" ? 0xff543b : current.snapshot.phase === "offline" ? 0x607580 : 0xff941f)
      const attention = attentionRef.current; const follow = !reduced && current.settings.attentionMode !== "off"
      bust.rotation.y += ((follow ? attention.x * .16 : 0) - bust.rotation.y) * (reduced ? 1 : Math.min(1, delta * 3.5))
      bust.rotation.x += ((follow ? -attention.y * .04 : 0) - bust.rotation.x) * (reduced ? 1 : Math.min(1, delta * 3.5))
      bust.position.y = reduced ? 0 : Math.sin(animationTime * 1.05) * .014
      uniforms.uPointer.value.set(attention.x * 1.4, .1 - attention.y * 1.2); uniforms.uPointerStrength.value = follow ? attention.confidence * .35 : 0
      try { if (composer) composer.render(); else renderer.render(scene, camera) } catch (error) { setFailure(error instanceof Error ? error : new Error("Particle bust render failed")) }
    }
    const onVisibility = () => { cancelAnimationFrame(frame); if (!document.hidden) { last = performance.now(); frame = requestAnimationFrame(render) } }
    canvas.addEventListener("webglcontextlost", onLost); document.addEventListener("visibilitychange", onVisibility); if (!document.hidden) frame = requestAnimationFrame(render)
    return () => { disposed = true; cancelAnimationFrame(frame); observer.disconnect(); canvas.removeEventListener("webglcontextlost", onLost); document.removeEventListener("visibilitychange", onVisibility); head.geometry.dispose(); body.geometry.dispose(); field.geometry.dispose(); material.dispose(); bloom?.dispose(); output?.dispose(); composer?.dispose(); renderer.dispose() }
  }, [settings.performancePreset])
  if (failure) throw failure
  return <div ref={stageRef} className="jarvis-presence jarvis-presence-humanoid" data-phase={snapshot.phase} data-performance-preset={settings.performancePreset} role="img" aria-label={`Jarvis particle bust is ${snapshot.phase}`}><canvas ref={canvasRef} aria-hidden="true" /><div className="jarvis-humanoid-label" aria-hidden="true"><span>JARVIS</span><i /><span>PARTICLE BUST</span></div></div>
}

export default ParticleBustPresence
