export type VoiceMeterKind = "tts" | "mic"

export type VoiceMeter = {
  attached: boolean
  level: number
  bins: Uint8Array | null
  kind: VoiceMeterKind | null
}

let context: AudioContext | null = null
let analyser: AnalyserNode | null = null
let source: AudioNode | null = null
let kind: VoiceMeterKind | null = null
const bins = new Uint8Array(64)

function ensureContext(): AudioContext {
  if (!context) context = new AudioContext()
  void context.resume().catch(() => undefined)
  return context
}

function disconnectCurrent(): void {
  try {
    source?.disconnect()
  } catch {
    // Already disconnected.
  }
  try {
    analyser?.disconnect()
  } catch {
    // Already disconnected.
  }
  source = null
  analyser = null
  kind = null
}

function attach(node: AudioNode, next: VoiceMeterKind, monitor: boolean): boolean {
  disconnectCurrent()
  try {
    const ctx = ensureContext()
    const nextAnalyser = ctx.createAnalyser()
    nextAnalyser.fftSize = 128
    nextAnalyser.smoothingTimeConstant = 0.82
    node.connect(nextAnalyser)
    if (monitor) nextAnalyser.connect(ctx.destination)
    source = node
    analyser = nextAnalyser
    kind = next
    return true
  } catch {
    disconnectCurrent()
    return false
  }
}

/** Tap TTS playback. Failure leaves the meter detached; playback still reaches the speakers. */
export function attachPlaybackAnalyser(audio: HTMLAudioElement): boolean {
  try {
    const ctx = ensureContext()
    const elementSource = ctx.createMediaElementSource(audio)
    const ok = attach(elementSource, "tts", true)
    if (!ok) {
      try {
        elementSource.connect(ctx.destination)
      } catch {
        // Capture failed before the element was taken over.
      }
    }
    return ok
  } catch {
    return false
  }
}

/** Tap an open microphone. The stream is not routed to the speakers. */
export function attachStreamAnalyser(stream: MediaStream): boolean {
  try {
    const ctx = ensureContext()
    return attach(ctx.createMediaStreamSource(stream), "mic", false)
  } catch {
    disconnectCurrent()
    return false
  }
}

export function detachVoiceAnalyser(): void {
  disconnectCurrent()
}

export function readVoiceMeter(): VoiceMeter {
  if (!analyser || !kind) return { attached: false, level: 0, bins: null, kind: null }
  analyser.getByteFrequencyData(bins)
  let sum = 0
  for (let i = 0; i < bins.length; i++) sum += bins[i]
  return {
    attached: true,
    level: sum / (bins.length * 255),
    bins,
    kind,
  }
}
