/** Local webcam attention — MediaPipe face landmarks first, FaceDetector fallback. */

export type CameraTrackSample = {
  x: number
  y: number
  confidence: number
}

export type PresenceCameraTracker = {
  /** Call each frame (or ~30fps) while video is playing. */
  tick(timestampMs: number): void
  read(): CameraTrackSample
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

/** Morphix / holistic-style gaze: nose-led blend with eye-line center (mirrored for user camera). */
function landmarksToVector(
  landmarks: Array<{ x: number; y: number }>,
): CameraTrackSample {
  const nose = landmarks[1] ?? landmarks[0]
  const left = landmarks[33] ?? nose
  const right = landmarks[263] ?? nose
  const eyeCx = (left.x + right.x) * 0.5
  const eyeCy = (left.y + right.y) * 0.5
  const gx = nose.x * 0.62 + eyeCx * 0.38
  const gy = nose.y * 0.5 + eyeCy * 0.5
  return {
    x: clamp((0.5 - gx) * 2.35, -1, 1),
    y: clamp((gy - 0.5) * 2.1, -1, 1),
    confidence: 1,
  }
}

async function createMediaPipeTracker(video: HTMLVideoElement): Promise<PresenceCameraTracker | null> {
  try {
    const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision")
    const vision = await FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm",
    )
    const landmarker = await FaceLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath:
          "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        delegate: "GPU",
      },
      runningMode: "VIDEO",
      numFaces: 1,
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: false,
    })

    let last: CameraTrackSample = { x: 0, y: 0, confidence: 0 }

    return {
      tick(timestampMs: number) {
        if (video.readyState < 2) return
        const result = landmarker.detectForVideo(video, timestampMs)
        const face = result.faceLandmarks?.[0]
        if (!face?.length) {
          last = { x: last.x, y: last.y, confidence: 0 }
          return
        }
        last = landmarksToVector(face)
      },
      read() {
        return last
      },
      dispose() {
        landmarker.close()
      },
    }
  } catch (error) {
    console.warn("MediaPipe face landmarker unavailable; trying FaceDetector.", error)
    return null
  }
}

function createFaceDetectorTracker(video: HTMLVideoElement): PresenceCameraTracker | null {
  if (!window.FaceDetector) return null
  const detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 })
  let last: CameraTrackSample = { x: 0, y: 0, confidence: 0 }

  return {
    tick() {
      void (async () => {
        if (video.readyState < 2) return
        try {
          const faces = await detector.detect(video)
          const face = faces[0]
          if (!face) {
            last = { x: last.x, y: last.y, confidence: 0 }
            return
          }
          const box = face.boundingBox
          const cx = (box.x + box.width * 0.5) / Math.max(1, video.videoWidth)
          const cy = (box.y + box.height * 0.5) / Math.max(1, video.videoHeight)
          last = {
            x: clamp((0.5 - cx) * 2, -1, 1),
            y: clamp((cy - 0.5) * 2, -1, 1),
            confidence: 0.85,
          }
        } catch {
          last = { x: 0, y: 0, confidence: 0 }
        }
      })()
    },
    read() {
      return last
    },
    dispose() {
      /* FaceDetector has no explicit dispose */
    },
  }
}

export async function createPresenceCameraTracker(
  video: HTMLVideoElement,
): Promise<PresenceCameraTracker | null> {
  const mp = await createMediaPipeTracker(video)
  if (mp) return mp
  return createFaceDetectorTracker(video)
}
