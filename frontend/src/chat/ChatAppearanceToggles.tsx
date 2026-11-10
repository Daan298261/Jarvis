import { useChatBackground, useChatCompact } from "./chatAppearance"

export function ChatAppearanceToggles() {
  const [chatCompact, setChatCompact] = useChatCompact()
  const [chatBackground, setChatBackground] = useChatBackground()
  return (
    <>
      <button type="button" className="hud-icon-btn hud-chat-compact-toggle"
        aria-pressed={chatCompact} onClick={() => setChatCompact(!chatCompact)}
        title="Compact chat keeps the conversation in a narrow column; off restores the classic wide layout">
        Compact chat: {chatCompact ? "On" : "Off"}
      </button>
      <button type="button" className="hud-icon-btn hud-chat-background-toggle"
        disabled={!chatCompact}
        aria-pressed={chatBackground} onClick={() => setChatBackground(!chatBackground)}
        title={chatCompact ? "Add a translucent background behind the conversation" : "Chat background only applies to Compact chat"}>
        Chat background: {chatBackground ? "On" : "Off"}
      </button>
    </>
  )
}
