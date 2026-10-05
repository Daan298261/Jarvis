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
