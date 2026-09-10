import type { AttentionMode } from "./presenceTypes"
import { createPresenceCameraTracker, type PresenceCameraTracker } from "./presenceCameraTrack"

export type AttentionVector = {
  x: number
  y: number
  confidence: number
  source: "pointer" | "camera"
}

export type PresenceAttentionController = {
  sample(): AttentionVector
  dispose(): void
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function lerp(current: number, target: number, alpha: number): number {
  return current + (target - current) * alpha
}

type ControllerOptions = {
  getMode: () => AttentionMode
  getReducedMotion: () => boolean
  /** When set, pointer coords are normalized to this element; otherwise the viewport. */
  anchor?: () => HTMLElement | null
}

export function createPresenceAttentionController(
  options: ControllerOptions,
): PresenceAttentionController {
  const pointerTarget = { x: 0, y: 0 }
  const pointerSmooth = { x: 0, y: 0 }
  const cameraTarget = { x: 0, y: 0, confidence: 0 }
  const cameraSmooth = { x: 0, y: 0, confidence: 0 }

  let stream: MediaStream | null = null
  let video: HTMLVideoElement | null = null
  let tracker: PresenceCameraTracker | null = null
  let trackFrame = 0
  let cameraModeActive = false
  let cameraUsable = false
  let disposed = false

  const onPointerMove = (event: PointerEvent) => {
    const anchor = options.anchor?.()
    if (anchor) {
      const rect = anchor.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      pointerTarget.x = clamp(((event.clientX - rect.left) / rect.width) * 2 - 1, -1, 1)
      pointerTarget.y = clamp(((event.clientY - rect.top) / rect.height) * 2 - 1, -1, 1)
      return
    }
    pointerTarget.x = clamp((event.clientX / Math.max(1, window.innerWidth)) * 2 - 1, -1, 1)
    pointerTarget.y = clamp((event.clientY / Math.max(1, window.innerHeight)) * 2 - 1, -1, 1)
  }

  window.addEventListener("pointermove", onPointerMove, { passive: true })

  const stopCamera = () => {
    if (trackFrame) window.cancelAnimationFrame(trackFrame)
    trackFrame = 0
    tracker?.dispose()
    tracker = null
    cameraUsable = false
    cameraModeActive = false
    cameraTarget.x = 0
    cameraTarget.y = 0
    cameraTarget.confidence = 0
    if (video) {
      video.pause()
      video.srcObject = null
      video.remove()
      video = null
    }
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  const runTrackingLoop = () => {
    if (!tracker || !video || disposed) return
    const tick = (time: number) => {
      if (disposed || !tracker || !video) return
      trackFrame = window.requestAnimationFrame(tick)
      tracker.tick(time)
      const sample = tracker.read()
      cameraTarget.x = sample.x
      cameraTarget.y = sample.y
      cameraTarget.confidence = sample.confidence
    }
    trackFrame = window.requestAnimationFrame(tick)
  }

  const startCamera = async () => {
    if (cameraModeActive || disposed) return
    cameraModeActive = true
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraUsable = false
      return
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      })
      video = document.createElement("video")
      video.playsInline = true
      video.muted = true
      video.autoplay = true
      video.style.position = "fixed"
      video.style.width = "1px"
      video.style.height = "1px"
      video.style.opacity = "0"
      video.style.pointerEvents = "none"
      video.setAttribute("aria-hidden", "true")
      document.body.appendChild(video)
      video.srcObject = stream
      await video.play()
      tracker = await createPresenceCameraTracker(video)
      if (tracker) {
        cameraUsable = true
        runTrackingLoop()
      } else {
        cameraUsable = false
        stopCamera()
      }
    } catch {
      cameraUsable = false
      stopCamera()
    }
  }

  const syncCameraLifecycle = () => {
    if (disposed || options.getReducedMotion()) {
      stopCamera()
      return
    }
    const mode = options.getMode()
    if (mode === "camera") {
      if (!cameraModeActive) void startCamera()
      return
    }
    stopCamera()
  }

  const modePoll = window.setInterval(syncCameraLifecycle, 400)
  syncCameraLifecycle()

  return {
    sample(): AttentionVector {
      syncCameraLifecycle()
      const reduced = options.getReducedMotion()
      const mode = options.getMode()
      if (reduced || mode === "off") {
        pointerSmooth.x = 0
        pointerSmooth.y = 0
        cameraSmooth.x = 0
        cameraSmooth.y = 0
        cameraSmooth.confidence = 0
        return { x: 0, y: 0, confidence: 0, source: "pointer" }
      }

      pointerSmooth.x = lerp(pointerSmooth.x, pointerTarget.x, 0.26)
      pointerSmooth.y = lerp(pointerSmooth.y, pointerTarget.y, 0.26)
      cameraSmooth.x = lerp(cameraSmooth.x, cameraTarget.x, 0.22)
      cameraSmooth.y = lerp(cameraSmooth.y, cameraTarget.y, 0.22)
      cameraSmooth.confidence = lerp(cameraSmooth.confidence, cameraTarget.confidence, 0.24)

      if (mode === "camera" && cameraUsable && cameraSmooth.confidence > 0.3) {
        return {
          x: cameraSmooth.x,
          y: cameraSmooth.y,
          confidence: cameraSmooth.confidence,
          source: "camera",
        }
      }

      return {
        x: pointerSmooth.x,
        y: pointerSmooth.y,
        confidence: 1,
        source: "pointer",
      }
    },
    dispose() {
      disposed = true
      window.clearInterval(modePoll)
      window.removeEventListener("pointermove", onPointerMove)
      stopCamera()
    },
  }
}

/** Shared yaw/pitch offsets for CSS-based presence surfaces. */
export function attentionCssTransform(x: number, y: number, scale = 1): string {
  const tx = x * 18 * scale
  const ty = y * 12 * scale
  const ry = x * 14 * scale
  const rx = -y * 8 * scale
  return `translate(calc(-50% + ${tx}px), calc(-50% + ${ty}px)) rotateY(${ry}deg) rotateX(${rx}deg)`
}
