import type { ParticleOrb, PresenceShapeDefinition } from "../particleTypes"
import { fillSphere, makeRng, pushOrb } from "./figureKit"

/** Magenta/gold orb, pulsing waveform rings, drifting letter strokes. */
export function buildWaveformLettersFigure(density: number): ParticleOrb[] {
  const random = makeRng(8018)
  const orbs: ParticleOrb[] = []
  fillSphere(orbs, random, Math.round(1800 * density), 0.55, 0.1, 0.75, 1.35, 0, 1.4, density)
  const wave = Math.round(360 * density)
  for (let ringIndex = 0; ringIndex < 3; ringIndex++) {
    const radius = 0.7 + ringIndex * 0.16
    for (let i = 0; i < wave; i++) {
      const a = (i / wave) * Math.PI * 2
      const y = 0.1 + Math.sin(a * 6 + ringIndex) * 0.12
      pushOrb(orbs, Math.cos(a) * radius, y, Math.sin(a) * radius * 0.72, ringIndex === 1 ? 1 : 0.2, 1.3, 0.44, 1.15, density)
    }
  }
  const letters = ["I", "O", "A"]
  letters.forEach((glyph, index) => {
    const x0 = -0.7 + index * 0.55
    if (glyph === "I") {
      for (let s = 0; s < 18; s++) pushOrb(orbs, x0, 0.55 + s * 0.025, 0.35, 1, 1.8, 0.46, 1.2, density)
    } else if (glyph === "O") {
      for (let s = 0; s < 28; s++) {
        const a = (s / 28) * Math.PI * 2
        pushOrb(orbs, x0 + Math.cos(a) * 0.12, 0.72 + Math.sin(a) * 0.16, 0.35, 1, 1.8, 0.46, 1.15, density)
      }
    } else {
      for (let s = 0; s < 16; s++) {
        const t = s / 15
        pushOrb(orbs, x0 - 0.1 + t * 0.1, 0.55 + t * 0.35, 0.35, 1, 1.8, 0.46, 1.15, density)
        pushOrb(orbs, x0 + 0.1 - t * 0.1, 0.55 + t * 0.35, 0.35, 1, 1.8, 0.46, 1.15, density)
      }
    }
  })
  return orbs
}

export const waveformLettersShape: PresenceShapeDefinition = {
  id: "waveform_letters",
  label: "Waveform letters",
  buildFigure: buildWaveformLettersFigure,
  framing: { yaw: 0.05, position: [0, 0.05, 0] },
}
