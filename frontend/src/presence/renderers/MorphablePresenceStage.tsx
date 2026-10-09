import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"
import * as THREE from "three"
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js"
import { OutputPass } from "three/addons/postprocessing/OutputPass.js"
import { RenderPass } from "three/addons/postprocessing/RenderPass.js"
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js"
import { createPresenceAttentionController, type AttentionVector } from "../presenceAttention"
import {
  LIFECYCLE_MORPH_SECONDS,
  PERSONA_MORPH_SECONDS,
  isRestPresencePhase,
  lifecycleMorphBlend,
  lifecycleMorphTarget,
  restAttractGain,
} from "../presenceLifecycle"
import type { PersonaCloudVisual, PresencePhase, PresenceSnapshot, PresentationSettings } from "../presenceTypes"
import { readVoiceMeter } from "../../tts/voiceAnalyser"
import {
  AutoPresenceQuality,
  motifSafeAccentHex,
  normalizedPresenceFitScale,
  presenceFitYawFrameOffset,
  presenceLookAtFromFit,
  resolveDotAppearance,
  resolvePresenceBloom,
  unionPresencePositions,
  PRESENCE_DEFAULT_FRAMING_YAW,
  PRESENCE_QUALITY_DENSITIES,
} from "../presenceQuality"
import {
  FIGURE_SAMPLE_ENERGY,
  createMorphablePresenceSystem,
  particleFragmentShader,
  particleVertexShader,
} from "./morphableOrbCloud"
import { presenceShapeIdForAvatar, resolvePresenceShape } from "./shapes/catalog"
import "./humanoid-presence.css"

type MorphablePresenceStageProps = {
  snapshot: PresenceSnapshot
  settings: PresentationSettings
  shapeId?: string
  personaVisual?: PersonaCloudVisual
  className: string
  ariaLabel: string
  /** Neural keeps the HUD ground and chrome visible through the cloud. */
  transparentBackdrop?: boolean
  style?: CSSProperties
  children?: ReactNode
}

const PHASE_COLOR: Record<PresenceSnapshot["phase"], number> = {
  offline: 0x547084, idle: 0x00c8ff, listening: 0x2ad8ff, thinking: 0x1aa0ff,
  executing: 0x00bdff, speaking: 0x3ad4ff, waiting: 0x7996b3, alert: 0xff7957,
  approval: 0xf5d76e, error: 0xffb020,
}

const PHASE_KIND: Record<PresencePhase, number> = {
  idle: 0, waiting: 0, listening: 1, thinking: 2, executing: 3,
  speaking: 4, alert: 5, approval: 6, error: 7, offline: 8,
}

function phaseIsEngaged(phase: PresencePhase): boolean {
  return !isRestPresencePhase(phase)
}

function personaDetail(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value)
    ? THREE.MathUtils.clamp(value, 0.35, 1)
    : 1
}

/**
 * One canvas, one orb cloud, one `uMorph`. Phase drives rest tightness ↔ winning figure
 * for every avatar that mounts this stage. Galaxy only toggles the star layer.
 */
