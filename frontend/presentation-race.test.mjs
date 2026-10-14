import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"

await register("./presence-lifecycle-loader.mjs", import.meta.url)
const presentation = await import("./src/presence/presentationSettings.ts")

test("late A response and mount refresh cannot undo a newer B selection", async () => {
  const previous = { window: globalThis.window, localStorage: globalThis.localStorage, fetch: globalThis.fetch }
  const values = new Map()
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  const events = []
  globalThis.window = { setTimeout, clearTimeout, dispatchEvent: e => events.push(e.detail), location: { origin: "http://localhost" } }
  const requests = []
  globalThis.fetch = () => new Promise(resolve => requests.push(resolve))
  const reply = settings => new Response(JSON.stringify({ presentation: settings }), { status: 200, headers: { "Content-Type": "application/json" } })
  try {
    const refresh = presentation.refreshPresentationFromBackend()
    const a = presentation.updatePresentation({ requestedPresence: "particle_bust", avatarId: "mythic_portrait_a" })
    const b = presentation.updatePresentation({ requestedPresence: "particle_bust", avatarId: "mythic_live_b" })
    assert.equal(presentation.readPresentationBootstrap().avatarId, "mythic_live_b")
    requests[2](reply({ requestedPresence: "particle_bust", avatarId: "mythic_live_b" }))
    await b
    requests[1](reply({ requestedPresence: "particle_bust", avatarId: "mythic_portrait_a" }))
    requests[0](reply({ requestedPresence: "humanoid", avatarId: "jarvis_base" }))
    await Promise.all([a, refresh])
    assert.equal(presentation.readPresentationBootstrap().avatarId, "mythic_live_b")
    assert.equal(events.at(-1).avatarId, "mythic_live_b")
  } finally {
    Object.assign(globalThis, previous)
  }
})
