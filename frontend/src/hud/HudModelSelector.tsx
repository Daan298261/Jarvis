import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import {
  bindDiscoveredGguf,
  bindLmStudioProfile,
  getLmStudioCatalog,
  getSelectedRuntimeProfileId,
  listRuntimeProfiles,
  sortLmStudioProfiles,
  type LmStudioCatalogResponse,
  type LmStudioGradedProfile,
  type LmStudioUngradedModel,
  type RuntimeProfile,
} from "../api"
import { applyRuntimeProfile, playDiscoveredGguf, playLmStudioCatalogProfile } from "./applyRuntimeProfile"
import { hexStrikeSelectMessage } from "./hexstrikeAutostart"
import {
  clearSlot,
  HUD_MODEL_SLOT_COUNT,
  loadHudModelSlots,
  moveSlot,
  saveHudModelSlots,
  setSlotProfile,
  type HudModelSlotsV1,
} from "./modelSlots"
import { isHexStrikeSuiteProfile } from "./hexstrikeSuite"
import "./hexstrike.css"

export type HudModelSelectorProps = {
  model: { loaded?: boolean; loading?: boolean; active_model?: string; last_error?: string } | null
  onOpenChange?: (open: boolean) => void
}

type PinTarget = { label: string; catalogId?: string; path?: string }

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

function localRowActive(profile: LmStudioGradedProfile, selectedId: string): boolean {
  if (!selectedId) return false
  if (profile.runtime_profile_id && profile.runtime_profile_id === selectedId) return true
  return false
}

