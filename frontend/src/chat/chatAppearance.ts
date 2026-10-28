import { useState } from "react"

export const CHAT_BACKGROUND_KEY = "jarvis.chat.background.v1"

export function readChatBackground(): boolean {
  try {
    return localStorage.getItem(CHAT_BACKGROUND_KEY) !== "off"
  } catch {
    return true
  }
}

export function useChatBackground(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = useState(readChatBackground)
  return [enabled, (next) => {
    setEnabled(next)
    try {
      localStorage.setItem(CHAT_BACKGROUND_KEY, next ? "on" : "off")
    } catch {
      // Keep the current preference even if browser storage is unavailable.
    }
  }]
}
