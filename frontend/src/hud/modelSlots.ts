/** HUD_MODEL_HOTSWAP — slot persistence (RFC number will align later). */

export const HUD_MODEL_SLOTS_STORAGE_KEY = "jarvis.hud.modelSlots.v1"
export const HUD_MODEL_SLOT_COUNT = 6

export type HudModelSlotEntry = {
  /** Runtime profile id (from `/api/runtime-profiles`). */
  profileId: string
  /** Optional short label override for the slot chip. */
  label?: string
}

export type HudModelSlotsV1 = {
  slots: HudModelSlotEntry[]
}

function emptySlots(): HudModelSlotEntry[] {
  return Array.from({ length: HUD_MODEL_SLOT_COUNT }, () => ({ profileId: "" }))
}

export function loadHudModelSlots(): HudModelSlotsV1 {
  try {
    const raw = localStorage.getItem(HUD_MODEL_SLOTS_STORAGE_KEY)
    if (!raw) return { slots: emptySlots() }
    const parsed = JSON.parse(raw) as Partial<HudModelSlotsV1>
    const slots = Array.isArray(parsed.slots) ? parsed.slots : []
    const normalized = emptySlots()
    for (let i = 0; i < HUD_MODEL_SLOT_COUNT; i++) {
      const item = slots[i]
      if (item && typeof item.profileId === "string") {
        normalized[i] = {
          profileId: item.profileId,
          label: typeof item.label === "string" ? item.label : undefined,
        }
      }
    }
    return { slots: normalized }
  } catch {
    return { slots: emptySlots() }
  }
}

export function saveHudModelSlots(state: HudModelSlotsV1): void {
  try {
    localStorage.setItem(HUD_MODEL_SLOTS_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // ignore
  }
}

export function setSlotProfile(
  state: HudModelSlotsV1,
  index: number,
  profileId: string,
  label?: string,
): HudModelSlotsV1 {
  if (index < 0 || index >= HUD_MODEL_SLOT_COUNT) return state
  const slots = state.slots.map((slot, i) =>
    i === index
      ? { profileId, label: label?.trim() || undefined }
      : slot,
  )
  return { slots }
}

export function clearSlot(state: HudModelSlotsV1, index: number): HudModelSlotsV1 {
  return setSlotProfile(state, index, "")
}

export function moveSlot(state: HudModelSlotsV1, from: number, to: number): HudModelSlotsV1 {
  if (
    from < 0 ||
    from >= HUD_MODEL_SLOT_COUNT ||
    to < 0 ||
    to >= HUD_MODEL_SLOT_COUNT ||
    from === to
  ) {
    return state
  }
  const slots = [...state.slots]
  const [item] = slots.splice(from, 1)
  slots.splice(to, 0, item)
  return { slots }
}
