import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

const store = new Map()
globalThis.localStorage = {
  getItem: (key) => (store.has(key) ? store.get(key) : null),
  setItem: (key, value) => store.set(key, String(value)),
  removeItem: (key) => store.delete(key),
}

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
  store.clear()
  assert.equal(appearance.readChatCompact(), true)
  assert.equal(appearance.readChatBackground(), true)
  store.set(appearance.CHAT_COMPACT_KEY, "off")
  assert.equal(appearance.readChatCompact(), false)
  assert.equal(appearance.readChatBackground(), true, "the two preferences are independent")
  store.set(appearance.CHAT_COMPACT_KEY, "on")
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

test("HudChat surfaces the Compact chat toggle beside the background toggle", () => {
  const hud = readFileSync(new URL("./src/hud/HudChat.tsx", import.meta.url), "utf8")
  assert.match(hud, /className=\{chatRootClassName\(chatCompact\)\}/)
  const tools = hud.slice(hud.indexOf('className="hud-chat-tools"'))
  assert.ok(tools.indexOf("Compact chat:") > 0 && tools.indexOf("Chat background:") > tools.indexOf("Compact chat:"))
})
