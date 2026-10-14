import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"
import { readFile } from "node:fs/promises"

await register("./presence-lifecycle-loader.mjs", import.meta.url)
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

test("activateNamedPersona awaits the morph seam on every switch with manual default and layout A", async () => {
  const src = await readFile(new URL("./src/persona/activateNamedPersona.ts", import.meta.url), "utf8")
  assert.match(src, /awaitPersonaMorphWithTimeout\(fromId, toId, \{/)
  assert.match(src, /reason: options\.reason \?\? "manual"/)
  assert.match(src, /layout: "A"/)
  assert.match(src, /const variant = mythicAvatarForSelection\(readPresentationBootstrap\(\).avatarId\)/)
  assert.match(src, /Promise\.allSettled\(\[presenceUpdate, personaUpdate, morph\]\)/)
  // Live behaviour preserved: HUD shell, particle bust and the voice-install path stay.
  assert.match(src, /shell: "hud"/)
  assert.match(src, /requestedPresence: "particle_bust"/)
  assert.match(src, /installVoiceProfile\(profileId\)/)
})
