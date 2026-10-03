import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import test from "node:test"

const catalog = await readFile(new URL("./src/persona/personaSetup.ts", import.meta.url), "utf8")
const guide = await readFile(new URL("./src/persona/PersonaSetupGuide.tsx", import.meta.url), "utf8")
const controls = await readFile(new URL("./src/persona/NamedPersonaControls.tsx", import.meta.url), "utf8")

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
})

test("guide keeps chat and neural speech available without losing progress", () => {
  assert.match(guide, /speakChatReply/)
  assert.match(guide, /Ask in chat/)
  assert.match(guide, /Skip for now/)
  assert.match(guide, /Resume setup/)
  assert.match(guide, /Run setup again/)
  assert.match(controls, /offerPersonaSetup/)
})

test("all setup destinations are internal application routes", () => {
  const routes = [...catalog.matchAll(/, "(\/[^"]+)"\)/g)].map((match) => match[1])
  assert.equal(routes.length, ids.length * 3)
  assert.ok(routes.every((route) => route.startsWith("/") && !route.startsWith("//")))
})
