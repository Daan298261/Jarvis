import { useSyncExternalStore } from "react"

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

const state = {
  [CHAT_BACKGROUND_KEY]: readOnByDefault(CHAT_BACKGROUND_KEY),
  [CHAT_COMPACT_KEY]: readOnByDefault(CHAT_COMPACT_KEY),
}
const listeners = new Set<() => void>()

function notify(): void {
  listeners.forEach((listener) => listener())
}

export function subscribeChatAppearance(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== null && event.key !== CHAT_BACKGROUND_KEY && event.key !== CHAT_COMPACT_KEY) return
    try {
      if (event.storageArea && event.storageArea !== window.localStorage) return
    } catch { /* Storage may be unavailable. */ }
    for (const key of [CHAT_BACKGROUND_KEY, CHAT_COMPACT_KEY] as const) {
      state[key] = readOnByDefault(key)
    }
    notify()
  })
}

function writeOnOff(key: keyof typeof state, enabled: boolean): void {
  state[key] = enabled
  try {
    localStorage.setItem(key, enabled ? "on" : "off")
  } catch {
    // Keep the current preference even if browser storage is unavailable.
  }
  notify()
}

export function readChatBackground(): boolean {
  return state[CHAT_BACKGROUND_KEY]
}

export function setChatBackground(enabled: boolean): void {
  writeOnOff(CHAT_BACKGROUND_KEY, enabled)
}

export function useChatBackground(): [boolean, (enabled: boolean) => void] {
  return [useSyncExternalStore(subscribeChatAppearance, readChatBackground, () => true), setChatBackground]
}

export function readChatCompact(): boolean {
  return state[CHAT_COMPACT_KEY]
}

export function setChatCompact(enabled: boolean): void {
  writeOnOff(CHAT_COMPACT_KEY, enabled)
}

export function useChatCompact(): [boolean, (enabled: boolean) => void] {
  return [useSyncExternalStore(subscribeChatAppearance, readChatCompact, () => true), setChatCompact]
}

/** Class names for the HUD chat root: `chat-compact` scopes the RFC-0243 caps; without it the classic rules apply. */
export function chatRootClassName(compact: boolean): string {
  return compact ? "hud-chat chat-compact" : "hud-chat"
}
