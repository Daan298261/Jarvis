import { CollapsibleSection } from "../components/CollapsibleSection"
import { useChatBackground, useChatCompact } from "./chatAppearance"

/** RFC-0243 chat appearance buttons. HudChat's tools row and Settings → Appearance render this same component. */
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
        title={chatCompact ? "Add a translucent background behind the conversation" : "Chat background applies in Compact chat"}>
        Chat background: {chatBackground ? "On" : "Off"}
      </button>
    </>
  )
}

/** Settings → Appearance "Chat" section (RFC-0243): the same toggles and store as the HUD chat tools row. */
export function ChatAppearanceSettingsSection() {
  return (
    <CollapsibleSection title="Chat" storageKey="appearance-chat">
      <div className="hud-chat-tools settings-chat-tools">
        <ChatAppearanceToggles />
      </div>
    </CollapsibleSection>
  )
}
