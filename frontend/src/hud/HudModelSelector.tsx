import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import {
  getSelectedRuntimeProfileId,
  listRuntimeProfiles,
  type RuntimeProfile,
} from "../api"
import { applyRuntimeProfile } from "./applyRuntimeProfile"
import {
  clearSlot,
  HUD_MODEL_SLOT_COUNT,
  loadHudModelSlots,
  moveSlot,
  saveHudModelSlots,
  setSlotProfile,
  type HudModelSlotsV1,
} from "./modelSlots"

export type HudModelSelectorProps = {
  model: { loaded?: boolean; loading?: boolean; active_model?: string; last_error?: string } | null
}

function profileMatches(profile: RuntimeProfile, id: string): boolean {
  if (!id) return false
  return profile.id === id || profile.name === id
}

function selectionMatchesSlot(
  slotProfileId: string,
  selected: string,
  profiles: RuntimeProfile[],
): boolean {
  if (!slotProfileId || !selected) return false
  if (slotProfileId === selected) return true
  const slotProfile = profiles.find((p) => profileMatches(p, slotProfileId))
  const selectedProfile = profiles.find((p) => profileMatches(p, selected))
  if (slotProfile && selectedProfile) return slotProfile.id === selectedProfile.id
  return false
}

function slotLabel(
  slot: { profileId: string; label?: string },
  profiles: RuntimeProfile[],
): string {
  if (!slot.profileId) return "—"
  if (slot.label?.trim()) return slot.label.trim()
  const profile = profiles.find((p) => profileMatches(p, slot.profileId))
  if (profile) return profile.label || profile.name
  return slot.profileId.slice(0, 8)
}

