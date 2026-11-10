import { useState } from "react"

export const CHAT_BACKGROUND_KEY = "jarvis.chat.background.v1"
/** RFC-0243 compact layout (820 px column, capped thread). Off restores the classic layout and fade mask. */
export const CHAT_COMPACT_KEY = "jarvis.chat.compact.v1"

/** Both preferences default on; only an explicit "off" turns one off. */
function readOnByDefault(key: string): boolean {
  try {
    return localStorage.getItem(key) !== "off"
  } catch {
    return true
  }
}

function writeOnOff(key: string, enabled: boolean): void {
  try {
    localStorage.setItem(key, enabled ? "on" : "off")
  } catch {
    // Keep the current preference even if browser storage is unavailable.
  }
}

function usePersistedToggle(key: string): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = useState(() => readOnByDefault(key))
  return [enabled, (next) => {
    setEnabled(next)
    writeOnOff(key, next)
  }]
}

export function readChatBackground(): boolean {
  return readOnByDefault(CHAT_BACKGROUND_KEY)
}

export function useChatBackground(): [boolean, (enabled: boolean) => void] {
  return usePersistedToggle(CHAT_BACKGROUND_KEY)
}

export function readChatCompact(): boolean {
  return readOnByDefault(CHAT_COMPACT_KEY)
}

export function useChatCompact(): [boolean, (enabled: boolean) => void] {
  return usePersistedToggle(CHAT_COMPACT_KEY)
}

/** Class names for the HUD chat root: `chat-compact` scopes the RFC-0243 caps; without it the classic rules apply. */
export function chatRootClassName(compact: boolean): string {
  return compact ? "hud-chat chat-compact" : "hud-chat"
}
