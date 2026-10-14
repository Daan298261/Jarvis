import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"
import { readFile } from "node:fs/promises"

await register("./persona-morph-test-loader.mjs", import.meta.url)
const morph = await import("./src/presence/personaMorphHook.ts")

const ctx = { reason: "manual", layout: "A", variant: "mythic_live_b" }

test("onCloudToPersonaMorph is exported as the authorized no-op seam", async () => {
  assert.equal(typeof morph.onCloudToPersonaMorph, "function")
  assert.equal(morph.onCloudToPersonaMorph.length, 3)
  assert.equal(await morph.onCloudToPersonaMorph("anzu", "enki", ctx), undefined)
  const src = await readFile(new URL("./src/presence/personaMorphHook.ts", import.meta.url), "utf8")
  assert.match(src, /reason: "manual" \| "intent"/)
  assert.match(src, /layout: "A" \| "B" \| "C"/)
  assert.match(src, /variant: string/)
  assert.match(src, /import type \{ NamedPersonaId as PersonaId \} from "\.\.\/persona\/namedPersonas"/)
})

test("helper passes from/to/ctx to the hook and reports completion", async () => {
  const calls = []
  const out = await morph.awaitPersonaMorphWithTimeout("anzu", "nabu", ctx, 1500, (...a) => { calls.push(a) })
  assert.equal(out, "completed")
  assert.deepEqual(calls, [["anzu", "nabu", ctx]])
})

test("a hook that never resolves does not block past the timeout", async () => {
  const started = Date.now()
  const out = await morph.awaitPersonaMorphWithTimeout("anzu", "enki", ctx, 50, () => new Promise(() => {}))
  assert.equal(out, "timeout")
  assert.ok(Date.now() - started < 1000)
})

test("rejecting or throwing hooks never throw to the caller", async () => {
  assert.equal(await morph.awaitPersonaMorphWithTimeout("anzu", "enki", ctx, 50, async () => { throw new Error("x") }), "error")
  assert.equal(await morph.awaitPersonaMorphWithTimeout("anzu", "enki", ctx, 50, () => { throw new Error("y") }), "error")
})

const stubs = await import("./persona-morph-test-stubs.mjs")
const { activateNamedPersona } = await import("./src/persona/activateNamedPersona.ts")

function recorder(impl = () => {}) {
  const calls = []
  const hook = (...args) => { calls.push(args); return impl(...args) }
  return { calls, hook }
}

test("a normal switch runs the morph hook once with previous id, new id and ctx", async () => {
  stubs.resetStubs({ activeId: "anzu", avatarId: "mythic_portrait_a" })
  const { calls, hook } = recorder()
  const state = await activateNamedPersona("enki", { morphHook: hook })
  assert.equal(state.active.id, "enki")
  assert.deepEqual(calls, [["anzu", "enki", { reason: "manual", layout: "A", variant: "mythic_portrait_a" }]])
  // Live behaviour preserved: HUD shell, particle bust, mythic selection feeds avatarId.
  assert.deepEqual(stubs.stubState.presentationUpdates, [
    { shell: "hud", requestedPresence: "particle_bust", avatarId: "mythic_portrait_a" },
  ])
  assert.deepEqual(stubs.stubState.selected, ["enki"])
})

test("reason is forwarded and unknown avatars fall back to the mythic default variant", async () => {
  stubs.resetStubs({ activeId: "nabu", avatarId: "not_a_mythic_avatar" })
  const { calls, hook } = recorder()
  await activateNamedPersona("veles", { morphHook: hook, reason: "intent" })
  assert.deepEqual(calls, [["nabu", "veles", { reason: "intent", layout: "A", variant: "mythic_live_b" }]])
})

test("re-selecting the active persona does not run the morph", async () => {
  stubs.resetStubs({ activeId: "enki" })
  const { calls, hook } = recorder()
  await activateNamedPersona("enki", { morphHook: hook })
  assert.equal(calls.length, 0)
  assert.deepEqual(stubs.stubState.selected, ["enki"])
})

test("with no previous active persona the morph is skipped and activation still completes", async () => {
  stubs.resetStubs({ activeId: undefined })
  const { calls, hook } = recorder()
  const state = await activateNamedPersona("mestor", { morphHook: hook })
  assert.equal(calls.length, 0)
  assert.equal(state.active.id, "mestor")
  assert.equal(stubs.stubState.presentationUpdates.length, 1)
})

test("a never-resolving morph hook does not block activation past the timeout", async () => {
  stubs.resetStubs({ activeId: "anzu" })
  const { calls, hook } = recorder(() => new Promise(() => {}))
  const started = Date.now()
  const state = await activateNamedPersona("bragi", { morphHook: hook })
  const elapsed = Date.now() - started
  assert.equal(state.active.id, "bragi")
  assert.equal(calls.length, 1)
  assert.ok(elapsed >= 1400 && elapsed < 3000, `activation took ${elapsed}ms`)
})
