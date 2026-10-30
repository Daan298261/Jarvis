import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { backendModelError, loadStatusLine, localCatalogHint, triggerMeta, vramHint } from "./src/hud/modelMenuStatus.ts"
import { nodeModelOptions, overallScore } from "./src/hud/nodeModelOptions.ts"

const catalog = (over = {}) => ({ profiles: [], ungraded: [], vram_gb: null, ...over })

test("loading line shows elapsed seconds once the first second passes and says the menu can close", () => {
  assert.equal(loadStatusLine(0), "Loading model… You can close this menu.")
  assert.equal(loadStatusLine(12), "Loading model (12s)… You can close this menu.")
})

test("trigger status covers loading, the cybersecurity suite, offline runtimes and the node default", () => {
  const base = { transferring: false, suiteActive: false, runtimesFailed: false }
  assert.equal(triggerMeta({ ...base, transferring: true, suiteActive: true, runtimesFailed: true }), "Loading model")
  assert.equal(triggerMeta({ ...base, suiteActive: true, runtimesFailed: true }), "Cybersecurity suite · Models ▾")
  assert.equal(triggerMeta({ ...base, runtimesFailed: true }), "Offline · Models ▾")
  assert.equal(triggerMeta(base), "Current node · Models ▾")
})

test("local catalog hints cover loading, unavailable and empty states", () => {
  assert.equal(localCatalogHint(null, false), "Loading local models…")
  assert.equal(localCatalogHint(null, true), "Local catalog unavailable.")
  assert.equal(localCatalogHint(catalog(), true), "Local catalog unavailable.")
  assert.equal(localCatalogHint(catalog(), false), "No local GGUFs found under LM Studio models.")
  assert.equal(localCatalogHint(catalog({ ungraded: [{ filename: "a.gguf" }] }), false), "")
  assert.equal(localCatalogHint(catalog({ profiles: [{ id: "a" }] }), false), "")
})

test("VRAM hint is shown only when the catalog reports it", () => {
  assert.equal(vramHint(null), "")
  assert.equal(vramHint(catalog()), "")
  assert.equal(vramHint(catalog({ vram_gb: 24 })), "~24 GB VRAM")
  assert.equal(vramHint(catalog({ vram_gb: 0 })), "~0 GB VRAM")
})

test("graded models keep their Overall score in the dropdown detail", () => {
  assert.equal(overallScore(7.46), "Overall 7.5 · ")
  assert.equal(overallScore(undefined), "")
  const entry = { id: "g", path: "C:/Qwen3.8-9B.gguf", matched: true, overall: 8.25, weight_gb: 10, quantization: "Q8", strength: "Fast" }
  const [option] = nodeModelOptions([], catalog({ profiles: [entry] }))
  assert.equal(option.detail, "Overall 8.3 · 10.0 GB weights · Q8 · Fast")
})

test("the backend's last model error is shown once, and never during a load", () => {
  assert.equal(backendModelError("CUDA out of memory", [], false), "CUDA out of memory")
  assert.equal(backendModelError("  CUDA out of memory ", ["", ""], false), "CUDA out of memory")
  assert.equal(backendModelError("CUDA out of memory", ["CUDA out of memory"], false), "")
  assert.equal(backendModelError("CUDA out of memory", [], true), "")
  assert.equal(backendModelError(undefined, [], false), "")
})

test("the selector renders every restored status through these helpers", () => {
  const source = readFileSync(new URL("./src/hud/HudModelSelector.tsx", import.meta.url), "utf8")
  for (const needle of ["loadStatusLine(elapsed)", "triggerMeta({", "localCatalogHint(catalog, catalogFailed)", "vramHint(catalog)",
    "backendModelError(state?.last_error", 'role="status">{loadStatusLine', "hud-model-suite-row${suiteActive", 'aria-busy={transferring}']) {
    assert.ok(source.includes(needle), `HudModelSelector.tsx is missing ${needle}`)
  }
})
