import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { test } from "node:test"

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "src")
const RENDERERS = join(ROOT, "presence", "renderers")

function read(rel) {
  return readFileSync(join(ROOT, rel), "utf8")
}

function readRenderer(name) {
  return readFileSync(join(RENDERERS, name), "utf8")
}

test("shared presence stage CSS fills the host without a primary aspect cap", () => {
  const stage = readRenderer("presence-stage.css")
  assert.match(stage, /\.jarvis-presence-stage/)
  assert.match(stage, /aspect-ratio:\s*unset/)
  assert.doesNotMatch(stage, /680\s*\/\s*480/)
  assert.doesNotMatch(stage, /920px/)
})

test("HUD presence stage remains viewport-filling at narrow widths", () => {
  const css = read("hud/hud-v2.css")
  const fullStage = css.indexOf(".hud-center:has(.jarvis-presence-stage)")
  const desktopMedia = css.lastIndexOf("@media (min-width: 761px)", fullStage)
  assert.ok(fullStage >= 0)
  assert.ok(desktopMedia < 0 || css.indexOf("}", desktopMedia) < fullStage,
    "full-stage layout must not be gated behind the desktop breakpoint")
  assert.match(css, /\.hud-home\.hexstrike-active > \.hud-orb-zone \{[\s\S]*?inset:\s*0;/)
})

test("profile CSS does not reintroduce competing Neural vs Humanoid stage boxes", () => {
  for (const file of ["apex-presence.css", "humanoid-presence.css"]) {
    const css = readRenderer(file)
    assert.doesNotMatch(css, /aspect-ratio:\s*680\s*\/\s*480/)
    assert.doesNotMatch(css, /920px/)
    assert.match(css, /@import\s+"\.\/presence-stage\.css"/)
  }
})

test("morphable presence mounts use the shared stage class", () => {
  const humanoid = read("presence/renderers/HumanoidPresence.tsx")
  const particle = read("presence/renderers/ParticleBustPresence.tsx")
  const neural = read("presence/renderers/NeuralCloudPresence.tsx")
  assert.match(humanoid, /jarvis-presence-stage/)
  assert.match(particle, /jarvis-presence-stage/)
  // Neural cloud reuses HumanoidPresence (stage class lives there).
  assert.match(neural, /HumanoidPresence/)
  assert.match(humanoid, /MorphablePresenceStage/)
})

test("Appearance exposes APEX UI copy and accurate mode previews", () => {
  const pane = read("settings/AppearanceSettingsPane.tsx")
  const preview = read("presence/PresenceModePreview.tsx")
  const styles = read("presence/presence.css")

  assert.match(pane, /APEX UI · orb \+ graph/)
  assert.match(pane, /requestedPresence: "neural"/)
  assert.doesNotMatch(pane, /Neural HUD/)
  assert.match(pane, /separately hosted private humanoid/)
  assert.match(pane, /PresenceModePreview/)
  assert.match(preview, /data-presence-preview/)
  assert.match(styles, /\[data-presence-preview="neural"\]/)
  assert.match(styles, /\[data-presence-preview="humanoid"\]/)
})

test("neural preview swatch is orb-and-graph not a bust-only thumbnail", () => {
  const styles = read("presence/presence.css")
  const neuralBlock = styles.split('[data-presence-preview="neural"]')[1].split("}")[0]
  assert.match(neuralBlock, /radial-gradient.*245,\s*166,\s*35/)
  assert.doesNotMatch(neuralBlock, /ellipse 34% 46%/)
})

function ruleBlock(css, selector) {
  const start = css.indexOf(selector)
  assert.ok(start >= 0, `missing selector ${selector}`)
  const open = css.indexOf("{", start)
  let depth = 0
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth += 1
    else if (css[i] === "}") {
      depth -= 1
      if (depth === 0) return css.slice(open + 1, i)
    }
  }
  throw new Error(`unclosed rule ${selector}`)
}

test("humanoid canvas is not mask-image'd; edges fade on a separate overlay", () => {
  const css = readRenderer("humanoid-presence.css")
  assert.doesNotMatch(css, /mask-image/)
  const host = ruleBlock(css, ".jarvis-presence-humanoid {")
  assert.doesNotMatch(host, /mask-image/)
  const fade = ruleBlock(css, ".jarvis-presence-humanoid::after {")
  assert.match(fade, /transparent 4%/)
  assert.match(fade, /transparent 94%/)
  assert.match(fade, /pointer-events:\s*none/)
  const galaxy = ruleBlock(css, '.jarvis-presence-humanoid[data-galaxy="true"]::after')
  assert.match(galaxy, /transparent 4%/)
  assert.match(galaxy, /transparent 94%/)
  assert.doesNotMatch(galaxy, /rgba\(0,\s*0,\s*0,\s*0\.[5-9]\)\s+50%/)
})

test("presence clear stays transparent so failed tiles cannot paint opaque black", () => {
  const stage = read("presence/renderers/MorphablePresenceStage.tsx")
  assert.doesNotMatch(stage, /setClearColor\(0x000000,\s*1\)/)
  assert.doesNotMatch(stage, /clear \? 0 : 1/)
  const clears = stage.match(/setClearColor\(0x000000,\s*0\)/g) || []
  assert.equal(clears.length, 2)
  assert.match(stage, /uSampleEnergy:\s*\{\s*value:\s*FIGURE_SAMPLE_ENERGY\s*\}/)
})

test("chat chrome over the presence canvas does not backdrop-filter it", () => {
  const css = read("hud/hud-v2.css")
  const bubble = ruleBlock(css, ".hud-bubble {")
  const composer = ruleBlock(css, ".hud-composer {")
  assert.match(bubble, /backdrop-filter:\s*none/)
  assert.doesNotMatch(bubble, /backdrop-filter:\s*blur/)
  assert.match(bubble, /background:\s*rgb\(7,\s*11,\s*17\)/)
  assert.match(composer, /backdrop-filter:\s*none/)
  assert.doesNotMatch(composer, /backdrop-filter:\s*blur/)
  assert.match(composer, /linear-gradient\(135deg,\s*rgb\(13,\s*25,\s*32\),\s*rgb\(7,\s*13,\s*19\)\)/)
})

test("presence chat fills the stage column and the scrollport is clipped", () => {
  const css = read("hud/hud-v2.css")
  const chat = ruleBlock(css, ".hud-home:has(.jarvis-presence-stage) > .hud-chat {")
  assert.match(chat, /width:\s*calc\(100% - 32px\)/)
  assert.match(chat, /max-width:\s*none/)
  assert.doesNotMatch(chat, /1000px/)
  assert.doesNotMatch(chat, /920px/)
  const center = ruleBlock(css, ".hud-center:has(.jarvis-presence-stage) {")
  assert.match(center, /overflow:\s*clip/)
  assert.match(center, /scrollbar-width:\s*none/)
})
