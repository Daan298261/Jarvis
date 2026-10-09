import type { ParticleOrb } from "../particleTypes"

const linear = (v: number) => v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)

/** Curved, closed particle relief of the authored silhouette, without replacing its identity. */
export function buildPortraitVolume(pixels: Uint8ClampedArray, width: number, height: number): ParticleOrb[] {
  const visible = (x: number, y: number) => {
    const i = (y * width + x) * 4
    return pixels[i + 3] >= 31 && Math.max(pixels[i], pixels[i + 1], pixels[i + 2]) >= 21
  }
  const points: ParticleOrb[] = []
  for (let y = 0; y < height; y++) {
    // Each contiguous run owns its own cross section; gaps between feathers,
    // horns and crowns stay open instead of becoming one generic oval mask.
    for (let start = 0; start < width; start++) {
      if (!visible(start, y)) continue
      let end = start
      while (end + 1 < width && visible(end + 1, y)) end++
      for (let x = start; x <= end; x++) {
        const i = (y * width + x) * 4
        const r = pixels[i] / 255, g = pixels[i + 1] / 255, b = pixels[i + 2] / 255
        const luminance = r * 0.2126 + g * 0.7152 + b * 0.0722
        const nx = end === start ? 0 : (x - start) / (end - start) * 2 - 1
        const arch = Math.sqrt(Math.max(0, 1 - nx * nx))
        const thickness = Math.min(0.62, (end - start + 1) / width * 0.85)
        const depth = arch * thickness
        const sample: ParticleOrb = {
          x: (x / (width - 1) - 0.5) * 3.1,
          y: (0.5 - y / (height - 1)) * 3.1 * height / width,
          z: depth + luminance * 0.12 * arch,
          size: 2.45, light: pixels[i + 3] / 255 * (0.9 + luminance * 0.8),
          gold: 0, flow: 0,
          color: [linear(r), linear(g), linear(b), 1],
        }
        points.push(sample)
        // Dim rear samples preserve the closed volume without washing out the front
        // in the shared additive renderer. They become visible as the head turns.
        if ((x + y) % 3 === 0) points.push({ ...sample, z: -depth, light: sample.light * 0.18, size: 1.3 })
        if (x === start || x === end) {
          points.push({ ...sample, z: 0, light: sample.light * 0.5 })
        }
      }
      start = end
    }
  }
  return points
}