export function MorphablePresenceStage({
  snapshot,
  settings,
  shapeId,
  personaVisual,
  className,
  ariaLabel,
  transparentBackdrop = false,
  style,
  children,
}: MorphablePresenceStageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const attentionRef = useRef<AttentionVector>({ x: 0, y: 0, confidence: 0, gesture: 0, source: "pointer" })
  const stateRef = useRef({ snapshot, settings, shapeId, personaVisual, transparentBackdrop })
  const [failure, setFailure] = useState<Error | null>(null)
  const [activeShapeId, setActiveShapeId] = useState(
    () => shapeId || presenceShapeIdForAvatar(settings.avatarId),
  )

  useEffect(() => {
    stateRef.current = { snapshot, settings, shapeId, personaVisual, transparentBackdrop }
  }, [snapshot, settings, shapeId, personaVisual, transparentBackdrop])

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
    renderer.setClearColor(0x000000, 0)
    renderer.toneMapping = THREE.ReinhardToneMapping
    renderer.toneMappingExposure = 0.82
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 40)
    camera.position.set(0.55, 0.28, 5.6)
    camera.lookAt(0, 0, 0)
    const uniforms = {
      uTime: { value: 0 }, uMotion: { value: 1 }, uActivity: { value: 0 },
      uSpeech: { value: 0 }, uPixelScale: { value: 1 }, uOpacity: { value: 1 },
      uMorph: { value: lifecycleMorphTarget("idle") },
      uRestTightness: { value: lifecycleMorphTarget("idle") },
      uRestRemap: { value: 1 },
      uPhaseKind: { value: 0 },
      uGlow: { value: 1 },
      uPointScale: { value: 1 },
      uDepthSoftness: { value: 0 },
      uBreath: { value: 0 },
      uListen: { value: 0 },
      uAlertAge: { value: 4 },
      uPointer: { value: new THREE.Vector2(0, 0) },
      uPointerStrength: { value: 0 },
      uGesture: { value: 0 },
      uColor: { value: new THREE.Color(PHASE_COLOR.idle) },
      uGold: { value: new THREE.Color(0xff941f) },
      uAccent: { value: new THREE.Color(0xd4a017) },
      uGalaxy: { value: 0 },
      uGalaxyBust: { value: 0 },
      uLattice: { value: 0 },
      uSampleEnergy: { value: FIGURE_SAMPLE_ENERGY },
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
    const qualityCeiling = settings.performancePreset === "auto" ? 1.15 : density
    const initialDensity = THREE.MathUtils.clamp(
      density * personaDetail(personaVisual?.detail),
      0.35,
      qualityCeiling,
    )
    const initialId = shapeId || presenceShapeIdForAvatar(settings.avatarId)
    const system = createMorphablePresenceSystem(
      initialDensity, material, initialId, qualityCeiling,
    )
    system.setQuality(initialDensity)
    const initialSamples = system.sampleCounts()
    stage.dataset.presenceSamples = `${initialSamples.figure}/${initialSamples.field}/${initialSamples.galaxyStars}`
    const bust = system.bust
    scene.add(system.group)
    setActiveShapeId(system.currentShapeId)

    const composer = efficient ? null : new EffectComposer(renderer)
    const bloom = efficient
      ? null
      : new UnrealBloomPass(
        new THREE.Vector2(1, 1),
        0.38,
        0.2,
        0.86,
      )
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
    let framingScale = 0.98
    let framingCenterX = 0
    let framingCenterY = 0
    let framingCenterZ = 0
    let previousPhase: PresencePhase = snapshot.phase
    let alertAge = 4
    const autoQuality = new AutoPresenceQuality()
    let autoTier = autoQuality.current
    let lastFrameSample: number | undefined
    let appliedDensity = initialDensity
    let averageFrameInterval = 16.67

    const fitCurrentShape = (aspect: number) => {
      const profile = resolvePresenceShape(system.currentShapeId)
      const aPos = system.figure.geometry.getAttribute("aPos")
      const bPos = system.figure.geometry.getAttribute("bPos")
      // Union rest + engaged so idle scatter cannot crop crown/chin off look-at.
      const positions = unionPresencePositions(
        aPos.array as ArrayLike<number>,
        bPos.array as ArrayLike<number>,
      )
      const fitYaw = profile.framing?.yaw ?? PRESENCE_DEFAULT_FRAMING_YAW
      const fit = normalizedPresenceFitScale(
        positions, aspect, camera.fov, camera.position.z,
        fitYaw, profile.framing?.fitMargin ?? 0.88, profile.framing?.landmarks,
      )
      framingScale = fit.scale
      framingCenterX = fit.centerX
      framingCenterY = fit.centerY
      framingCenterZ = fit.centerZ
      const look = presenceLookAtFromFit(fit)
      camera.lookAt(look.x, look.y, look.z)
    }

    const resize = () => {
      const { width, height } = stage.getBoundingClientRect()
      const preset = stateRef.current.settings.performancePreset
      const cap = preset === "efficient" ? 1 : preset === "cinematic" ? 1.5
        : preset === "auto" ? [1, 1.25, 1.5][autoTier] : 1.25
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap))
      renderer.setSize(Math.max(1, width), Math.max(1, height), false)
      composer?.setPixelRatio(renderer.getPixelRatio())
      composer?.setSize(Math.max(1, width), Math.max(1, height))
      const aspect = Math.max(1, width) / Math.max(1, height)
      camera.aspect = aspect
      camera.fov = aspect < 0.85 ? 37 : 32
      camera.position.set(0, 0.12, aspect < 0.85 ? 6.15 : 5.6)
      fitCurrentShape(aspect)
      const personaScale = stateRef.current.personaVisual?.scale
      bust.scale.setScalar(framingScale * (personaScale && personaScale > 0 ? personaScale : 1))
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
      const frameMs = lastFrameSample === undefined ? 16.67 : time - lastFrameSample
      let baseDensity = density
      let tierChanged = false
      if (current.settings.performancePreset === "auto") {
        const tier = autoQuality.sample(time, frameMs)
        baseDensity = PRESENCE_QUALITY_DENSITIES[tier]
        tierChanged = tier !== autoTier
        autoTier = tier
      }
      const detail = personaDetail(current.personaVisual?.detail)
      const targetDensity = THREE.MathUtils.clamp(baseDensity * detail, 0.35, qualityCeiling)
      if (Math.abs(targetDensity - appliedDensity) > 0.001) {
        const counts = system.setQuality(targetDensity)
        appliedDensity = targetDensity
        stage.dataset.presenceSamples = `${counts.figure}/${counts.field}/${counts.galaxyStars}`
      }
      stage.dataset.presenceDetail = detail.toFixed(2)
      if (tierChanged) resize()
      lastFrameSample = time
      const reduced = current.settings.reducedMotion === "reduce"
        || (current.settings.reducedMotion === "system" && motionQuery.matches)
      const interval = reduced ? 100 : efficient ? 33 : 0
      if (time - lastRender < interval) return
      if (lastRender) averageFrameInterval += (time - lastRender - averageFrameInterval) * 0.08
      stage.dataset.presenceFrameMs = averageFrameInterval.toFixed(1)
      stage.dataset.presenceFps = (1000 / Math.max(1, averageFrameInterval)).toFixed(0)
      const delta = Math.min((time - lastRender) / 1000, 0.05)
      lastRender = time
      if (!reduced) animationTime += delta

      const phase = current.snapshot.phase
      const desiredShape = current.shapeId || presenceShapeIdForAvatar(current.settings.avatarId)
      // Lifecycle is phase-driven for every mounted avatar. Galaxy does not gate it.
      system.setLifecycleTarget(lifecycleMorphTarget(phase), {
        duration: reduced ? 0 : LIFECYCLE_MORPH_SECONDS,
        immediate: reduced,
      })
      if (desiredShape !== system.currentShapeId) {
        system.morphTo(desiredShape, {
          duration: reduced ? 0 : PERSONA_MORPH_SECONDS,
          immediate: reduced,
        })
        setActiveShapeId(system.currentShapeId)
        fitCurrentShape(camera.aspect)
      }
      system.tick(delta)
      stage.dataset.morph = system.morphValue().toFixed(3)
      stage.dataset.morphBlend = lifecycleMorphBlend(system.morphValue()).toFixed(3)
      stage.dataset.restTightness = String(lifecycleMorphTarget("idle"))
      stage.dataset.restIdentity = isRestPresencePhase(phase) ? "silhouette" : "engaged"
      stage.dataset.silhouetteGuard = "rfc0195"

      const activity = {
        offline: 0, idle: 0.18, listening: 0.45, thinking: 0.72,
        executing: 1, speaking: 0.68, waiting: 0.12, alert: 0.85,
        approval: 0.4, error: 0.9,
      }[phase]
      const visual = current.personaVisual
      const animation = typeof visual?.animation === "number" ? visual.animation : 1
      uniforms.uTime.value = animationTime
      uniforms.uMotion.value = reduced ? 0 : animation
      uniforms.uPhaseKind.value = PHASE_KIND[phase]
      if (phase !== previousPhase) {
        if (phase === "alert") alertAge = 0
        previousPhase = phase
      }
      if (reduced) alertAge = 4
      else alertAge = Math.min(4, alertAge + delta)
      uniforms.uAlertAge.value = alertAge
      uniforms.uBreath.value = reduced || phase !== "idle"
        ? 0
        : (0.5 + 0.5 * Math.sin(animationTime * 0.92)) * animation
      const listenTarget = phase === "listening" && !reduced ? 1 : 0
      uniforms.uListen.value += (listenTarget - uniforms.uListen.value) * Math.min(1, delta * 4)
      const shapeDef = resolvePresenceShape(system.currentShapeId)
      const liveBGlow = system.currentShapeId.endsWith("_b") && typeof visual?.glow === "number"
        ? Math.min(1.05, visual.glow * 1.18)
        : visual?.glow
      const appearance = resolveDotAppearance(shapeDef.appearance, { ...visual, glow: liveBGlow })
      uniforms.uGlow.value = appearance.glow
      const personaScale = visual?.scale && visual.scale > 0 ? visual.scale : 1
      bust.scale.setScalar(framingScale * personaScale)
      uniforms.uActivity.value += (activity - uniforms.uActivity.value)
        * (reduced ? 1 : Math.min(1, delta * 3))
      const galaxyOn = current.settings.requestedPresence === "galaxy"
      const bustShape = system.currentShapeId === "humanoid_bust" || system.currentShapeId === "portrait_humanoid"
      const rest = isRestPresencePhase(phase)
      const alive = phaseIsEngaged(phase)
      uniforms.uGalaxy.value = galaxyOn ? 1 : 0
      uniforms.uGalaxyBust.value = galaxyOn && bustShape ? 1 : 0
      // Lattice follows morph so rest (0.82) keeps motif gold; engaged is 1.0.
      uniforms.uLattice.value = system.morphValue()
      system.setGalaxy(galaxyOn)
      system.syncStars(animationTime, reduced ? 0 : 1)
      // Alpha stays 0 now that the canvas is unmasked and chat chrome no longer
      // backdrop-filters it. An opaque black clear is what failed WebView2 tiles paint.
      renderer.setClearColor(0x000000, 0)
      const meterNow = galaxyOn && (phase === "speaking" || phase === "listening") ? readVoiceMeter() : null
      const speechLevel = !reduced && meterNow && meterNow.attached && meterNow.kind === "tts" && phase === "speaking"
        ? THREE.MathUtils.clamp(meterNow.level, 0, 1)
        : 0
      uniforms.uSpeech.value = system.morphValue() > 0.45 ? speechLevel : 0
      const bloomPass = resolvePresenceBloom({
        appearance,
        performancePreset: current.settings.performancePreset,
        autoTier,
        rest,
      })
      if (bloom) {
        bloom.strength = bloomPass.strength
        bloom.radius = bloomPass.radius
        bloom.threshold = bloomPass.threshold
        bloom.enabled = bloomPass.enabled
      }
      stage.dataset.bloomEnabled = bloomPass.enabled ? "1" : "0"
      uniforms.uOpacity.value = phase === "offline" ? 0.35 : phase === "waiting" ? 0.72 : phase === "error" ? 0.92 : 1
      const warning = phase === "alert" || phase === "error" || phase === "offline" || phase === "approval"
      const safeAccent = motifSafeAccentHex(visual?.accentColor, visual?.orbColor)
      if (galaxyOn && bustShape) {
        color.setHex(alive ? 0x6fd0ff : 0x8ec4de)
        uniforms.uGold.value.setHex(alive ? 0xff8a1a : 0x24303a)
        uniforms.uAccent.value.set(visual?.accentColor || "#9fd4ea")
      } else if (!warning && bustShape) {
        // The restored Jarvis humanoid has its own art direction. Persona
        // colours belong to mythic shapes and must not recolour this shell.
        color.setHex(0x1ec8ff)
        uniforms.uGold.value.setHex(0xff951f)
        uniforms.uAccent.value.setHex(0x8ceaff)
      } else if (!warning && visual?.orbColor) {
        color.set(visual.orbColor)
        uniforms.uGold.value.set(safeAccent)
        uniforms.uAccent.value.set(safeAccent)
      } else {
        color.setHex(PHASE_COLOR[phase])
        uniforms.uGold.value.setHex(
          phase === "alert" || phase === "error" ? 0xff543b : phase === "offline" ? 0x607580 : phase === "approval" ? 0xffe7a3 : 0xff941f,
        )
        uniforms.uAccent.value.copy(uniforms.uGold.value)
      }
      uniforms.uColor.value.lerp(color, reduced ? 1 : 0.12)

      const framing = shapeDef.framing
      uniforms.uPointScale.value = appearance.pointScale
      uniforms.uDepthSoftness.value = appearance.depthSoftness
      const baseYaw = framing?.yaw ?? PRESENCE_DEFAULT_FRAMING_YAW
      const basePos = framing?.position ?? [0, 0.08, 0]
      // Cancel yaw-frame AABB center in parent space (Three.js T*R*S — same frame as fit).
      const fitScale = framingScale * personaScale
      const yawOffset = presenceFitYawFrameOffset(
        { centerX: framingCenterX, centerY: framingCenterY, centerZ: framingCenterZ },
        fitScale,
      )
      const framedX = basePos[0] + yawOffset.x
      const framedY = basePos[1] + yawOffset.y
      const framedZ = basePos[2] + yawOffset.z
      const mode = current.settings.attentionMode
      const follow = !reduced && mode !== "off"
      const att = attentionRef.current
      const morphNow = system.morphValue()
      const volumetricPersona = system.currentShapeId.startsWith("portrait_") && system.currentShapeId.endsWith("_b")
      const yawGain = THREE.MathUtils.degToRad(volumetricPersona ? 18 : 3.2)
      const pitchGain = THREE.MathUtils.degToRad(volumetricPersona ? 9 : 1.35)
      const idleMotion = reduced ? 0 : Math.max(0, animation)
      const hoverX = volumetricPersona ? Math.sin(animationTime * 0.48) * 0.035 * idleMotion : 0
      const hoverY = Math.sin(animationTime * 1.05) * (volumetricPersona ? 0.032 : 0.016) * idleMotion
      const breathScale = volumetricPersona ? 1 + Math.sin(animationTime * 0.92) * 0.009 * idleMotion : 1
      bust.scale.setScalar(fitScale * breathScale)
      const rotationLerp = 1 - Math.exp(-delta * 3.4)
      if (!follow) {
        bust.rotation.set(0, baseYaw, 0)
        bust.position.set(
          framedX + hoverX,
          framedY + hoverY,
          framedZ,
        )
        uniforms.uPointerStrength.value = 0
        uniforms.uGesture.value = 0
      } else {
        const ax = att.x
        const ay = att.y
        const yawFollow = morphNow
        bust.rotation.y += ((baseYaw + ax * yawGain * yawFollow) - bust.rotation.y) * rotationLerp
        bust.rotation.x += ((-ay * pitchGain * yawFollow) - bust.rotation.x) * rotationLerp
        bust.position.x = framedX + hoverX
        bust.position.z = framedZ
        bust.position.y = framedY + hoverY
        uniforms.uPointer.value.set(ax * 1.45, 0.12 - ay * 1.35)
        const pointerTarget = THREE.MathUtils.clamp(att.confidence, 0, 1) * restAttractGain(morphNow)
        uniforms.uPointerStrength.value += (pointerTarget - uniforms.uPointerStrength.value)
          * Math.min(1, delta * 5)
        const gestureTarget = att.source === "camera" ? att.gesture : 0
        uniforms.uGesture.value += (gestureTarget - uniforms.uGesture.value) * Math.min(1, delta * 4)
      }
      stage.dataset.presenceYaw = bust.rotation.y.toFixed(3)
      stage.dataset.presencePitch = bust.rotation.x.toFixed(3)
      stage.dataset.presenceMotion = String(idleMotion)
      try {
        if (composer && bloomPass.enabled) composer.render()
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
  // Shape and phase update inside the frame loop — remounting would drop the cloud.
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.performancePreset])

  if (failure) throw failure
  const stageName = isRestPresencePhase(snapshot.phase) ? "idle" : "engaged"
  return (
    <div
      ref={stageRef}
      className={className}
      data-phase={snapshot.phase}
      data-performance-preset={settings.performancePreset}
      data-attention-mode={settings.attentionMode}
      data-presence-shape={activeShapeId}
      data-presence-samples=""
      data-lifecycle="on"
      data-lifecycle-stage={stageName}
      data-galaxy={settings.requestedPresence === "galaxy" ? "true" : "false"}
      role="img"
      aria-label={ariaLabel}
      style={style}
    >
      <canvas ref={canvasRef} aria-hidden="true" />
      {children}
    </div>
  )
}
