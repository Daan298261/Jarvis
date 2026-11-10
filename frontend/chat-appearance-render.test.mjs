import assert from "node:assert/strict"
import { test } from "node:test"
import { JSDOM } from "jsdom"
import React, { act } from "react"
import { createRoot } from "react-dom/client"

const dom = new JSDOM("<!doctype html><body><div id='hud'></div><div id='settings'></div></body>", { url: "http://127.0.0.1:4780/" })
const { window } = dom
for (const key of ["window", "document", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const appearance = await import("./src/chat/chatAppearance.ts")
const { ChatAppearanceToggles, ChatAppearanceSettingsSection } = await import("./src/chat/ChatAppearanceToggles.tsx")

/** The HUD chat root exactly as HudChat builds it: class from chatRootClassName, data attributes, tools row. */
function HudChatRoot() {
  const [compact] = appearance.useChatCompact()
  const [background] = appearance.useChatBackground()
  return React.createElement("div", {
    className: appearance.chatRootClassName(compact),
    "data-chat-background": background ? "on" : "off",
    "data-chat-compact": compact ? "on" : "off",
  }, React.createElement("div", { className: "hud-chat-tools" }, React.createElement(ChatAppearanceToggles)))
}

const click = (button) => act(async () => { button.dispatchEvent(new window.MouseEvent("click", { bubbles: true })) })
const compactButton = (surface) => surface.querySelector(".hud-chat-compact-toggle")
const backgroundButton = (surface) => surface.querySelector(".hud-chat-background-toggle")

async function mountBoth(check) {
  localStorage.clear()
  appearance.setChatCompact(true)
  appearance.setChatBackground(true)
  const hud = document.getElementById("hud")
  const settings = document.getElementById("settings")
  const hudRoot = createRoot(hud)
  const settingsRoot = createRoot(settings)
  try {
    await act(async () => {
      hudRoot.render(React.createElement(HudChatRoot))
      settingsRoot.render(React.createElement(ChatAppearanceSettingsSection))
    })
    // The Settings "Chat" section is a collapsed CollapsibleSection; open it like the owner does.
    const disclosure = [...settings.querySelectorAll(".collapsible-section-toggle")].find((button) => button.textContent.includes("Chat"))
    assert.ok(disclosure, "Settings shows a Chat section")
    await click(disclosure)
    await check({ hud, settings, root: () => hud.firstChild })
  } finally {
    await act(async () => { hudRoot.unmount(); settingsRoot.unmount() })
    appearance.setChatCompact(true)
    appearance.setChatBackground(true)
  }
}

test("clicking Compact chat flips the HUD root class and persists", () =>
  mountBoth(async ({ hud, root }) => {
    assert.equal(root().className, "hud-chat chat-compact")
    await click(compactButton(hud))
    assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "off")
    assert.equal(root().className, "hud-chat")
    await click(compactButton(hud))
    assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "on")
    assert.equal(root().className, "hud-chat chat-compact")
  }))

test("compact off renders the classic chat root and disables Chat background", () =>
  mountBoth(async ({ hud, settings, root }) => {
    await click(compactButton(settings))
    assert.equal(root().className, "hud-chat")
    assert.equal(root().getAttribute("data-chat-compact"), "off")
    assert.equal(hud.querySelector(".chat-compact"), null)
    for (const surface of [hud, settings]) {
      assert.equal(compactButton(surface).textContent, "Compact chat: Off")
      assert.equal(compactButton(surface).getAttribute("aria-pressed"), "false")
      assert.equal(backgroundButton(surface).disabled, true)
      assert.equal(backgroundButton(surface).title, "Chat background applies in Compact chat")
    }
    assert.equal(localStorage.getItem(appearance.CHAT_BACKGROUND_KEY), "on", "the owner's background choice is kept")
  }))

test("settings and HUD compact toggles stay in sync", () =>
  mountBoth(async ({ hud, settings, root }) => {
    await click(compactButton(settings))
    assert.equal(compactButton(hud).textContent, "Compact chat: Off")
    assert.equal(root().className, "hud-chat")
    await click(compactButton(hud))
    assert.equal(compactButton(settings).textContent, "Compact chat: On")
    await click(backgroundButton(settings))
    assert.equal(localStorage.getItem(appearance.CHAT_BACKGROUND_KEY), "off")
    assert.equal(backgroundButton(hud).textContent, "Chat background: Off")
    assert.equal(root().getAttribute("data-chat-background"), "off")
    await click(backgroundButton(hud))
    assert.equal(backgroundButton(settings).textContent, "Chat background: On")
  }))

test("a storage event from another tab updates the compact toggle", () =>
  mountBoth(async ({ hud, settings, root }) => {
    await act(async () => {
      localStorage.setItem(appearance.CHAT_COMPACT_KEY, "off")
      window.dispatchEvent(new window.StorageEvent("storage", { key: appearance.CHAT_COMPACT_KEY, storageArea: localStorage }))
    })
    assert.equal(compactButton(settings).textContent, "Compact chat: Off")
    assert.equal(compactButton(hud).textContent, "Compact chat: Off")
    assert.equal(root().className, "hud-chat")
    await act(async () => {
      localStorage.clear()
      window.dispatchEvent(new window.StorageEvent("storage", { key: null, storageArea: localStorage }))
    })
    assert.equal(compactButton(settings).textContent, "Compact chat: On")
    assert.equal(root().className, "hud-chat chat-compact")
  }))
