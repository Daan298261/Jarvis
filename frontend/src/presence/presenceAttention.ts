import type { AttentionMode } from "./presenceTypes"

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

type FaceDetectorLike = {
  detect: (source: CanvasImageSource) => Promise<Array<{ boundingBox: DOMRectReadOnly }>>
}

type FaceDetectorCtor = new (options?: { fastMode?: boolean; maxDetectedFaces?: number }) => FaceDetectorLike

declare global {
  interface Window {
    FaceDetector?: FaceDetectorCtor
  }
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
  let detector: FaceDetectorLike | null = null
  let detectTimer = 0
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
    window.clearInterval(detectTimer)
    detectTimer = 0
    detector = null
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

  const detectFace = async () => {
    if (!video || !detector || video.readyState < 2) return
    try {
      const faces = await detector.detect(video)
      const face = faces[0]
      if (!face) {
        cameraTarget.confidence = 0
        return
      }
      const box = face.boundingBox
      const cx = (box.x + box.width * 0.5) / Math.max(1, video.videoWidth)
      const cy = (box.y + box.height * 0.5) / Math.max(1, video.videoHeight)
      cameraTarget.x = clamp((cx - 0.5) * 2, -1, 1)
      cameraTarget.y = clamp((cy - 0.5) * 2, -1, 1)
      cameraTarget.confidence = 1
    } catch {
      cameraTarget.confidence = 0
    }
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
        video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 240 } },
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
      if (window.FaceDetector) {
        detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 })
        cameraUsable = true
        detectTimer = window.setInterval(() => {
          void detectFace()
        }, 120)
      } else {
        cameraUsable = false
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

      pointerSmooth.x = lerp(pointerSmooth.x, pointerTarget.x, 0.22)
      pointerSmooth.y = lerp(pointerSmooth.y, pointerTarget.y, 0.22)
      cameraSmooth.x = lerp(cameraSmooth.x, cameraTarget.x, 0.18)
      cameraSmooth.y = lerp(cameraSmooth.y, cameraTarget.y, 0.18)
      cameraSmooth.confidence = lerp(cameraSmooth.confidence, cameraTarget.confidence, 0.2)

      if (mode === "camera" && cameraUsable && cameraSmooth.confidence > 0.35) {
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
  const tx = x * 14 * scale
  const ty = y * 9 * scale
  const ry = x * 10 * scale
  const rx = -y * 6 * scale
  return `translate(calc(-50% + ${tx}px), calc(-50% + ${ty}px)) rotateY(${ry}deg) rotateX(${rx}deg)`
}