export function HudModelSelector({ model }: HudModelSelectorProps) {
  const menuId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [configure, setConfigure] = useState(false)
  const [slotsState, setSlotsState] = useState<HudModelSlotsV1>(() => loadHudModelSlots())
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([])
  const [profilesError, setProfilesError] = useState(false)
  const [selectedId, setSelectedId] = useState(getSelectedRuntimeProfileId)
  const [busySlot, setBusySlot] = useState<number | null>(null)
  const [msg, setMsg] = useState("")
  const [assignIndex, setAssignIndex] = useState<number | null>(null)

  const persistSlots = useCallback((next: HudModelSlotsV1) => {
    setSlotsState(next)
    saveHudModelSlots(next)
  }, [])

  const refreshProfiles = useCallback(async () => {
    try {
      const data = await listRuntimeProfiles()
      setProfiles(data.profiles || [])
      setProfilesError(false)
    } catch {
      setProfiles([])
      setProfilesError(true)
    }
  }, [])

  useEffect(() => {
    void refreshProfiles()
  }, [refreshProfiles])

  useEffect(() => {
    const onRuntimeChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail
      setSelectedId(detail?.id ?? getSelectedRuntimeProfileId())
    }
    window.addEventListener("jarvis:runtime-profile-changed", onRuntimeChange)
    return () => window.removeEventListener("jarvis:runtime-profile-changed", onRuntimeChange)
  }, [])

  useEffect(() => {
    if (!open) return
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
        setConfigure(false)
        setAssignIndex(null)
      }
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const selectedProfile = useMemo(
    () => profiles.find((p) => profileMatches(p, selectedId)) || null,
    [profiles, selectedId],
  )

  const headline = useMemo(() => {
    if (model?.loading) return "Loading…"
    if (selectedProfile) return selectedProfile.label || selectedProfile.name
    if (model?.active_model) return model.active_model
    return "Model"
  }, [model?.active_model, model?.loading, selectedProfile])

  const subline = useMemo(() => {
    if (model?.loading) return "Switching runtime"
    if (model?.loaded && model.active_model) return model.active_model
    if (selectedProfile) return selectedProfile.model
    return profilesError ? "Offline" : "Pick a slot"
  }, [model, profilesError, selectedProfile])

  async function onSwapSlot(index: number) {
    const slot = slotsState.slots[index]
    if (!slot.profileId) {
      setConfigure(true)
      setAssignIndex(index)
      return
    }
    setBusySlot(index)
    setMsg("")
    try {
      const applied = await applyRuntimeProfile(slot.profileId)
      setSelectedId(applied.id || applied.name)
      setMsg(`Loaded ${applied.label || applied.name}.`)
    } catch {
      setMsg("Could not load this slot.")
    } finally {
      setBusySlot(null)
    }
  }

  function onAssignProfile(profile: RuntimeProfile) {
    if (assignIndex == null) return
    const next = setSlotProfile(slotsState, assignIndex, profile.id, profile.label || profile.name)
    persistSlots(next)
    setAssignIndex(null)
    setMsg(`Pinned ${profile.label || profile.name} to slot ${assignIndex + 1}.`)
  }

  function onClearSlot(index: number) {
    persistSlots(clearSlot(slotsState, index))
    setMsg(`Cleared slot ${index + 1}.`)
  }

  function onMoveSlot(index: number, direction: -1 | 1) {
    const to = index + direction
    if (to < 0 || to >= HUD_MODEL_SLOT_COUNT) return
    persistSlots(moveSlot(slotsState, index, to))
  }

  return (
    <div className="hud-model-selector" ref={rootRef}>
      <button
        type="button"
        className={`hud-model-trigger${open ? " open" : ""}`}
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
        title="Model hotswap (HUD_MODEL_HOTSWAP)"
      >
        <span className="hud-model-trigger-label">{headline}</span>
        <span className="hud-model-trigger-meta">{subline}</span>
      </button>

      {open && (
        <div className="hud-model-menu" id={menuId} role="dialog" aria-label="Model hotswap">
          <div className="hud-model-menu-head">
            <span className="hud-model-menu-title">Hotswap</span>
            <button
              type="button"
              className="hud-icon-btn hud-model-config-toggle"
              onClick={() => {
                setConfigure((c) => !c)
                setAssignIndex(null)
              }}
            >
              {configure ? "Done" : "Pin"}
            </button>
          </div>

          {msg && <p className="hud-model-msg">{msg}</p>}
          {model?.last_error && <p className="hud-model-error">{model.last_error}</p>}

          <div className="hud-model-slots" role="group" aria-label="Pinned runtime slots">
            {slotsState.slots.map((slot, index) => {
              const active = selectionMatchesSlot(slot.profileId, selectedId, profiles)
              const filled = !!slot.profileId
              const label = slotLabel(slot, profiles)
              return (
                <div key={index} className={`hud-model-slot-wrap${configure ? " configuring" : ""}`}>
                  {configure && (
                    <div className="hud-model-slot-tools">
                      <button
                        type="button"
                        className="hud-icon-btn"
                        disabled={index === 0}
                        onClick={() => onMoveSlot(index, -1)}
                        title="Move left"
                      >
                        ←
                      </button>
                      <button
                        type="button"
                        className="hud-icon-btn"
                        disabled={index === HUD_MODEL_SLOT_COUNT - 1}
                        onClick={() => onMoveSlot(index, 1)}
                        title="Move right"
                      >
                        →
                      </button>
                      <button
                        type="button"
                        className="hud-icon-btn"
                        disabled={!filled}
                        onClick={() => onClearSlot(index)}
                        title="Clear slot"
                      >
                        ×
                      </button>
                      <button
                        type="button"
                        className="hud-icon-btn"
                        onClick={() => setAssignIndex(index)}
                        title="Assign profile"
                      >
                        …
                      </button>
                    </div>
                  )}
                  <button
                    type="button"
                    className={`hud-model-slot${active ? " active" : ""}${filled ? "" : " empty"}`}
                    disabled={busySlot === index}
                    onClick={() => (configure ? setAssignIndex(index) : onSwapSlot(index))}
                    title={filled ? label : `Empty slot ${index + 1}`}
                  >
                    <span className="hud-model-slot-idx">{index + 1}</span>
                    <span className="hud-model-slot-label">{filled ? label : "+"}</span>
                  </button>
                </div>
              )
            })}
          </div>

          {configure && assignIndex != null && (
            <div className="hud-model-assign" aria-label="Pick runtime profile">
              <p className="hud-model-assign-hint">
                Slot {assignIndex + 1}
                {profilesError ? " — runtimes unavailable" : ""}
              </p>
              <ul className="hud-model-assign-list">
                {profiles.map((profile) => (
                  <li key={profile.id}>
                    <button
                      type="button"
                      className="hud-model-assign-row"
                      onClick={() => onAssignProfile(profile)}
                    >
                      <span>{profile.label || profile.name}</span>
                      <span className="hud-model-assign-meta">{profile.model}</span>
                    </button>
                  </li>
                ))}
                {!profiles.length && !profilesError && <li className="hud-model-assign-empty">No runtimes</li>}
              </ul>
            </div>
          )}

          <div className="hud-model-menu-foot">
            <Link to="/model" className="hud-model-more" onClick={() => setOpen(false)}>
              More →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