export function HudModelSelector({ model, onOpenChange }: HudModelSelectorProps) {
  const menuId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [configure, setConfigure] = useState(false)
  const [slotsState, setSlotsState] = useState<HudModelSlotsV1>(() => loadHudModelSlots())
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([])
  const [profilesError, setProfilesError] = useState(false)
  const [catalog, setCatalog] = useState<LmStudioCatalogResponse | null>(null)
  const [catalogUnavailable, setCatalogUnavailable] = useState(false)
  const [selectedId, setSelectedId] = useState(getSelectedRuntimeProfileId)
  const [busySlot, setBusySlot] = useState<number | null>(null)
  const [busyLocalId, setBusyLocalId] = useState<string | null>(null)
  const [msg, setMsg] = useState("")
  const [assignIndex, setAssignIndex] = useState<number | null>(null)
  const [pinTarget, setPinTarget] = useState<PinTarget | null>(null)
  const [pinning, setPinning] = useState(false)

  const transferring = busySlot !== null || busyLocalId !== null || !!model?.loading
  const [loadElapsed, setLoadElapsed] = useState(0)

  useEffect(() => {
    if (!transferring) {
      setLoadElapsed(0)
      return
    }
    const started = Date.now()
    const timer = window.setInterval(() => {
      setLoadElapsed(Math.floor((Date.now() - started) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [transferring])

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

  const refreshCatalog = useCallback(async () => {
    try {
      const data = await getLmStudioCatalog(false)
      setCatalog(data)
      setCatalogUnavailable(false)
    } catch {
      setCatalog(null)
      setCatalogUnavailable(true)
    }
  }, [])

  useEffect(() => {
    void refreshProfiles()
  }, [refreshProfiles])

  useEffect(() => {
    if (!open) return
    void refreshProfiles()
    void refreshCatalog()
  }, [open, refreshCatalog, refreshProfiles])

  useEffect(() => {
    onOpenChange?.(open)
  }, [open, onOpenChange])

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
        setPinTarget(null)
      }
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const localGraded = useMemo(
    () => (catalog ? sortLmStudioProfiles(catalog.profiles) : []),
    [catalog],
  )
  const localUngraded = catalog?.ungraded ?? []

  const selectedProfile = useMemo(
    () => profiles.find((p) => profileMatches(p, selectedId)) || null,
    [profiles, selectedId],
  )
  const hexstrikeProfile = useMemo(
    () => profiles.find((profile) => isHexStrikeSuiteProfile(profile)) || null,
    [profiles],
  )
  const hexstrikeActive = !!(selectedProfile && isHexStrikeSuiteProfile(selectedProfile))

  const headline = useMemo(() => {
    if (transferring) return "Loading model…"
    if (model?.loading) return "Loading…"
    if (hexstrikeActive && selectedProfile) return selectedProfile.label || selectedProfile.name
    // The server's identity wins over a stale shortcut/catalog label.
    if (model?.active_model) {
      const parts = model.active_model.split(/[\\/]/)
      return parts.find((part) => /\d+(?:\.\d+)?b(?:$|[-_@])/i.test(part)) || parts.at(-1) || model.active_model
    }
    if (selectedProfile) return selectedProfile.label || selectedProfile.name
    return "Model"
  }, [hexstrikeActive, model?.active_model, model?.loading, selectedProfile, transferring])

  const subline = useMemo(() => {
    if (transferring) return "Loading model"
    if (model?.loading) return "Switching runtime"
    if (hexstrikeActive) return "Cybersecurity suite"
    if (model?.loaded && model.active_model) return model.active_model
    if (selectedProfile) return selectedProfile.model
    return profilesError ? "Offline" : "Pick a slot"
  }, [hexstrikeActive, model, profilesError, selectedProfile, transferring])

  function setOpenState(next: boolean) {
    setOpen(next)
    if (!next) {
      setConfigure(false)
      setAssignIndex(null)
      setPinTarget(null)
    }
  }

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
    } catch (err: unknown) {
      const text = err instanceof Error ? err.message : "Could not load this slot."
      setMsg(text.length > 180 ? `${text.slice(0, 177)}…` : text)
    } finally {
      setBusySlot(null)
    }
  }

  async function onSwapSuite() {
    if (!hexstrikeProfile) return
    setBusySlot(-1)
    setMsg("")
    try {
      const applied = await applyRuntimeProfile(hexstrikeProfile.id || hexstrikeProfile.name)
      setSelectedId(applied.id || applied.name)
      setMsg(hexStrikeSelectMessage(!!applied.hexStrikeAutoStarted))
      setOpenState(false)
    } catch {
      setMsg("Could not open HexStrike.")
    } finally {
      setBusySlot(null)
    }
  }

  async function onPlayLocal(profile: LmStudioGradedProfile) {
    setBusyLocalId(profile.id)
    setMsg("")
    try {
      const applied = await playLmStudioCatalogProfile(profile.id)
      setSelectedId(applied.id || applied.name)
      setMsg(`Loaded ${profile.display_name}.`)
      void refreshProfiles()
      void refreshCatalog()
    } catch (err: unknown) {
      const text = err instanceof Error ? err.message : "Could not load model."
      setMsg(text.length > 96 ? `${text.slice(0, 93)}…` : text)
    } finally {
      setBusyLocalId(null)
    }
  }

  async function pinModelToSlot(target: PinTarget, index: number) {
    setPinning(true)
    setMsg("")
    try {
      const runtime = target.catalogId
        ? await bindLmStudioProfile(target.catalogId)
        : await bindDiscoveredGguf(target.path!)
      const next = setSlotProfile(slotsState, index, runtime.id || runtime.name, target.label)
      persistSlots(next)
      setAssignIndex(null)
      setPinTarget(null)
      setMsg(`Pinned ${target.label} to slot ${index + 1}. Current model unchanged.`)
      void refreshProfiles()
      void refreshCatalog()
    } catch (err: unknown) {
      setMsg(err instanceof Error ? err.message : "Could not pin this local model.")
    } finally {
      setPinning(false)
    }
  }

  function choosePinTarget(target: PinTarget) {
    if (configure && assignIndex != null) void pinModelToSlot(target, assignIndex)
    else setPinTarget(target)
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

  async function onPlayUngraded(item: LmStudioUngradedModel) {
    setBusyLocalId(item.path)
    setMsg("")
    try {
      const applied = await playDiscoveredGguf(item.path)
      setSelectedId(applied.id || applied.name)
      setMsg(`Loaded ${item.filename}.`)
      void refreshProfiles()
      void refreshCatalog()
    } catch (err: unknown) {
      const text = err instanceof Error ? err.message : "Could not load model."
      setMsg(text.length > 96 ? `${text.slice(0, 93)}…` : text)
    } finally {
      setBusyLocalId(null)
    }
  }

  function renderUngradedRow(item: LmStudioUngradedModel) {
    const busy = busyLocalId === item.path
    return (
      <li key={item.path} className="hud-model-local-row ungraded">
        <div className="hud-model-local-text">
          <span className="hud-model-local-name">
            <span className="hud-model-local-badge">local</span>
            {item.filename}
          </span>
          <span className="hud-model-local-meta">
            {item.weight_gb.toFixed(1)} GiB weights · {item.quantization || "Quant unknown"}
          </span>
          <span className="hud-model-local-meta">{item.speed_label || "Speed unmeasured"}</span>
          <span className="hud-model-local-meta">{item.restriction_label || "Restrictions unverified"}</span>
        </div>
        <div className="hud-model-local-actions">
          <button type="button" className="hud-icon-btn hud-model-pin-btn"
            disabled={transferring || pinning}
            onClick={() => choosePinTarget({ label: item.filename, path: item.path })}
            title={`Save ${item.filename} to a shortcut without loading`} aria-label={`Pin ${item.filename}`}>
            Pin
          </button>
          <button
            type="button"
            className="hud-icon-btn hud-model-play-btn"
            disabled={transferring || busy || pinning}
            onClick={() => void onPlayUngraded(item)}
            title={`Load ${item.filename} now`}
            aria-label={`Load ${item.filename}`}
          >
            ▶ Load
          </button>
        </div>
      </li>
    )
  }

  function renderGradedRow(profile: LmStudioGradedProfile) {
    const active = localRowActive(profile, selectedId)
    const busy = busyLocalId === profile.id
    return (
      <li key={profile.id} className={`hud-model-local-row${active ? " active" : ""}${profile.matched ? "" : " unavailable"}`}>
        <div className="hud-model-local-text">
          <span className="hud-model-local-name">
            <span className="hud-model-local-badge">{profile.matched ? "Installed" : "Not installed"}</span>
            {profile.pinned ? "★ " : ""}
            {profile.display_name}
          </span>
          <span className="hud-model-local-meta">
            {profile.weight_gb.toFixed(1)} GiB weights{profile.matched ? "" : " (estimate)"} · {profile.quantization}
          </span>
          <span className="hud-model-local-meta">{profile.speed_label || "Speed unmeasured"}</span>
          <span className="hud-model-local-meta" title={profile.source_notes}>
            {profile.restriction_label || "Restrictions unverified"}
          </span>
          {profile.path && <span className="hud-model-artifact" title={profile.path}>
            File: {profile.filename || profile.path.split(/[\\/]/).pop()}
          </span>}
        </div>
        <div className="hud-model-local-actions">
            <button
              type="button"
              className="hud-icon-btn hud-model-pin-btn"
              disabled={transferring || pinning || !profile.matched}
              onClick={() => choosePinTarget({ label: profile.display_name, catalogId: profile.id })}
              title="Save a shortcut without loading"
              aria-label={`Pin ${profile.display_name}`}
            >
              Pin
            </button>
          <button
            type="button"
            className="hud-icon-btn hud-model-play-btn"
            disabled={transferring || busy || pinning || !profile.matched}
            onClick={() => void onPlayLocal(profile)}
            title={profile.matched ? `Load ${profile.display_name} now` : "Download this model first"}
            aria-label={`Load ${profile.display_name}`}
          >
            ▶ Load
          </button>
        </div>
      </li>
    )
  }

  const localEmpty =
    catalog && localGraded.length === 0 && localUngraded.length === 0 && !catalogUnavailable

  return (
    <div className="hud-model-selector" ref={rootRef}>
      <button
        type="button"
        className={`hud-model-trigger${open ? " open" : ""}${transferring ? " transferring" : ""}`}
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls={menuId}
        aria-busy={transferring}
        onClick={() => setOpenState(!open)}
        title="Switch local model"
      >
        <span className="hud-model-trigger-label">{headline}</span>
        <span className="hud-model-trigger-meta">{subline}</span>
      </button>

      {open && (
        <div className="hud-model-menu" id={menuId} role="dialog" aria-label="Switch local model">
          <div className="hud-model-menu-head">
            <span className="hud-model-menu-title">Model</span>
            <button
              type="button"
              className="hud-icon-btn hud-model-config-toggle"
              disabled={pinning}
              onClick={() => {
                setConfigure((c) => !c)
                setAssignIndex(null)
              }}
            >
              {configure ? "Done" : "Edit shortcuts"}
            </button>
          </div>

          <p className="hud-model-action-hint">▶ Load switches model now. Pin saves a shortcut.</p>
          <p className="hud-model-action-hint">Speed is estimated. Refusal-reduced models can still refuse.</p>
          {model?.loaded && model.active_model && !hexstrikeActive && (
            <p className="hud-model-serving" title={model.active_model}>Serving: {model.active_model}</p>
          )}

          {transferring && (
            <p className="hud-model-transferring" role="status">
              Loading model{loadElapsed > 0 ? ` (${loadElapsed}s)` : ""}… You can close this menu.
            </p>
          )}

          {msg && <p className="hud-model-msg">{msg}</p>}
          {(profilesError || catalogUnavailable) && !transferring && (
            <button
              type="button"
              className="hud-icon-btn hud-model-retry"
              onClick={() => {
                setMsg("Checking local models…")
                void Promise.all([refreshProfiles(), refreshCatalog()]).then(() => setMsg(""))
              }}
            >
              Retry local models
            </button>
          )}
          {model?.last_error && !transferring && (
            <p className="hud-model-error">{model.last_error}</p>
          )}

          {hexstrikeProfile && (
            <button
              type="button"
              className={`hud-model-suite-row${hexstrikeActive ? " active" : ""}`}
              disabled={transferring}
              onClick={() => void onSwapSuite()}
            >
              <span className="mark" aria-hidden>
                ⬡
              </span>
              <span>{hexstrikeProfile.label || "HexStrike AI"}</span>
              <span className="meta">Cyber suite</span>
            </button>
          )}

          <div
            className="hud-model-slots"
            role="group"
            aria-label="Pinned runtime slots"
            aria-disabled={transferring || pinning}
          >
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
                        disabled={index === 0 || transferring || pinning}
                        onClick={() => onMoveSlot(index, -1)}
                        title="Move left"
                      >
                        ←
                      </button>
                      <button
                        type="button"
                        className="hud-icon-btn"
                        disabled={index === HUD_MODEL_SLOT_COUNT - 1 || transferring || pinning}
                        onClick={() => onMoveSlot(index, 1)}
                        title="Move right"
                      >
                        →
                      </button>
                      <button
                        type="button"
                        className="hud-icon-btn"
                        disabled={!filled || transferring || pinning}
                        onClick={() => onClearSlot(index)}
                        title="Clear slot"
                      >
                        ×
                      </button>
                      <button
                        type="button"
                        className="hud-icon-btn"
                        disabled={transferring || pinning}
                        onClick={() => setAssignIndex(index)}
                        title="Assign profile"
                      >
                        …
                      </button>
                    </div>
                  )}
                  <button
                    type="button"
                    className={`hud-model-slot${active ? " active" : ""}${filled ? "" : " empty"}${transferring ? " disabled" : ""}`}
                    disabled={transferring || pinning || busySlot === index}
                    onClick={() => (configure ? setAssignIndex(index) : onSwapSlot(index))}
                    title={configure ? `Edit shortcut ${index + 1}` : filled ? `Load ${label}` : `Empty slot ${index + 1}`}
                  >
                    <span className="hud-model-slot-idx">{configure ? "Pin" : filled ? "▶ Load" : "Pin"} {index + 1}</span>
                    <span className="hud-model-slot-label">{filled ? label : "+"}</span>
                  </button>
                </div>
              )
            })}
          </div>

          {pinTarget && (
            <div className="hud-model-pin-target" role="group" aria-label="Choose shortcut slot">
              <p className="hud-model-assign-hint">Pin {pinTarget.label} to a slot:</p>
              <div className="hud-model-pin-slots">
                {slotsState.slots.map((slot, index) => (
                  <button type="button" className="hud-icon-btn" key={index}
                    disabled={transferring || pinning}
                    title={slot.profileId ? `Replace ${slotLabel(slot, profiles)}` : "Empty slot"}
                    onClick={() => void pinModelToSlot(pinTarget, index)}>
                    Slot {index + 1}{slot.profileId ? " (replace)" : ""}
                  </button>
                ))}
              </div>
              <button type="button" className="hud-icon-btn" disabled={pinning} onClick={() => setPinTarget(null)}>Cancel</button>
            </div>
          )}

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
                      disabled={transferring || pinning}
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

          <section className="hud-model-local" aria-label="Local LM Studio models">
              <div className="hud-model-local-head">
                <span className="hud-model-local-title">Local</span>
                {catalog?.vram_gb != null && (
                  <span className="hud-model-local-vram">~{catalog.vram_gb} GB VRAM</span>
                )}
              </div>
              {catalogUnavailable && (
                <p className="hud-model-local-hint">Local catalog unavailable.</p>
              )}
              {!catalog && !catalogUnavailable && (
                <p className="hud-model-local-hint">Loading local models…</p>
              )}
              {localEmpty && (
                <p className="hud-model-local-hint">No local GGUFs found under LM Studio models.</p>
              )}
              {(localGraded.length > 0 || localUngraded.length > 0) && (
                <ul className="hud-model-local-list">
                  {localGraded.map(renderGradedRow)}
                  {localUngraded.map(renderUngradedRow)}
                </ul>
              )}
            </section>

          <div className="hud-model-menu-foot">
            <Link to="/model" className="hud-model-more" onClick={() => setOpenState(false)}>
              More →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
