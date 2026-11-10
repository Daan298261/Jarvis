import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { JSDOM } from "jsdom"
import React, { act } from "react"
import { createRoot } from "react-dom/client"

const dom = new JSDOM("<!doctype html><body><div id='root'></div><div id='settings'></div></body>", { url: "http://127.0.0.1:4780/" })
const { window } = dom
for (const key of ["window", "document", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const appearance = await import("./src/chat/chatAppearance.ts")
const { ChatAppearanceToggles } = await import("./src/chat/ChatAppearanceToggles.tsx")
const css = readFileSync(new URL("./src/hud/hud-v2.css", import.meta.url), "utf8")

function rules(source) {
  const out = []
  const re = /([^{}]+)\{([^{}]*)\}/g
  let match
  while ((match = re.exec(source))) out.push({ selector: match[1].replace(/\/\*[\s\S]*?\*\//g, "").trim(), body: match[2] })
  return out
}
const all = rules(css)
const compactRules = all.filter((rule) => rule.selector.includes(".chat-compact"))
const classicRules = all.filter((rule) => !rule.selector.includes(".chat-compact"))

test("compact chat defaults on and persists like the background toggle", () => {
  assert.equal(appearance.readChatCompact(), true)
  assert.equal(appearance.readChatBackground(), true)
  appearance.setChatCompact(false)
  assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "off")
  assert.equal(appearance.readChatCompact(), false)
  assert.equal(appearance.readChatBackground(), true, "the two preferences are independent")
  appearance.setChatCompact(true)
  assert.equal(appearance.readChatCompact(), true)
})

test("compact on adds the chat-compact class and its rules carry the RFC-0243 caps", () => {
  assert.equal(appearance.chatRootClassName(true), "hud-chat chat-compact")
  const body = compactRules.map((rule) => rule.body).join("\n")
  assert.match(body, /width: min\(820px, calc\(100% - 24px\)\)/)
  assert.match(body, /max-width: 820px/)
  assert.match(body, /max-height: min\(40dvh, 420px\)/)
  assert.match(body, /mask-image: none/)
})

test("compact off restores the classic layout and fade mask", () => {
  assert.equal(appearance.chatRootClassName(false), "hud-chat")
  assert.ok(!appearance.chatRootClassName(false).includes("chat-compact"))
  const classic = classicRules.map((rule) => rule.body).join("\n")
  for (const cap of ["820px", "min(40dvh, 420px)"]) assert.ok(!classic.includes(cap), `${cap} leaks outside compact mode`)
  const thread = classicRules.find((rule) => rule.selector === ".hud-thread")
  assert.match(thread.body, /max-height: min\(30vh, 285px\)/)
  assert.match(thread.body, /mask-image: linear-gradient\(to bottom, transparent 0, black 18px, black calc\(100% - 12px\), transparent 100%\)/)
  const chat = classicRules.find((rule) => rule.selector === ".hud-chat")
  assert.match(chat.body, /width: min\(1000px, calc\(100% - 64px\)\)/)
  assert.ok(!classicRules.some((rule) => rule.selector.includes(".hud-thread") && /mask-image: none/.test(rule.body)))
})

test("the reading panel is compact-only and classic thread styling stays transparent", () => {
  for (const rule of classicRules.filter((rule) => /\.hud-thread\b/.test(rule.selector))) {
    if (rule.selector === ".hud-thread") {
      assert.match(rule.body, /background:\s*transparent\s*;/)
      assert.match(rule.body, /border:\s*0\s*;/)
      assert.doesNotMatch(rule.body, /(?:box-shadow|border-color)\s*:/)
    } else {
      assert.doesNotMatch(rule.body, /(?:background(?:-color)?|box-shadow|border-color)\s*:/, rule.selector)
    }
  }
  const panels = all.filter((rule) => /\.hud-thread\b/.test(rule.selector) && /background:\s*rgba\(5, 11, 18, 0.82\)/.test(rule.body))
  assert.equal(panels.length, 1)
  assert.equal(panels[0].selector, '.hud-chat.chat-compact[data-chat-background="on"] .hud-thread')
  assert.match(panels[0].body, /border-color:/)
  assert.match(panels[0].body, /box-shadow:/)
})

test("compact bubbles only adjust layout and preserve development role colours", () => {
  const bubbles = compactRules.filter((rule) => /\.hud-bubble(?![\w-])/.test(rule.selector))
  assert.ok(bubbles.length)
  for (const rule of bubbles) {
    assert.doesNotMatch(rule.body, /background(?:-[\w-]+)?\s*:/)
    for (const declaration of rule.body.split(";").filter((part) => part.trim())) {
      assert.match(declaration.trim(), /^(?:margin(?:-[\w-]+)?|padding(?:-[\w-]+)?|font-size|line-height)\s*:/)
    }
  }
  for (const [selector, background] of [
    [".hud-bubble-user", "rgba(24, 47, 59, 0.35)"],
    [".hud-bubble-internal", "rgba(20, 16, 8, 0.82)"],
    [".hud-bubble-thought", "rgba(20, 16, 8, 0.82)"],
  ]) {
    assert.ok(classicRules.some((rule) => rule.selector.split(",").map((part) => part.trim()).includes(selector)
      && rule.body.includes(`background: ${background};`)), `${selector} keeps its original background`)
  }
})

test("HUD and Settings toggles share persisted state and restore classic mode together", async () => {
  function ChatRoot() {
    const [compact] = appearance.useChatCompact()
    return React.createElement("div", { className: appearance.chatRootClassName(compact) }, React.createElement(ChatAppearanceToggles))
  }
  const host = document.getElementById("root")
  const settings = document.getElementById("settings")
  const root = createRoot(host)
  const settingsRoot = createRoot(settings)
  const click = (button) => act(async () => button.dispatchEvent(new window.MouseEvent("click", { bubbles: true })))
  const compact = (surface) => surface.querySelector(".hud-chat-compact-toggle")
  const background = (surface) => surface.querySelector(".hud-chat-background-toggle")
  try {
    await act(async () => {
      root.render(React.createElement(ChatRoot))
      settingsRoot.render(React.createElement("section", { "aria-label": "Chat" }, React.createElement(ChatAppearanceToggles)))
    })
    assert.ok(host.querySelector(".chat-compact"))
    await click(compact(host))
    assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "off")
    assert.equal(host.querySelector(".chat-compact"), null)
    assert.equal(host.firstChild.className, "hud-chat")
    for (const surface of [host, settings]) {
      assert.equal(compact(surface).textContent, "Compact chat: Off")
      assert.equal(compact(surface).getAttribute("aria-pressed"), "false")
      assert.equal(background(surface).disabled, true)
      assert.match(background(surface).title, /only applies to Compact chat/)
    }
    await click(compact(settings))
    assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "on")
    assert.ok(host.querySelector(".chat-compact"))
    assert.equal(compact(host).textContent, "Compact chat: On")
    assert.equal(background(host).disabled, false)
    await click(background(settings))
    assert.equal(localStorage.getItem(appearance.CHAT_BACKGROUND_KEY), "off")
    assert.equal(background(host).textContent, "Chat background: Off")
    await click(background(host))
    assert.equal(background(settings).textContent, "Chat background: On")

    await act(async () => {
      localStorage.setItem(appearance.CHAT_COMPACT_KEY, "off")
      window.dispatchEvent(new window.StorageEvent("storage", { key: appearance.CHAT_COMPACT_KEY, storageArea: localStorage }))
    })
    assert.equal(compact(settings).textContent, "Compact chat: Off")
    assert.equal(host.querySelector(".chat-compact"), null)
    await act(async () => {
      localStorage.clear()
      window.dispatchEvent(new window.StorageEvent("storage", { key: null, storageArea: localStorage }))
    })
    assert.equal(compact(settings).textContent, "Compact chat: On")
    assert.ok(host.querySelector(".chat-compact"))
  } finally {
    await act(async () => { root.unmount(); settingsRoot.unmount() })
  }
})

test("storage failures retain shared in-memory preferences and notify subscribers", () => {
  const storage = globalThis.localStorage
  globalThis.localStorage = { getItem() { throw new Error("blocked") }, setItem() { throw new Error("blocked") } }
  let notifications = 0
  const unsubscribe = appearance.subscribeChatAppearance(() => { notifications++ })
  try {
    appearance.setChatCompact(false)
    appearance.setChatBackground(false)
    assert.equal(appearance.readChatCompact(), false)
    assert.equal(appearance.readChatBackground(), false)
    assert.equal(notifications, 2)
    window.dispatchEvent(new window.StorageEvent("storage", { key: null }))
    assert.equal(appearance.readChatCompact(), true, "unreadable storage defaults on")
    assert.equal(appearance.readChatBackground(), true)
  } finally {
    unsubscribe()
    globalThis.localStorage = storage
    appearance.setChatCompact(true)
    appearance.setChatBackground(true)
  }
})
