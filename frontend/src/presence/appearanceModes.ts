import type { PresentationSettings } from "./presenceTypes"

export const DAYBREAK_AVATAR_ID = "hexstrike_suite"
/** Runtime selection must not silently override an explicit visual selection. */
export function usesDaybreakAppearance(settings: Pick<PresentationSettings, "requestedPresence" | "avatarId">, suiteActive: boolean): boolean {
  return suiteActive && settings.requestedPresence === "humanoid" && settings.avatarId === DAYBREAK_AVATAR_ID
}

export type StageRect = { left: number; top: number; width: number; height: number }
export function personaSafeViewport(stage: StageRect, composer?: StageRect | null, menu?: StageRect | null) {
  const bottom = composer && composer.top > stage.top ? Math.min(stage.height - 16, composer.top - stage.top - 38) : stage.height - 30
  const left = menu && menu.width > 140 && menu.left + menu.width < stage.left + stage.width * 0.7
    ? Math.max(0, menu.left + menu.width - stage.left + 22) : 20
  const width = Math.max(120, stage.width - left - 20)
  const height = Math.max(120, bottom - 22)
  return { width, height, centerX: left + width / 2, centerY: 22 + height / 2 }
}

export function isPersonaPortraitShape(id: string): boolean {
  return id.startsWith("portrait_") && !id.startsWith("portrait_humanoid")
}
