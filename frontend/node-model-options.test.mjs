import assert from "node:assert/strict"
import { test } from "node:test"
import { modelName, nodeModelOptions, selectedModelOption } from "./src/hud/nodeModelOptions.ts"

test("model identities retain dotted names and quantization", () => {
  assert.equal(modelName("C:\\models\\Qwen3.8-9B.Q8_0.gguf"), "Qwen3.8-9B.Q8_0")
})
test("catalog aliases share one actual file without hiding another runtime", () => {
  const profiles = [{ id: "local", name: "local", model: "generic", provider: "local", is_local: true },
    { id: "remote", name: "remote", model: "Qwen3.8-27B", provider: "openai", is_local: false }]
  const entry = { id: "catalog", path: "C:/Qwen3.8-9B.gguf", matched: true, runtime_profile_id: "local", weight_gb: 10, quantization: "Q8" }
  const options = nodeModelOptions(profiles, { profiles: [entry, { ...entry, id: "alias" }], ungraded: [{ ...entry, filename: "Qwen3.8-9B.gguf" }] })
  assert.equal(options.length, 2)
  assert.match(options.find(option => option.kind === "catalog").label, /Qwen3\.8-9B/)
  assert.equal(selectedModelOption(options, "local"), "catalog:catalog")
  assert.match(options.find(option => option.id === "remote").detail, /remote/)
  assert.equal(selectedModelOption(options, "missing"), "")
})
