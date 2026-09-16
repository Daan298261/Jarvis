import { useEffect, useState } from "react"
import { VoiceProfilePicker } from "../tts/VoiceProfilePicker"
import {
  readTtsBootstrap,
  refreshTtsFromBackend,
  TTS_SETTINGS_CHANGED_EVENT,
  updateTtsSettings,
  type TtsSettings,
} from "../tts/chatTtsSettings"

export function VoiceSettingsPane() {
  const [speakChatReplies, setSpeakChatReplies] = useState(() => readTtsBootstrap().speak_chat_replies)

  useEffect(() => {
    const onChanged = (event: Event) => {
      const custom = event as CustomEvent<TtsSettings>
      setSpeakChatReplies(custom.detail.speak_chat_replies)
    }
    window.addEventListener(TTS_SETTINGS_CHANGED_EVENT, onChanged)
    refreshTtsFromBackend()
      .then((tts) => setSpeakChatReplies(tts.speak_chat_replies))
      .catch(() => undefined)
    return () => window.removeEventListener(TTS_SETTINGS_CHANGED_EVENT, onChanged)
  }, [])

  return (
    <div className="card grid settings-pane-card">
      <h2>Voice</h2>
      <p className="lede" style={{ margin: "0 0 12px" }}>
        Jarvis speaks typed chat replies with local Kokoro TTS (natural British household voice).
        Windows SAPI is an explicit baseline choice, never a silent neural fallback. Text always
        appears even when speech is off or TTS fails.
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
      <p className="lede" style={{ margin: 0, fontSize: 13 }}>
        Spoken replies use the active voice profile and universal Jarvis persona pack (backend injection — RFC-0061/0062 D1/D2).
        You can also mute speech from the chat composer without opening Settings.
      </p>
    </div>
  )
}
