import type { ParticleOrb } from "../particleTypes"

/** Upper-body study. Negative flow tags keep articulated samples solid:
 * -1 chest, -2 left wing, -3 right wing. Other shapes never use these tags. */
export function buildLivingBird(head: readonly ParticleOrb[], persona: string): ParticleOrb[] {
  if (persona !== "anzu" && persona !== "nabu") return [...head]
  const owl = persona === "nabu"
  const points: ParticleOrb[] = head.map(p => ({ ...p }))
  const blue: readonly [number, number, number, number] = [0.08, 0.38, 0.72, 1]
  const gold: readonly [number, number, number, number] = [0.78, 0.55, 0.19, 1]
  const add = (x: number, y: number, z: number, flow: number, warm: number, shade: number) => {
    points.push({ x, y, z, flow, gold: 0, size: 2.1, light: shade,
      color: blue.map((v, i) => i === 3 ? 1 : v * (1 - warm) + gold[i] * warm) as [number, number, number, number] })
  }
  // Feathered breast and neck, with a closed rear surface. Lower torso continues
  // below the window edge; it is deliberately excluded from head-safe framing.
  for (let row = 0; row < 160; row++) {
    const t = row / 159
    const y = -0.85 - t * 2.8
    const radius = (owl ? 0.8 : 0.72) * Math.sin(Math.PI * (0.13 + t * 0.8))
    for (let col = 0; col < 128; col++) {
      const a = col / 128 * Math.PI * 2
      const feather = Math.sin(a * 18 + t * 60) * 0.022
      const x = Math.cos(a) * (radius + feather)
      const z = Math.sin(a) * (radius * 0.6 + feather) - 0.12
      const warm = Math.max(0, Math.sin(a)) * (0.35 + 0.28 * Math.cos(t * 24))
      add(x, y, z, -1, warm, Math.sin(a) > 0 ? 1.25 : 0.24)
    }
  }
  // Layered flight feathers follow a drooping, folded-wing silhouette rather
  // than a decorative halo. Asymmetric settling rotates each shoulder pivot.
  for (const side of [-1, 1]) for (let feather = 0; feather < 18; feather++) {
    const f = feather / 17
    for (let row = 0; row < 110; row++) {
      const t = row / 109
      const length = (owl ? 1.25 : 1.65) * (0.6 + f * 0.4)
      const x = side * (0.55 + t * length * (0.8 - f * 0.35))
      const y = -1.22 - f * 0.42 - t * (0.65 + f * 1.25)
      const z = -0.16 - f * 0.18 + Math.sin(t * Math.PI) * 0.22
      const width = Math.sin(t * Math.PI) * (0.065 + f * 0.035)
      for (let across = -2; across <= 2; across++) {
        add(x + side * width * across / 2, y + width * across / 2, z,
          side < 0 ? -2 : -3, feather % 4 === 0 ? 0.65 : 0.06, 0.9 + (across === 0 ? 0.35 : 0))
      }
    }
  }
  // Shared draw budgets now cover the body as well. Compensate the head's
  // samples for that allocation so adding a torso does not dim the loved face.
  const headEnergy = points.length / Math.max(1, head.length)
  for (let i = 0; i < head.length; i++) points[i].light *= headEnergy
  return points
}
