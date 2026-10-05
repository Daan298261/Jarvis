import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import test from "node:test"

const catalog = await readFile(new URL("./src/persona/personaSetup.ts", import.meta.url), "utf8")
const guide = await readFile(new URL("./src/persona/PersonaSetupGuide.tsx", import.meta.url), "utf8")
const controls = await readFile(new URL("./src/persona/NamedPersonaControls.tsx", import.meta.url), "utf8")
const shell = await readFile(new URL("./src/hud/HudShell.tsx", import.meta.url), "utf8")

const ids = ["anzu", "mestor", "nabu", "enki", "veles", "themis", "aegir", "bragi", "hermes", "heimdall", "eir", "maia", "vulcan", "umi"]

test("every selectable persona has a job-specific setup pack", () => {
  for (const id of ids) {
    assert.match(catalog, new RegExp(`\\n  ${id}: \\{`), `${id} setup pack missing`)
  }
  assert.equal((catalog.match(/steps: \[/g) || []).length, ids.length)
  assert.equal((catalog.match(/tools: \[/g) || []).length, ids.length)
})

test("setup state supports interruption, skip, completion, and revisit", () => {
  assert.match(catalog, /jarvis\.named-persona-setup\.v1/)
  assert.match(catalog, /"not_started" \| "in_progress" \| "complete" \| "skipped"/)
  assert.match(catalog, /beginPersonaSetup/)
  assert.match(catalog, /offerPersonaSetup/)
  assert.match(catalog, /advancePersonaSetup/)
  assert.match(catalog, /skipPersonaSetup/)
  assert.match(catalog, /restartPersonaSetup/)
  assert.match(catalog, /isPersonaSetupIncomplete/)
})

test("guide keeps chat and neural speech available without losing progress", () => {
  assert.match(guide, /speakChatReply/)
  assert.match(guide, /Ask in chat/)
  assert.match(guide, /Skip for now/)
  assert.match(guide, /Resume setup/)
  assert.match(guide, /Run setup again/)
})

test("tool pack setup is not an auto-popup on persona controls", () => {
  assert.doesNotMatch(controls, /PersonaSetupGuide/)
  assert.doesNotMatch(controls, /offerPersonaSetup/)
  assert.doesNotMatch(guide, /progress\.status === "not_started" \|\| progress\.status === "in_progress"/)
  assert.doesNotMatch(guide, /offerPersonaSetup\(personaId\)/)
})

test("top-right admin menu opens the same resumable tool pack flow", () => {
  assert.match(shell, /Tool pack setup/)
  assert.match(shell, /hud-admin-setup-entry/)
  assert.match(shell, /offerPersonaSetup\(setupPersonaId\)/)
  assert.match(shell, /PersonaSetupGuide/)
  assert.match(shell, /setupOpen &&/)
  assert.match(shell, /isPersonaSetupIncomplete/)
  assert.match(shell, /hud-setup-dot/)
  assert.match(shell, /onToolPackSetup/)
})

test("all setup destinations are internal application routes", () => {
  const routes = [...catalog.matchAll(/, "(\/[^"]+)"\)/g)].map((match) => match[1])
  assert.equal(routes.length, ids.length * 3)
  assert.ok(routes.every((route) => route.startsWith("/") && !route.startsWith("//")))
})
