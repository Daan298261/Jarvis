import assert from "node:assert/strict"
import { before, describe, test } from "node:test"

/** @type {typeof import("./src/settings/settingsSubmenus.ts")} */
let submenus

before(async () => {
  submenus = await import("./src/settings/settingsSubmenus.ts")
})

function installStorage(raw) {
  const data = new Map()
  if (raw !== undefined) data.set(submenus.LAST_SETTINGS_SUBMENU_KEY, raw)
  const storage = {
    getItem(key) {
      return data.has(key) ? data.get(key) : null
    },
    setItem(key, value) {
      data.set(key, String(value))
    },
    removeItem(key) {
      data.delete(key)
    },
  }
  globalThis.localStorage = storage
  return data
}

describe("settings submenu IA (RFC-0094)", () => {
  test("nav lists appearance and voice as separate first-class groups", () => {
    assert.ok(submenus.SETTINGS_SUBMENUS.includes("appearance"))
    assert.ok(submenus.SETTINGS_SUBMENUS.includes("voice"))
    assert.equal(submenus.SETTINGS_SUBMENUS.includes("appearance-voice"), false)
    assert.equal(submenus.SETTINGS_SUBMENU_LABELS.appearance, "Appearance")
    assert.equal(submenus.SETTINGS_SUBMENU_LABELS.voice, "Voice")
  })

  test("appearance-voice route redirects to appearance or voice", () => {
    assert.equal(submenus.resolveAppearanceVoiceSubmenuRedirect("appearance-voice", "", ""), "appearance")
    assert.equal(submenus.resolveAppearanceVoiceSubmenuRedirect("appearance-voice", "?section=voice", ""), "voice")
    assert.equal(submenus.resolveAppearanceVoiceSubmenuRedirect("appearance-voice", "", "#voice"), "voice")
    assert.equal(submenus.resolveAppearanceVoiceSubmenuRedirect("voice", "", ""), null)
  })

  test("last submenu migrates appearance-voice and defaults to voice", () => {
    installStorage("appearance-voice")
    assert.equal(submenus.readLastSettingsSubmenu(), "appearance")
    assert.equal(globalThis.localStorage.getItem(submenus.LAST_SETTINGS_SUBMENU_KEY), "appearance")

    installStorage(undefined)
    assert.equal(submenus.readLastSettingsSubmenu(), submenus.DEFAULT_SETTINGS_SUBMENU)
    assert.equal(submenus.DEFAULT_SETTINGS_SUBMENU, "voice")

    installStorage("not-a-real-submenu")
    assert.equal(submenus.readLastSettingsSubmenu(), "voice")
  })

  test("canonical paths for HUD deep-links", () => {
    assert.equal(submenus.voiceSettingsPath(), "/settings/voice")
    assert.equal(submenus.appearanceSettingsPath(), "/settings/appearance")
  })
})
