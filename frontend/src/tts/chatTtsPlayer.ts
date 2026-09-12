import { fetchAudio } from "../api"
import { getActiveVoiceProfileId } from "./voiceProfiles"

const MAX_SPEAK_CHARS = 800

type SpeakOpts = {
  onStart?: () => void
  onEnd?: () => void
  append?: boolean
}

type QueuedSpeech = {
  text: string
  opts?: SpeakOpts
  resolve: () => void
}

let activeAudio: HTMLAudioElement | null = null
let activeUrl: string | null = null
let activeFinish: (() => void) | null = null
let playbackEpoch = 0
let pumpRunning = false
const speechQueue: QueuedSpeech[] = []

function releaseMedia(): void {
  if (activeAudio) {
    activeAudio.pause()
    activeAudio.onended = null
    activeAudio.onerror = null
    activeAudio = null
  }
  if (activeUrl) {
    URL.revokeObjectURL(activeUrl)
    activeUrl = null
  }
}

/** Stop active and queued chat speech immediately (barge-in). */
export function stopChatTts(): void {
  playbackEpoch += 1
  while (speechQueue.length) speechQueue.shift()?.resolve()
  const finish = activeFinish
  activeFinish = null
  releaseMedia()
  finish?.()
}

async function play(item: QueuedSpeech, epoch: number): Promise<void> {
  item.opts?.onStart?.()
  try {
    const payload: { text: string; voice_profile_id?: string } = {
      text: item.text.slice(0, MAX_SPEAK_CHARS),
    }
    const voiceProfileId = getActiveVoiceProfileId()
    if (voiceProfileId) payload.voice_profile_id = voiceProfileId

    const blob = await fetchAudio("/api/voice/speak", {
      method: "POST",
      body: JSON.stringify(payload),
    })
    if (epoch !== playbackEpoch) return

    const url = URL.createObjectURL(blob)
    activeUrl = url
    const audio = new Audio(url)
    activeAudio = audio
    await new Promise<void>((resolve) => {
      let finished = false
      const finish = () => {
        if (finished) return
        finished = true
        activeFinish = null
        releaseMedia()
        resolve()
      }
      activeFinish = finish
      audio.onended = finish
      audio.onerror = finish
      void audio.play().catch(finish)
    })
  } catch {
    releaseMedia()
  } finally {
    item.opts?.onEnd?.()
    item.resolve()
  }
}

async function pump(epoch: number): Promise<void> {
  if (pumpRunning) return
  pumpRunning = true
  try {
    while (speechQueue.length && epoch === playbackEpoch) {
      const item = speechQueue.shift()
      if (item) await play(item, epoch)
    }
  } finally {
    pumpRunning = false
    if (speechQueue.length) void pump(playbackEpoch)
  }
}

/** Queue a stable speech chunk; append=true preserves any phrase already playing. */
export function queueChatSpeech(text: string, opts?: SpeakOpts): Promise<void> {
  const trimmed = text.trim()
  if (!trimmed) return Promise.resolve()
  if (!opts?.append) stopChatTts()
  const epoch = playbackEpoch
  return new Promise<void>((resolve) => {
    speechQueue.push({ text: trimmed, opts, resolve })
    void pump(epoch)
  })
}

/** Speak a complete reply, replacing any previous playback. */
export function speakChatReply(text: string, opts?: SpeakOpts): Promise<void> {
  return queueChatSpeech(text, { ...opts, append: false })
}

/** Return only text not already spoken as an early stable prefix. */
export function unspokenRemainder(fullText: string, spokenPrefix: string): string {
  const full = fullText.trim()
  const prefix = spokenPrefix.trim()
  if (!prefix) return full
  if (full.startsWith(prefix)) return full.slice(prefix.length).trim()
  return full
}
