import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { JSDOM } from "jsdom"

const dom = new JSDOM("<!doctype html><body></body>", { url: "http://127.0.0.1:4780/" })
const { window } = dom
for (const key of ["window", "document", "localStorage", "HTMLElement", "Node", "Event", "MouseEvent"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const appearance = await import("./src/chat/chatAppearance.ts")
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

test("compact toggle writes off and a reload reads off", async () => {
  localStorage.clear()
  appearance.setChatCompact(false)
  assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "off")
  const reloaded = await import("./src/chat/chatAppearance.ts?reload=off")
  assert.equal(reloaded.readChatCompact(), false, "a fresh module instance (a reload) reads Off from storage")
  appearance.setChatCompact(true)
  assert.equal(localStorage.getItem(appearance.CHAT_COMPACT_KEY), "on")
  const reloadedOn = await import("./src/chat/chatAppearance.ts?reload=on")
  assert.equal(reloadedOn.readChatCompact(), true)
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

test("classic mode has no chat background panel", () => {
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

test("compact keeps the role bubble colours", () => {
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
