import { useCallback, useEffect, useId, useState } from "react"
import {
  getLmStudioCatalog,
  pinLmStudioProfile,
  selectLmStudioProfile,
  setSelectedRuntimeProfileId,
  sortLmStudioProfiles,
  type LmStudioCatalogResponse,
  type LmStudioGradedProfile,
} from "../api"
import { GradedProfileHoverCard } from "./GradedProfileHoverCard"

export type LmStudioCatalogPickerProps = {
  variant?: "classic" | "hud"
  /** Called after a catalog row is selected and bound to a RuntimeProfile. */
  onSelected?: (runtimeProfileId: string) => void
  /** Currently active runtime profile id (for highlight). */
  activeRuntimeId?: string
  compact?: boolean
}

export function LmStudioCatalogPicker({
  variant = "classic",
  onSelected,
  activeRuntimeId = "",
  compact = false,
}: LmStudioCatalogPickerProps) {
  const listId = useId()
  const [catalog, setCatalog] = useState<LmStudioCatalogResponse | null>(null)
  const [showHidden, setShowHidden] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError("")
    try {
      const data = await getLmStudioCatalog(showHidden)
      setCatalog(data)
    } catch (err: unknown) {
      setCatalog(null)
      setError(err instanceof Error ? err.message : "Could not load LM Studio catalog.")
    }
  }, [showHidden])

  useEffect(() => {
    void load()
  }, [load])

  const profiles = catalog ? sortLmStudioProfiles(catalog.profiles) : []

  async function onPin(profile: LmStudioGradedProfile) {
    setBusyId(profile.id)
    setError("")
    try {
      await pinLmStudioProfile(profile.id, !profile.pinned)
      await load()
      setMsg(profile.pinned ? `Unpinned ${profile.display_name}.` : `Pinned ${profile.display_name}.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update pin.")
    } finally {
      setBusyId(null)
    }
  }

  async function onSelect(profile: LmStudioGradedProfile) {
    setBusyId(profile.id)
    setError("")
    try {
      const runtime = await selectLmStudioProfile(profile.id)
      const id = runtime.id || runtime.name
      setSelectedRuntimeProfileId(id)
      window.dispatchEvent(new CustomEvent("jarvis:runtime-profile-changed", { detail: { id } }))
      onSelected?.(id)
      const active = runtime.load?.active_model
      setMsg(
        active
          ? `Selected ${profile.display_name} (${String(active)}).`
          : `Selected ${profile.display_name}.`,
      )
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not select this profile.")
    } finally {
      setBusyId(null)
    }
  }

  function vramBadge(state: LmStudioGradedProfile["vram_state"]): string | null {
    if (state === "warn") return "VRAM caution"
    if (state === "hidden") return "Heavy"
    return null
  }

  const tone = variant === "hud" ? " hud-catalog" : " classic-catalog"

  return (
    <section className={`lm-catalog-picker${tone}${compact ? " compact" : ""}`} aria-labelledby={listId}>
      <div className="lm-catalog-head">
        <h3 id={listId}>{compact ? "LM Studio" : "LM Studio graded catalog"}</h3>
        {catalog?.vram_gb != null && (
          <span className="lm-catalog-vram">Node VRAM ~{catalog.vram_gb} GB</span>
        )}
      </div>
      <p className="lm-catalog-disclaimer">
        Estimates — not Jarvis-measured. Grades are provisional benchmarks, not live harness results.
      </p>

      {msg && <p className="lm-catalog-msg">{msg}</p>}
      {error && <p className="lm-catalog-error">{error}</p>}

      <label className="lm-show-hidden">
        <input
          type="checkbox"
          checked={showHidden}
          onChange={(event) => setShowHidden(event.target.checked)}
        />
        Show heavy models (&gt;16 GB)
      </label>

      {!catalog && !error && <p className="lede">Loading catalog…</p>}

      {profiles.length > 0 && (
        <ul className="lm-catalog-list" role="listbox" aria-label="Graded LM Studio profiles">
          {profiles.map((profile) => {
            const active = activeRuntimeId && profile.runtime_profile_id === activeRuntimeId
            const badge = vramBadge(profile.vram_state)
            const showCard = hoverId === profile.id || focusId === profile.id
            return (
              <li key={profile.id} className={`lm-catalog-row${active ? " active" : ""}`}>
                <div
                  className="lm-catalog-row-main"
                  tabIndex={0}
                  role="option"
                  aria-selected={!!active}
                  onMouseEnter={() => setHoverId(profile.id)}
                  onMouseLeave={() => setHoverId((id) => (id === profile.id ? null : id))}
                  onFocus={() => setFocusId(profile.id)}
                  onBlur={() => setFocusId((id) => (id === profile.id ? null : id))}
                >
                  <div className="lm-catalog-row-text">
                    <span className="lm-catalog-name">
                      {profile.pinned ? "★ " : ""}{profile.display_name}
                    </span>
                    <span className="lm-catalog-meta">
                      Overall {profile.overall.toFixed(1)} <em>(est.)</em>
                      {" · "}{profile.weight_gb.toFixed(1)} GB · {profile.quantization}
                      {!profile.matched ? " · unmatched" : ""}
                    </span>
                  </div>
                  <div className="lm-catalog-row-actions" onClick={(e) => e.stopPropagation()}>
                    {badge && <span className={`badge lm-vram-badge ${profile.vram_state}`}>{badge}</span>}
                    <button
                      type="button"
                      className={variant === "hud" ? "hud-icon-btn" : "btn secondary"}
                      disabled={busyId === profile.id}
                      onClick={() => onPin(profile)}
                      title={profile.pinned ? "Unpin" : "Pin"}
                    >
                      {profile.pinned ? "Unpin" : "Pin"}
                    </button>
                    <button
                      type="button"
                      className={variant === "hud" ? "hud-icon-btn" : "btn"}
                      disabled={busyId === profile.id}
                      onClick={() => onSelect(profile)}
                    >
                      {active ? "Selected" : "Select"}
                    </button>
                  </div>
                </div>
                {showCard && (
                  <div className="lm-catalog-card-wrap">
                    <GradedProfileHoverCard profile={profile} variant={variant} />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {catalog && profiles.length === 0 && !error && (
        <p className="lede">No graded profiles found. Check LM Studio models folder.</p>
      )}

      {catalog && catalog.ungraded.length > 0 && (
        <div className="lm-ungraded">
          <h4>Ungraded</h4>
          <p className="lede">Downloaded GGUFs without a graded catalog match.</p>
          <ul>
            {catalog.ungraded.map((item) => (
              <li key={item.path}>
                <span>{item.filename}</span>
                <span>{item.weight_gb.toFixed(1)} GB · {item.quantization || "—"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {catalog?.models_root && !compact && (
        <p className="lm-catalog-root lede">Models root: {catalog.models_root}</p>
      )}
    </section>
  )
}
