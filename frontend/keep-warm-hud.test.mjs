import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { JSDOM } from "jsdom"
import React, { act } from "react"
import { createRoot } from "react-dom/client"

const dom = new JSDOM("<!doctype html><body><div id='root'></div></body>", { url: "http://127.0.0.1:4780/" })
const { window } = dom
Object.assign(window, { setInterval, clearInterval, setTimeout, clearTimeout })
for (const key of ["window", "document", "localStorage", "HTMLElement", "Node", "Event", "CustomEvent", "MouseEvent", "KeyboardEvent"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const { ApiError } = await import("./src/api.ts")
const { HudModelRelease } = await import("./src/hud/HudModelRelease.tsx")

const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
const click = (element) => act(async () => { element.dispatchEvent(new window.MouseEvent("click", { bubbles: true })) })
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

/** A tiny in-memory backend: settings persist across mounts like the real settings file. */
function backend({ keepWarm = false, unload = async () => ({ ok: true, refused: false, reason: "", released_count: 2, results: [] }), saveError = null } = {}) {
  const state = { keepWarm, calls: [] }
  globalThis.__hudModelApi = {
    api: async (path, init) => {
      state.calls.push({ path, method: init?.method || "GET", body: init?.body ? JSON.parse(init.body) : undefined })
      if (path === "/api/settings" && init?.method === "PUT") {
        if (saveError) throw saveError
        state.keepWarm = JSON.parse(init.body).inference_keep_warm
        return { inference: { keep_warm: state.keepWarm } }
      }
      if (path === "/api/settings") return { inference: { keep_warm: state.keepWarm } }
      if (path === "/api/model/unload-all") return unload()
      throw new Error(`unexpected ${path}`)
    },
  }
  return state
}

async function mount() {
  const host = document.getElementById("root")
  const root = createRoot(host)
  await act(async () => { root.render(React.createElement(HudModelRelease)) })
  await flush()
  return { host, unloadButton: () => host.querySelector(".hud-unload-btn"), toggle: () => host.querySelector("[role=switch]"),
    note: () => host.querySelector(".hud-model-release-note"), close: () => act(async () => root.unmount()) }
}

async function withView(check) {
  const view = await mount()
  try { await check(view) } finally { await view.close() }
}

test("renders the Unload model button and the Keep warm switch, OFF by default", async () => {
  const state = backend()
  await withView(async (view) => {
    assert.equal(view.unloadButton().textContent, "Unload model")
    assert.equal(view.unloadButton().disabled, false)
    assert.equal(view.toggle().textContent, "Keep warm: Off")
    assert.equal(view.toggle().getAttribute("aria-checked"), "false")
    assert.equal(view.note(), null)
    assert.deepEqual(state.calls.map((call) => call.path), ["/api/settings"])
  })
})

test("clicking Unload model posts once, shows a busy state, then reports what was unloaded", async () => {
  const pending = deferred()
  const state = backend({ unload: () => pending.promise })
  await withView(async (view) => {
    await click(view.unloadButton())
    assert.equal(view.unloadButton().textContent, "Unloading…")
    assert.equal(view.unloadButton().disabled, true)
    assert.equal(view.unloadButton().getAttribute("aria-busy"), "true")
    await click(view.unloadButton())
    assert.equal(state.calls.filter((call) => call.path === "/api/model/unload-all").length, 1, "a busy button never double-submits")
    await act(async () => { pending.resolve({ ok: true, refused: false, reason: "", released_count: 2, results: [] }) })
    await flush()
    assert.equal(view.unloadButton().textContent, "Unload model")
    assert.equal(view.unloadButton().disabled, false)
    assert.equal(view.unloadButton().getAttribute("aria-busy"), "false")
    assert.match(view.note().textContent, /Unloaded 2 models\. They load again on your next turn or a Load\./)
    assert.equal(state.calls.find((call) => call.path === "/api/model/unload-all").method, "POST")
  })
})

test("a refused unload shows the reason in the HUD and the button comes back (never a dead button)", async () => {
  backend({ unload: async () => { throw new ApiError(409, "ANZU is answering a request; try again when it finishes.") } })
  await withView(async (view) => {
    await click(view.unloadButton())
    await flush()
    assert.equal(view.note().textContent, "Not unloaded: ANZU is answering a request; try again when it finishes.")
    assert.ok(view.note().classList.contains("error"))
    assert.equal(view.note().getAttribute("role"), "status")
    assert.equal(view.unloadButton().disabled, false)
  })
})

test("a partial unload (207) is never shown as success: one line per model and the reason", async () => {
  backend({ unload: async () => ({
    ok: false, refused: false, reason: "ollama 127.0.0.1:11434: stuck:1b: still loaded after unload", released: 1, failed: 1, skipped: [],
    results: [
      { model: "qwen-a", backend: "lmstudio", via: "lmstudio_instance", verified: true, error: null },
      { model: "stuck:1b", backend: "ollama", via: "ollama_keep_alive_0", verified: false, error: "still loaded after unload" },
    ] }) })
  await withView(async (view) => {
    await click(view.unloadButton())
    await flush()
    assert.ok(view.note().classList.contains("error"))
    assert.match(view.note().textContent, /^Unload incomplete: 1 of 2 models released\. ollama 127\.0\.0\.1:11434/)
    const lines = [...view.note().querySelectorAll("li")].map((li) => li.textContent)
    assert.deepEqual(lines, ["Unloaded and verified: qwen-a", "Could not unload stuck:1b: still loaded after unload"])
    assert.doesNotMatch(view.note().textContent, /They load again/)
    assert.equal(view.unloadButton().disabled, false)
  })
})

test("a cancelled pipeline is shown in the HUD (the unload is not refused for a running task)", async () => {
  backend({ unload: async () => ({ ok: true, refused: false, reason: "", released: 1, failed: 0, skipped: [], cancelled_tasks: ["t1", "t2"],
    results: [{ model: "a", backend: "ollama", via: "ollama_keep_alive_0", verified: true, error: null }] }) })
  await withView(async (view) => {
    await click(view.unloadButton())
    await flush()
    assert.deepEqual([...view.note().querySelectorAll("li")].map((li) => li.textContent),
      ["Cancelled 2 running tasks (shown as cancelled in the task list).", "Unloaded and verified: a"])
  })
})

test("a full unload (200) lists every model as verified", async () => {
  backend({ unload: async () => ({ ok: true, refused: false, reason: "", released: 2, failed: 0, skipped: [], results: [
    { model: "a", backend: "ollama", via: "ollama_keep_alive_0", verified: true, error: null },
    { model: "b", backend: "lmstudio", via: "lmstudio_instance", verified: true, error: null }] }) })
  await withView(async (view) => {
    await click(view.unloadButton())
    await flush()
    assert.ok(!view.note().classList.contains("error"))
    assert.match(view.note().textContent, /^Unloaded 2 models\./)
    assert.deepEqual([...view.note().querySelectorAll("li")].map((li) => li.textContent), ["Unloaded and verified: a", "Unloaded and verified: b"])
  })
})

test("a backend that fails to release (502) reports its own reason instead of a success", async () => {
  backend({ unload: async () => { throw new ApiError(502, "ollama 127.0.0.1:11434: still loaded after unload: stuck:1b") } })
  await withView(async (view) => {
    await click(view.unloadButton())
    await flush()
    assert.equal(view.note().textContent, "Unload incomplete: ollama 127.0.0.1:11434: still loaded after unload: stuck:1b")
    assert.equal(view.unloadButton().disabled, false)
  })
})

test("Unload with nothing loaded is a 409 with its reason on the control", async () => {
  backend({ unload: async () => { throw new ApiError(409, "Nothing to unload: ANZU has no loaded model.") } })
  await withView(async (view) => {
    await click(view.unloadButton())
    await flush()
    assert.equal(view.note().textContent, "Not unloaded: Nothing to unload: ANZU has no loaded model.")
    assert.equal(view.unloadButton().disabled, false)
  })
})

test("the Keep warm switch persists through the settings API and survives a remount", async () => {
  const state = backend()
  await withView(async (view) => {
    await click(view.toggle())
    await flush()
    const save = state.calls.find((call) => call.method === "PUT")
    assert.deepEqual(save, { path: "/api/settings", method: "PUT", body: { inference_keep_warm: true } })
    assert.equal(view.toggle().textContent, "Keep warm: On")
    assert.equal(view.toggle().getAttribute("aria-checked"), "true")
  })
  assert.equal(state.keepWarm, true)
  await withView(async (view) => {
    assert.equal(view.toggle().textContent, "Keep warm: On", "the saved value is read back on the next load")
    await click(view.toggle())
    await flush()
    assert.equal(state.keepWarm, false)
    assert.equal(view.toggle().textContent, "Keep warm: Off")
  })
})

test("a failed Keep warm save keeps the old value and says why", async () => {
  backend({ saveError: new ApiError(500, "settings file is read-only") })
  await withView(async (view) => {
    await click(view.toggle())
    await flush()
    assert.equal(view.toggle().textContent, "Keep warm: Off")
    assert.equal(view.note().textContent, "Keep warm was not saved: settings file is read-only")
    assert.equal(view.toggle().disabled, false)
  })
})

test("the HUD top bar only gains the new controls: every existing control is still there, ahead of the model menu", () => {
  const shell = readFileSync(new URL("./src/hud/HudShell.tsx", import.meta.url), "utf8")
  const right = shell.slice(shell.indexOf('<div className="hud-top-right">'), shell.indexOf("{adminOpen &&"))
  const order = ["<HelpTrigger", ">\n          Admin", "Classic\n", "<HudModelRelease />", "<HudModelSelector "].map((part) => right.indexOf(part))
  assert.ok(order.every((index) => index >= 0), `missing control in top-right: ${order}`)
  assert.deepEqual([...order].sort((a, b) => a - b), order)
})
