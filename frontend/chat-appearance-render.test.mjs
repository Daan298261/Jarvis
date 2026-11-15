import assert from "node:assert/strict"
import { after, test } from "node:test"
import { JSDOM } from "jsdom"
import React, { act } from "react"
import { createRoot } from "react-dom/client"

const dom = new JSDOM("<!doctype html><body><div id='hud'></div><div id='settings'></div></body>", { url: "http://127.0.0.1:4780/" })
const { window } = dom
for (const key of ["window", "document", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent", "customElements"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
// HudChat probes the backend on mount; answer every request with an empty JSON body instead of the network.
globalThis.fetch = async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } })
// Closing the window clears any jsdom timer a mounted component scheduled, so the test process exits.
after(() => window.close())

const appearance = await import("./src/chat/chatAppearance.ts")
// The real HUD chat root (HudChat renders its whole body inside HudChatFrame) and the real Settings
// Appearance pane, so the tests fail if either drops the Compact chat / Chat background wiring.
const { HudChat, HudChatFrame } = await import("./src/hud/HudChat.tsx")
const { PendingApprovalsProvider } = await import("./src/chat/pendingApprovals.tsx")
const { MemoryRouter } = await import("react-router-dom")
const { AppearanceSettingsPane } = await import("./src/settings/AppearanceSettingsPane.tsx")
const { DEFAULT_PRESENTATION_SETTINGS } = await import("./src/presence/presenceTypes.ts")

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
      hudRoot.render(React.createElement(HudChatFrame))
      settingsRoot.render(React.createElement(AppearanceSettingsPane, { settings: DEFAULT_PRESENTATION_SETTINGS, showPersona: false }))
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

test("HudChat renders its body inside HudChatFrame, so the live HUD carries the Compact chat wiring", async () => {
  localStorage.clear()
  appearance.setChatCompact(true)
  appearance.setChatBackground(true)
  const hud = document.getElementById("hud")
  const hudRoot = createRoot(hud)
  try {
    await act(async () => {
      hudRoot.render(React.createElement(MemoryRouter, null,
        React.createElement(PendingApprovalsProvider, null, React.createElement(HudChat))))
    })
    const root = hud.firstElementChild
    assert.equal(root.className, "hud-chat chat-compact")
    assert.equal(root.getAttribute("data-chat-compact"), "on")
    assert.equal(root.getAttribute("data-chat-background"), "on")
    assert.equal(root.firstElementChild.className, "hud-chat-tools", "the tools row stays the first child of the chat root")
    assert.ok(root.firstElementChild.querySelector(".hud-chat-compact-toggle"))
    assert.ok(root.querySelector(":scope > .hud-composer"), "the composer still renders directly under the chat root")
    await click(compactButton(hud))
    assert.equal(hud.firstElementChild.className, "hud-chat")
    assert.equal(hud.firstElementChild.getAttribute("data-chat-compact"), "off")
  } finally {
    await act(async () => { hudRoot.unmount() })
    appearance.setChatCompact(true)
    appearance.setChatBackground(true)
  }
})
