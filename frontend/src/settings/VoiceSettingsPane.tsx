import { useEffect, useState } from "react"
import { VoiceProfilePicker } from "../tts/VoiceProfilePicker"
import {
  readTtsBootstrap,
  refreshTtsFromBackend,
  TTS_SETTINGS_CHANGED_EVENT,
  updateTtsSettings,
  type TtsSettings,
} from "../tts/chatTtsSettings"
import {
  DEFAULT_VOICE_SPEECH_SETTINGS,
  fetchVoiceSpeechSettings,
  saveVoiceSpeechSettings,
  type SttBackendOption,
  type TtsEngineOption,
  type VoiceSpeechSettings,
} from "./voiceSpeechSettings"

const STT_OPTIONS: { value: SttBackendOption; label: string }[] = [
  { value: "auto", label: "Auto (local Whisper when installed, else Windows SAPI)" },
  { value: "faster-whisper", label: "faster-whisper (models/whisper/)" },
  { value: "voicestudio", label: "VoiceStudio local API" },
  { value: "windows-sapi", label: "Windows SAPI" },
  { value: "whisper.cpp", label: "whisper.cpp CLI" },
  { value: "openai-whisper", label: "openai-whisper" },
]

const TTS_ENGINE_OPTIONS: { value: TtsEngineOption; label: string }[] = [
  { value: "auto", label: "Auto (active voice profile decides)" },
  { value: "kokoro", label: "Kokoro-82M" },
  { value: "voicestudio", label: "VoiceStudio" },
  { value: "pocket_tts", label: "Pocket TTS (CPU)" },
  { value: "chatterbox_turbo", label: "Chatterbox Turbo" },
  { value: "chatterbox_multilingual_v3", label: "Chatterbox Multilingual" },
  { value: "external", label: "External" },
]

export function VoiceSettingsPane() {
  const [speakChatReplies, setSpeakChatReplies] = useState(() => readTtsBootstrap().speak_chat_replies)
  const [speech, setSpeech] = useState<VoiceSpeechSettings>(DEFAULT_VOICE_SPEECH_SETTINGS)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const onChanged = (event: Event) => {
      const custom = event as CustomEvent<TtsSettings>
      setSpeakChatReplies(custom.detail.speak_chat_replies)
    }
    window.addEventListener(TTS_SETTINGS_CHANGED_EVENT, onChanged)
    refreshTtsFromBackend()
      .then((tts) => setSpeakChatReplies(tts.speak_chat_replies))
      .catch(() => undefined)
    fetchVoiceSpeechSettings()
      .then(setSpeech)
      .catch(() => undefined)
    return () => window.removeEventListener(TTS_SETTINGS_CHANGED_EVENT, onChanged)
  }, [])

  const persistSpeech = async (patch: Partial<VoiceSpeechSettings>) => {
    const next = { ...speech, ...patch }
    setSpeech(next)
    setSaving(true)
    try {
      await saveVoiceSpeechSettings(patch)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card grid settings-pane-card">
      <h2>Voice</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Jarvis speaks with local engines (Kokoro by default). You can also route speech through VoiceStudio or
        Pocket TTS, and choose a speech-to-text backend for microphone uploads.
      </p>
      <VoiceProfilePicker />

      <label className="row" style={{ marginTop: 12 }}>
        <input
          type="checkbox"
          checked={speakChatReplies}
          onChange={(e) => {
            const enabled = e.target.checked
            setSpeakChatReplies(enabled)
            void updateTtsSettings({ speak_chat_replies: enabled })
          }}
        />
        <strong>Speak chat replies</strong>
      </label>

      <h3 style={{ marginTop: 20, marginBottom: 8 }}>Speech-to-text</h3>
      <label className="grid" style={{ gap: 6 }}>
        <span>STT backend</span>
        <select
          value={speech.stt_backend}
          disabled={saving}
          onChange={(e) => void persistSpeech({ stt_backend: e.target.value as SttBackendOption })}
        >
          {STT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label className="grid" style={{ gap: 6, marginTop: 10 }}>
        <span>Whisper model path or id (optional)</span>
        <input
          type="text"
          value={speech.whisper_model}
          disabled={saving}
          placeholder="models/whisper/base or Systran/faster-whisper-base"
          onChange={(e) => setSpeech((prev) => ({ ...prev, whisper_model: e.target.value }))}
          onBlur={() => void persistSpeech({ whisper_model: speech.whisper_model.trim() })}
        />
      </label>

      <h3 style={{ marginTop: 20, marginBottom: 8 }}>VoiceStudio</h3>
      <label className="grid" style={{ gap: 6 }}>
        <span>Local API base URL</span>
        <input
          type="url"
          value={speech.voicestudio_url}
          disabled={saving}
          onChange={(e) => setSpeech((prev) => ({ ...prev, voicestudio_url: e.target.value }))}
          onBlur={() => void persistSpeech({ voicestudio_url: speech.voicestudio_url.trim() })}
        />
      </label>
      <p className="lede" style={{ margin: "8px 0 0", fontSize: 13 }}>
        Run debpalash/VoiceStudio locally (default port 3900). Jarvis uses OpenAI-compatible{" "}
        <code>/v1/audio/speech</code> and <code>/v1/audio/transcriptions</code>. Set{" "}
        <code>JARVIS_VOICESTUDIO_API_KEY</code> when the server requires a bearer token.
      </p>

      <h3 style={{ marginTop: 20, marginBottom: 8 }}>TTS engine preference</h3>
      <label className="grid" style={{ gap: 6 }}>
        <span>Default engine hint (profile still wins when set)</span>
        <select
          value={speech.tts_engine}
          disabled={saving}
          onChange={(e) => void persistSpeech({ tts_engine: e.target.value as TtsEngineOption })}
        >
          {TTS_ENGINE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <p className="lede" style={{ margin: "12px 0 0", fontSize: 13 }}>
        {saving ? "Saving…" : "Installer optional tasks download Kokoro, Persona voices, Whisper, VoiceStudio clone, and Pocket TTS."}
      </p>
    </div>
  )
}
