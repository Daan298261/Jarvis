import { fetchAudio } from "../api"
import { getActiveVoiceProfileId } from "./voiceProfiles"

const MAX_SPEAK_CHARS = 800

type SpeakOpts = {
  onStart?: () => void
  onEnd?: () => void
}

let activeAudio: HTMLAudioElement | null = null
let activeUrl: string | null = null

function clearActiveAudio(): void {
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

/** Stop any in-flight chat TTS (barge-in on new user send). */
export function stopChatTts(): void {
  clearActiveAudio()
}

/**
 * Speak assistant text without blocking UI. Failures are swallowed so text stays visible.
 * Returns a promise that resolves when playback ends or fails.
 */
export async function speakChatReply(text: string, opts?: SpeakOpts): Promise<void> {
  const trimmed = text.trim()
  if (!trimmed) return

  stopChatTts()
  opts?.onStart?.()

  try {
    const payload: { text: string; voice_profile_id?: string } = {
      text: trimmed.slice(0, MAX_SPEAK_CHARS),
    }
    const voiceProfileId = getActiveVoiceProfileId()
    if (voiceProfileId) payload.voice_profile_id = voiceProfileId

    const blob = await fetchAudio("/api/voice/speak", {
      method: "POST",
      body: JSON.stringify(payload),
    })
    const url = URL.createObjectURL(blob)
    activeUrl = url
    const audio = new Audio(url)
    activeAudio = audio
    await new Promise<void>((resolve) => {
      const finish = () => {
        clearActiveAudio()
        opts?.onEnd?.()
        resolve()
      }
      audio.onended = finish
      audio.onerror = finish
      void audio.play().catch(finish)
    })
  } catch {
    clearActiveAudio()
    opts?.onEnd?.()
  }
}
