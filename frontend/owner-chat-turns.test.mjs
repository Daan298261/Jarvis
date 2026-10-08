import assert from "node:assert/strict"
import { register } from "node:module"
import { test } from "node:test"

await register("./presence-lifecycle-loader.mjs", import.meta.url)

const view = await import("./src/chat/ownerChatView.ts")

const QUICK = "Your meeting is at 3 pm."
const CORRECTION = "Actually, the meeting moved to 4 pm tomorrow in room B."

test("replace_previous_text replaces the live quick answer", () => {
  const reduced = view.reduceLiveAssistantEvents([
    { kind: "front_response_completed", detail: JSON.stringify({ text: QUICK }) },
    { kind: "assistant_delta", detail: " stale tail" },
    { kind: "replace_previous_text", detail: CORRECTION },
  ])
  assert.equal(reduced.replaced, true)
  assert.equal(reduced.text, CORRECTION)
  assert.equal(reduced.text.includes(QUICK), false)
})

test("visible turns overwrite the saved quick line when the live text was replaced", () => {
  const turns = view.visibleChatTurns({
    messages: [
      { role: "user", content: "When is my meeting?" },
      { role: "assistant", content: QUICK },
    ],
    liveAssistant: CORRECTION,
    liveReplaced: true,
  })
  const assistant = turns.filter((turn) => turn.role === "assistant")
  assert.equal(assistant.length, 1)
  assert.equal(assistant[0].content, CORRECTION)
})

test("a live preview that does not replace stays off a different saved line", () => {
  const turns = view.visibleChatTurns({
    messages: [
      { role: "assistant", content: CORRECTION },
    ],
    liveAssistant: QUICK,
    liveReplaced: false,
  })
  assert.equal(turns[0].content, CORRECTION)
})

test("distinct consecutive assistant rows stay distinct", () => {
  const turns = view.visibleChatTurns({
    messages: [
      { role: "user", content: "When is the meeting?" },
      { role: "assistant", content: "The meeting is at 3." },
      { role: "assistant", content: "The meeting was moved to 4." },
    ],
  })
  const assistant = turns.filter((turn) => turn.role === "assistant")
  assert.equal(assistant.length, 2)
  assert.equal(assistant[0].content, "The meeting is at 3.")
  assert.equal(assistant[1].content, "The meeting was moved to 4.")
})

test("exact duplicate assistant rows still collapse", () => {
  const turns = view.visibleChatTurns({
    messages: [
      { role: "assistant", content: "Same line." },
      { role: "assistant", content: "Same line." },
    ],
  })
  assert.equal(turns.filter((turn) => turn.role === "assistant").length, 1)
})

test("assistant deltas still append after the front line", () => {
  const reduced = view.reduceLiveAssistantEvents([
    { kind: "front_response_completed", detail: JSON.stringify({ text: QUICK }) },
    { kind: "assistant_delta", detail: "It moved to room B." },
  ])
  assert.equal(reduced.replaced, false)
  assert.equal(reduced.text, `${QUICK}It moved to room B.`)
})

test("replace events stay out of the work log", () => {
  const hidden = view.filterWorkEvents([
    {
      kind: "replace_previous_text",
      title: "Reply",
      detail: CORRECTION,
      stage: "chat",
      created_at: "",
    },
    {
      kind: "tool",
      title: "filesystem",
      detail: "listed",
      stage: "act",
      created_at: "",
    },
  ])
  assert.equal(hidden.length, 1)
  assert.equal(hidden[0].kind, "tool")
})
