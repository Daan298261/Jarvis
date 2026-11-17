import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import {
  isUnavailableError,
  pruneUnavailableServers,
  unansweredOfferIds,
} from "./src/hud/runningModelsUi.ts"

const css = readFileSync(new URL("./src/hud/hud-v2.css", import.meta.url), "utf8")
const card = readFileSync(new URL("./src/hud/RunningModels.tsx", import.meta.url), "utf8")

test("chooser action buttons set an explicit dark face and light label (no white-on-white)", () => {
  assert.match(css, /\.running-model-offer button,\s*\n\.running-model-actions button \{/)
  assert.match(css, /background:\s*#2a2218/)
  assert.match(css, /color:\s*#f3ebe0/)
  assert.doesNotMatch(css, /\.running-model-actions button \{[^}]*color:\s*inherit/)
})

test("HUD card exposes a Dismiss control that is not the details summary alone", () => {
  assert.match(card, /Dismiss/)
  assert.match(card, /dismissCard/)
  assert.match(card, /running-model-dismiss/)
})

test("unavailable / server-changed errors prune the ghost row so the card can close", () => {
  assert.equal(isUnavailableError("That model is no longer available; scan again"), true)
  assert.equal(isUnavailableError("The server changed; scan again before choosing"), true)
  assert.equal(isUnavailableError("Another client is using this model"), false)
  const servers = [{ id: "a" }, { id: "b" }]
  assert.deepEqual(
    pruneUnavailableServers(servers, "a", "That model is no longer available; scan again"),
    [{ id: "b" }],
  )
  assert.deepEqual(pruneUnavailableServers(servers, "a", "busy"), servers)
})

test("dismiss targets unanswered offers only", () => {
  assert.deepEqual(
    unansweredOfferIds([
      { id: "a", choice: null },
      { id: "b", choice: "leave" },
      { id: "c", choice: null },
    ]),
    ["a", "c"],
  )
})
