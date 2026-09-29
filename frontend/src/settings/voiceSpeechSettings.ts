import { api } from "../api"

export type SttBackendOption =
  | "auto"
  | "faster-whisper"
  | "whisper.cpp"
  | "openai-whisper"
  | "voicestudio"
  | "windows-sapi"

export type TtsEngineOption =
  | "auto"
  | "kokoro"
  | "voicestudio"
  | "pocket_tts"
  | "chatterbox_multilingual_v3"
  | "chatterbox_turbo"
  | "external"

export type VoiceSpeechSettings = {
  stt_backend: SttBackendOption
  whisper_model: string
  voicestudio_url: string
  voicestudio_autostart: boolean
  tts_engine: TtsEngineOption
}

export const DEFAULT_VOICE_SPEECH_SETTINGS: VoiceSpeechSettings = {
  stt_backend: "auto",
  whisper_model: "",
  voicestudio_url: "http://127.0.0.1:3900",
  voicestudio_autostart: false,
  tts_engine: "auto",
}

function normalizeVoiceSpeech(raw: Record<string, unknown> | undefined): VoiceSpeechSettings {
  const voice = raw?.voice && typeof raw.voice === "object" ? (raw.voice as Record<string, unknown>) : {}
  const tts = raw?.tts && typeof raw.tts === "object" ? (raw.tts as Record<string, unknown>) : {}
  const sttRaw = voice.stt_backend ?? voice.sttBackend
  const engineRaw = tts.engine ?? tts.engine_id
  const stt =
    typeof sttRaw === "string" && sttRaw.trim()
      ? (sttRaw.trim() as SttBackendOption)
      : DEFAULT_VOICE_SPEECH_SETTINGS.stt_backend
  const engine =
    typeof engineRaw === "string" && engineRaw.trim()
      ? (engineRaw.trim() as TtsEngineOption)
      : DEFAULT_VOICE_SPEECH_SETTINGS.tts_engine
  return {
    stt_backend: stt,
    whisper_model: typeof voice.whisper_model === "string" ? voice.whisper_model : "",
    voicestudio_url:
      typeof voice.voicestudio_url === "string" && voice.voicestudio_url.trim()
        ? voice.voicestudio_url.trim()
        : DEFAULT_VOICE_SPEECH_SETTINGS.voicestudio_url,
    voicestudio_autostart: voice.voicestudio_autostart === true,
    tts_engine: engine,
  }
}

export async function fetchVoiceSpeechSettings(): Promise<VoiceSpeechSettings> {
  const response = await api<Record<string, unknown>>("/api/settings")
  return normalizeVoiceSpeech(response)
}

export async function saveVoiceSpeechSettings(patch: Partial<VoiceSpeechSettings>): Promise<void> {
  const body: Record<string, unknown> = {}
  if (patch.stt_backend !== undefined) body.voice_stt_backend = patch.stt_backend
  if (patch.whisper_model !== undefined) body.voice_whisper_model = patch.whisper_model
  if (patch.voicestudio_url !== undefined) body.voice_voicestudio_url = patch.voicestudio_url
  if (patch.voicestudio_autostart !== undefined) body.voice_voicestudio_autostart = patch.voicestudio_autostart
  if (patch.tts_engine !== undefined) body.tts_engine = patch.tts_engine
  if (patch.stt_backend === "voicestudio" && patch.voicestudio_autostart === undefined) {
    body.voice_voicestudio_autostart = true
  }
  if (patch.tts_engine === "voicestudio" && patch.voicestudio_autostart === undefined) {
    body.voice_voicestudio_autostart = true
  }
  if (Object.keys(body).length === 0) return
  await api("/api/settings", { method: "PUT", body: JSON.stringify(body) })
}
