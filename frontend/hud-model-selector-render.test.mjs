import assert from "node:assert/strict"
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
const { HudModelSelector } = await import("./src/hud/HudModelSelector.tsx")

const suite = { id: "hexstrike-suite", name: "hexstrike-suite", label: "HexStrike AI", model: "suite", provider: "hexstrike", is_local: true }
const graded = (id, name, over = {}) => ({ id, display_name: name, overall: 5, path: `C:/models/${name}.gguf`, matched: true, weight_gb: 8,
  quantization: "Q4", strength: "", pinned: false, favorite: false, runtime_profile_id: null, ...over })

async function mount({ profiles, catalog = null, selectedId = "" }) {
  const calls = { profiles: 0, catalog: 0 }
  globalThis.__hudModelApi = {
    selectedId,
    listRuntimeProfiles: async () => { calls.profiles++; if (profiles instanceof Error) throw profiles; return { profiles } },
    getLmStudioCatalog: async () => { calls.catalog++; if (!catalog) throw new Error("catalog unavailable"); return catalog },
    api: async (path) => (path === "/api/model" ? { loaded: false } : {}),
    getRuntimeProfile: async () => suite,
  }
  const host = document.getElementById("root")
  const root = createRoot(host)
  await act(async () => { root.render(React.createElement(HudModelSelector, { model: { loaded: false } })) })
  const text = (selector) => host.querySelector(selector)?.textContent
  return { host, calls, text, root,
    open: async () => {
      await act(async () => { host.querySelector(".hud-model-trigger").dispatchEvent(new window.MouseEvent("click", { bubbles: true })) })
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
    },
    close: () => act(async () => root.unmount()) }
}

async function withView(options, check) {
  const view = await mount(options)
  try { await check(view) } finally { await view.close() }
}

test("the trigger shows the cybersecurity suite status before the menu is ever opened, with one runtime fetch", () =>
  withView({ profiles: [suite], selectedId: "hexstrike-suite" }, async (view) => {
    assert.equal(view.host.querySelector(".hud-model-menu"), null)
    assert.equal(view.text(".hud-model-trigger-meta"), "Cybersecurity suite · Models ▾")
    assert.equal(view.calls.profiles, 1)
    assert.equal(view.calls.catalog, 0)
    await view.open()
    assert.equal(view.calls.profiles, 2, "opening the menu refreshes once; it does not add a second fetch")
    assert.ok(view.host.querySelector(".hud-model-suite-row.active"))
  }))

test("the trigger shows Offline before the menu is opened when runtimes cannot be read", () =>
  withView({ profiles: new Error("down") }, async (view) => {
    assert.equal(view.host.querySelector(".hud-model-menu"), null)
    assert.equal(view.text(".hud-model-trigger-meta"), "Offline · Models ▾")
  }))

test("pinned and favorite graded models list first (Overall descending), only pinned ones carry a star, and files follow alphabetically", () => {
  const catalog = { profiles: [graded("a", "Alpha", { overall: 9 }), graded("p", "Pinned", { overall: 2, pinned: true }),
    graded("f", "Fav", { overall: 3, favorite: true }), graded("b", "Beta", { overall: 6 })],
    ungraded: [{ filename: "Zed.gguf", path: "C:/models/Zed.gguf", weight_gb: 3, quantization: "Q4" }], vram_gb: null }
  return withView({ profiles: [], catalog }, async (view) => {
    await view.open()
    const labels = [...view.host.querySelectorAll("option")].map((option) => option.textContent).filter((label) => !label.startsWith("Choose"))
    assert.deepEqual(labels, ["Fav · 8.0 GB", "★ Pinned · 8.0 GB", "Alpha · 8.0 GB", "Beta · 8.0 GB", "Zed · 3.0 GB"])
  })
})

test("the trigger announces a popup and selecting the HexStrike suite closes the menu", () =>
  withView({ profiles: [suite] }, async (view) => {
    assert.equal(view.host.querySelector(".hud-model-trigger").getAttribute("aria-haspopup"), "true")
    await view.open()
    assert.ok(view.host.querySelector(".hud-model-menu"))
    await act(async () => { view.host.querySelector(".hud-model-suite-row").dispatchEvent(new window.MouseEvent("click", { bubbles: true })) })
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })
    assert.equal(view.host.querySelector(".hud-model-menu"), null)
  }))
