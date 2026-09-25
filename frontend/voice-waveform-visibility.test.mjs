import assert from "node:assert/strict"
import { test } from "node:test"

const waveform = await import("./src/chat/voiceWaveformVisibility.ts")

test("waveform stays hidden while idle", () => {
  assert.equal(waveform.voiceWaveformVisible({ speaking: false, listening: false }), false)
})

test("waveform is shown while Jarvis is speaking", () => {
  assert.equal(waveform.voiceWaveformVisible({ speaking: true, listening: false }), true)
})

test("waveform is shown while the mic is listening", () => {
  assert.equal(waveform.voiceWaveformVisible({ speaking: false, listening: true }), true)
})

test("waveform hides again when speaking and listening end", () => {
  assert.equal(waveform.voiceWaveformVisible({ speaking: true, listening: true }), true)
  assert.equal(waveform.voiceWaveformVisible({ speaking: false, listening: false }), false)
})
