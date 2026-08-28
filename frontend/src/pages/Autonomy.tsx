import { useEffect, useMemo, useState, type FormEvent } from "react"
import {
  PERSISTENCE_MODES,
  PROACTIVITY_MODES,
  approveProactiveAction,
  createAutonomyProfile,
  getAutonomyProfile,
  getAwayMode,
  getEffectiveProactivityMatrix,
  listAutonomyModes,
  listAutonomyProfiles,
  listProactiveActions,
  putAwayMode,
  updateAutonomyProfile,
  type AutonomyProfile,
  type AwayModeState,
  type EffectiveBehavior,
  type EffectiveProactivityRow,
  type PersistenceMode,
  type ProactiveAction,
  type ProactivityMode,
} from "../api"

type FormState = {
  name: string
  persistence: PersistenceMode
  proactivity: ProactivityMode
  agent_id: string
}

const PERSISTENCE_COPY: Record<PersistenceMode, { title: string; body: string }> = {
  ONE_SHOT: {
    title: "This request",
    body: "Finish what I asked, then stop.",
  },
  UNTIL_COMPLETE: {
    title: "Until it's done",
    body: "Keep going until the job finishes.",
  },
  CONTINUOUS: {
    title: "Keep watching",
    body: "Stay on after this job. This does not let Jarvis invent new work.",
  },
}

const PROACTIVITY_COPY: Record<ProactivityMode, { title: string; body: string }> = {
  DISABLED: {
    title: "Wait for me",
    body: "Only act when I ask.",
  },
  SUGGEST_ONLY: {
    title: "Suggest",
    body: "Propose work. Nothing runs until I say yes.",
  },
  CREATE_TASKS: {
    title: "Queue jobs",
    body: "Can open new jobs. They still wait for my OK before they run.",
  },
  EXECUTE_WITHIN_POLICY: {
    title: "Act within limits",
    body: "Can start and do bounded work under the rules already set.",
  },
}

function isPersistence(value: string): value is PersistenceMode {
  return (PERSISTENCE_MODES as readonly string[]).includes(value)
}

function isProactivity(value: string): value is ProactivityMode {
  return (PROACTIVITY_MODES as readonly string[]).includes(value)
}

function persistenceLabel(mode: string): string {
  return isPersistence(mode) ? PERSISTENCE_COPY[mode].title : mode
}

function proactivityLabel(mode: string): string {
  return isProactivity(mode) ? PROACTIVITY_COPY[mode].title : mode
}

function emptyForm(): FormState {
  return {
    name: "",
    persistence: "ONE_SHOT",
    proactivity: "DISABLED",
    agent_id: "",
  }
}

function formFromProfile(profile: AutonomyProfile): FormState {
  return {
    name: profile.name,
    persistence: isPersistence(profile.persistence) ? profile.persistence : "ONE_SHOT",
    proactivity: isProactivity(profile.proactivity) ? profile.proactivity : "DISABLED",
    agent_id: profile.agent_id || "",
  }
}

function persistenceFingerprint(profiles: AutonomyProfile[]): string {
  return profiles
    .map((profile) => `${profile.id}:${profile.persistence}`)
    .sort()
    .join("|")
}

function effectiveSentence(behavior: EffectiveBehavior | null, persistence: string): string {
  const stay = persistenceLabel(behavior?.persistence || persistence)
  let start: string
  if (!behavior) {
    start = "Loading what is in effect…"
  } else if (behavior.can_execute_within_policy) {
    start = "Jarvis may start and do bounded work under your rules."
  } else if (behavior.can_create_tasks) {
    start = "Jarvis may open new jobs, but they wait for your OK before they run."
  } else if (behavior.can_suggest) {
    start = "Jarvis may only suggest. Nothing runs until you approve."
  } else if (behavior.away_mode?.enabled && behavior.away_mode.pause_proactivity) {
    start = "New work Jarvis would start on its own is paused while you are away."
  } else {
    start = "Jarvis will not start work on its own."
  }
  return `Stay with a job: ${stay}. ${start}`
}

function actionNeedsApproval(action: ProactiveAction): boolean {
  if (!action.requires_approval) return false
  return action.status === "suggested" || action.status === "pending_approval"
}

function actionStatusLabel(status: string): string {
  if (status === "suggested" || status === "pending_approval") return "Waiting for you"
  if (status === "queued") return "Queued"
  if (status === "executed") return "Done"
  if (status === "rejected") return "Turned down"
  return status
}

export function AutonomySection() {
  const [persistenceModes, setPersistenceModes] = useState<string[]>([...PERSISTENCE_MODES])
  const [proactivityModes, setProactivityModes] = useState<string[]>([...PROACTIVITY_MODES])
  const [profiles, setProfiles] = useState<AutonomyProfile[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<AutonomyProfile | null>(null)
  const [away, setAway] = useState<AwayModeState | null>(null)
  const [awayMessage, setAwayMessage] = useState("")
  const [matrix, setMatrix] = useState<EffectiveProactivityRow[]>([])
  const [actions, setActions] = useState<ProactiveAction[]>([])
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [error, setError] = useState("")
  const [persistenceNote, setPersistenceNote] = useState("")

  const selectedEffective = selected?.effective || null
  const formOpen = creating || !!editingId
  const awayPauses = !!(away?.enabled && away.pause_proactivity)

  const matrixByConfigured = useMemo(() => {
    const map = new Map<string, EffectiveProactivityRow>()
    for (const row of matrix) map.set(row.configured, row)
    return map
  }, [matrix])

  async function refreshAll(preferredId?: string | null) {
    const [modeData, profileData, awayData, matrixData, actionData] = await Promise.all([
      listAutonomyModes().catch(() => ({
        persistence_modes: [...PERSISTENCE_MODES],
        proactivity_modes: [...PROACTIVITY_MODES],
      })),
      listAutonomyProfiles(),
      getAwayMode(),
      getEffectiveProactivityMatrix(),
      listProactiveActions().catch(() => ({ actions: [] as ProactiveAction[] })),
    ])
    const nextProfiles = profileData.profiles || []
    setPersistenceModes(modeData.persistence_modes?.length ? modeData.persistence_modes : [...PERSISTENCE_MODES])
    setProactivityModes(modeData.proactivity_modes?.length ? modeData.proactivity_modes : [...PROACTIVITY_MODES])
    setProfiles(nextProfiles)
    setAway(awayData)
    setAwayMessage(awayData.message || "")
    setMatrix(matrixData.rows || [])
    setActions(actionData.actions || [])

    const nextId =
      preferredId && nextProfiles.some((profile) => profile.id === preferredId)
        ? preferredId
        : selectedId && nextProfiles.some((profile) => profile.id === selectedId)
          ? selectedId
          : nextProfiles[0]?.id || null
    setSelectedId(nextId)
    if (nextId) {
      const detailed = await getAutonomyProfile(nextId)
      setSelected(detailed)
    } else {
      setSelected(null)
    }
    return nextProfiles
  }

  useEffect(() => {
    let cancelled = false
    refreshAll().catch((err: unknown) => {
      if (cancelled) return
      setError(err instanceof Error ? err.message : "Could not load how Jarvis stays with a job.")
    })
    return () => {
      cancelled = true
    }
  }, [])

  function patchForm(patch: Partial<FormState>) {
    setForm((current) => ({ ...current, ...patch }))
  }

  function startCreate() {
    setCreating(true)
    setEditingId(null)
    setForm(emptyForm())
    setMsg("")
    setError("")
  }

  function startEdit(profile: AutonomyProfile) {
    setCreating(false)
    setEditingId(profile.id)
    setForm(formFromProfile(profile))
    setMsg("")
    setError("")
  }

  function cancelForm() {
    setCreating(false)
    setEditingId(null)
    setForm(emptyForm())
  }

  async function selectProfile(profile: AutonomyProfile) {
    setSelectedId(profile.id)
    try {
      setSelected(await getAutonomyProfile(profile.id))
    } catch (err: unknown) {
      setSelected(profile)
      setError(err instanceof Error ? err.message : "Could not load what is in effect.")
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const name = form.name.trim()
    if (!name) {
      setError("Give this setup a short name.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    try {
      if (creating) {
        const created = await createAutonomyProfile({
          name,
          persistence: form.persistence,
          proactivity: form.proactivity,
          agent_id: form.agent_id.trim(),
        })
        cancelForm()
        await refreshAll(created.id)
        setMsg(`Saved “${created.name}”. Stay with a job and start-on-its-own are stored separately.`)
      } else if (editingId) {
        const updated = await updateAutonomyProfile(editingId, {
          name,
          persistence: form.persistence,
          proactivity: form.proactivity,
          agent_id: form.agent_id.trim(),
        })
        cancelForm()
        await refreshAll(updated.id)
        setMsg(`Updated “${updated.name}”.`)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save this setup.")
    } finally {
      setBusy(false)
    }
  }

  async function onToggleAway(enabled: boolean) {
    setBusy(true)
    setError("")
    setMsg("")
    setPersistenceNote("")
    const before = persistenceFingerprint(profiles)
    try {
      const next = await putAwayMode({
        enabled,
        pause_proactivity: away?.pause_proactivity !== false,
        message: awayMessage,
      })
      const afterProfiles = await refreshAll(selectedId)
      const after = persistenceFingerprint(afterProfiles)
      if (before && after && before !== after) {
        setPersistenceNote("Unexpected change to how long Jarvis stays with a job. Check the setups below.")
      } else if (enabled) {
        setPersistenceNote("How long Jarvis stays with a job is unchanged. Only new work it would start on its own is paused.")
      } else {
        setPersistenceNote("Away Mode is off. Start-on-its-own is back to each setup’s saved choice.")
      }
      setAway(next)
      setMsg(enabled ? "Away Mode is on." : "Away Mode is off.")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update Away Mode.")
    } finally {
      setBusy(false)
    }
  }

  async function onSaveAwayDetails() {
    setBusy(true)
    setError("")
    try {
      const next = await putAwayMode({
        enabled: !!away?.enabled,
        pause_proactivity: away?.pause_proactivity !== false,
        message: awayMessage,
      })
      await refreshAll(selectedId)
      setAway(next)
      setMsg("Away Mode note saved. Job-stay settings were not rewritten.")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save Away Mode.")
    } finally {
      setBusy(false)
    }
  }

  async function onPauseChange(pause: boolean) {
    setBusy(true)
    setError("")
    const before = persistenceFingerprint(profiles)
    try {
      const next = await putAwayMode({
        enabled: !!away?.enabled,
        pause_proactivity: pause,
        message: awayMessage,
      })
      const afterProfiles = await refreshAll(selectedId)
      if (before && persistenceFingerprint(afterProfiles) !== before) {
        setPersistenceNote("Unexpected change to how long Jarvis stays with a job.")
      } else {
        setPersistenceNote("How long Jarvis stays with a job is still the same.")
      }
      setAway(next)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not update Away Mode.")
    } finally {
      setBusy(false)
    }
  }

  async function onApprove(action: ProactiveAction) {
    setBusy(true)
    setError("")
    try {
      await approveProactiveAction(action.id)
      await refreshAll(selectedId)
      setMsg("Suggestion approved.")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not approve that suggestion.")
    } finally {
      setBusy(false)
    }
  }

  const pendingSuggestions = actions.filter(actionNeedsApproval)

  return (
    <div className="card autonomy-section" style={{ maxWidth: 760, marginTop: 16 }}>
      <h2>Stay with a job & Away Mode</h2>
      <p className="lede" style={{ margin: "0 0 14px" }}>
        How long Jarvis stays with a job is separate from whether it may start work on its own.
        Away Mode can pause new work without wiping the job-stay setting.
      </p>

      {msg && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--ok)", padding: "12px 16px" }}>
          {msg}
        </div>
      )}
      {error && (
        <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--bad)", padding: "12px 16px" }}>
          {error}
        </div>
      )}

      <div className={`away-banner${away?.enabled ? " on" : ""}`}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div className="row" style={{ gap: 8, marginBottom: 4 }}>
              <h3 style={{ margin: 0 }}>Away Mode</h3>
              <span className={`badge ${away?.enabled ? "running" : "ok"}`}>
                {away?.enabled ? "You're away" : "You're here"}
              </span>
            </div>
            <p>
              {away?.enabled
                ? awayPauses
                  ? "You are marked away. Jarvis keeps watching jobs the way you saved, but will not start new work on its own."
                  : "You are marked away, but start-on-its-own is still allowed because pause is off."
                : "Turn this on when you step away. Job-stay settings stay as you left them."}
            </p>
          </div>
          <button
            className={away?.enabled ? "btn" : "btn secondary"}
            type="button"
            disabled={busy}
            onClick={() => onToggleAway(!away?.enabled)}
          >
            {away?.enabled ? "I'm back" : "Turn on Away Mode"}
          </button>
        </div>
        <label className="row" style={{ marginTop: 10 }}>
          <input
            type="checkbox"
            checked={away?.pause_proactivity !== false}
            disabled={busy}
            onChange={(event) => onPauseChange(event.target.checked)}
          />
          Pause work Jarvis would start on its own
        </label>
        <label style={{ marginTop: 10 }}>
          Optional note
          <div className="row" style={{ marginTop: 6, gap: 8 }}>
            <input
              type="text"
              value={awayMessage}
              placeholder="e.g. Dinner — back later"
              onChange={(event) => setAwayMessage(event.target.value)}
            />
            <button className="btn secondary" type="button" disabled={busy} onClick={onSaveAwayDetails}>
              Save note
            </button>
          </div>
        </label>
        {persistenceNote && <p className="autonomy-preserve">{persistenceNote}</p>}
      </div>

      <div className="effective-panel">
        <h3>What is in effect</h3>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          {selected
            ? effectiveSentence(selectedEffective, selected.persistence)
            : "Create a setup below to choose how long Jarvis stays with a job, and whether it may start work on its own."}
        </p>
        {selected && (
          <div className="effective-compare">
            <div>
              <b>Saved</b>
              <span>Stay with a job: {persistenceLabel(selected.persistence)}</span>
              <span>Start on its own: {proactivityLabel(selected.proactivity)}</span>
            </div>
            <div>
              <b>Right now</b>
              <span>Stay with a job: {persistenceLabel(selectedEffective?.persistence || selected.persistence)}</span>
              <span>
                Start on its own:{" "}
                {awayPauses
                  ? `${proactivityLabel(selectedEffective?.effective_proactivity || "DISABLED")} (Away Mode)`
                  : proactivityLabel(selectedEffective?.effective_proactivity || selected.proactivity)}
              </span>
            </div>
          </div>
        )}
        {matrix.length > 0 && (
          <table className="autonomy-matrix">
            <thead>
              <tr>
                <th>If you chose</th>
                <th>Right now</th>
              </tr>
            </thead>
            <tbody>
              {matrix.map((row) => (
                <tr key={row.configured}>
                  <td>{proactivityLabel(row.configured)}</td>
                  <td>
                    {row.configured === row.effective
                      ? proactivityLabel(row.effective)
                      : `${proactivityLabel(row.effective)}${row.away_mode_active ? " — paused by Away Mode" : ""}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="row" style={{ margin: "16px 0 12px" }}>
        <button className="btn" type="button" disabled={busy} onClick={startCreate}>
          New setup
        </button>
      </div>

      <div className="template-grid">
        {profiles.map((profile) => {
          const active = profile.id === selectedId
          const row = matrixByConfigured.get(profile.proactivity)
          const effectiveStart = row?.effective || profile.proactivity
          const paused = !!(row?.away_mode_active && profile.proactivity !== "DISABLED")
          return (
            <article
              key={profile.id}
              className={`template-card runtime-card${active ? " selected" : ""}`}
              onClick={() => selectProfile(profile)}
            >
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>{profile.name}</h3>
                {active && <span className="badge ok">Selected</span>}
              </div>
              <p>
                Stay with a job: <strong>{persistenceLabel(profile.persistence)}</strong>
              </p>
              <p style={{ marginTop: 0 }}>
                Start on its own: <strong>{proactivityLabel(profile.proactivity)}</strong>
                {paused ? (
                  <>
                    {" "}
                    → right now <strong>{proactivityLabel(effectiveStart)}</strong>
                  </>
                ) : null}
              </p>
              <div className="row" style={{ marginTop: 12 }} onClick={(event) => event.stopPropagation()}>
                <button className="btn secondary" type="button" disabled={busy} onClick={() => startEdit(profile)}>
                  Edit
                </button>
              </div>
            </article>
          )
        })}
      </div>
      {!profiles.length && (
        <p className="lede">No setups yet. Add one to choose the two settings independently.</p>
      )}

      {formOpen && (
        <form className="runtime-form autonomy-form" onSubmit={onSubmit} style={{ marginTop: 18 }}>
          <h3 className="span-2" style={{ margin: 0 }}>
            {creating ? "New setup" : `Edit ${form.name}`}
          </h3>
          <label className="span-2">Name
            <input
              value={form.name}
              placeholder="Everyday"
              onChange={(event) => patchForm({ name: event.target.value })}
            />
          </label>

          <fieldset className="axis-fieldset span-2">
            <legend>Stay with a job</legend>
            <p>How long Jarvis keeps going. This is not permission to invent new work.</p>
            <div className="axis-options" role="radiogroup" aria-label="Stay with a job">
              {persistenceModes.map((mode) => {
                const selectedMode = form.persistence === mode
                const copy = isPersistence(mode) ? PERSISTENCE_COPY[mode] : { title: mode, body: mode }
                return (
                  <button
                    key={mode}
                    type="button"
                    role="radio"
                    aria-checked={selectedMode}
                    className={`axis-option${selectedMode ? " selected" : ""}`}
                    onClick={() => patchForm({ persistence: isPersistence(mode) ? mode : "ONE_SHOT" })}
                  >
                    <strong>{copy.title}</strong>
                    <span>{copy.body}</span>
                    <em>{mode}</em>
                  </button>
                )
              })}
            </div>
          </fieldset>

          <fieldset className="axis-fieldset span-2">
            <legend>Start work on its own</legend>
            <p>Whether Jarvis may invent or run new work. Separate from how long a job stays open.</p>
            <div className="axis-options" role="radiogroup" aria-label="Start work on its own">
              {proactivityModes.map((mode) => {
                const selectedMode = form.proactivity === mode
                const copy = isProactivity(mode) ? PROACTIVITY_COPY[mode] : { title: mode, body: mode }
                return (
                  <button
                    key={mode}
                    type="button"
                    role="radio"
                    aria-checked={selectedMode}
                    className={`axis-option${selectedMode ? " selected" : ""}`}
                    onClick={() => patchForm({ proactivity: isProactivity(mode) ? mode : "DISABLED" })}
                  >
                    <strong>{copy.title}</strong>
                    <span>{copy.body}</span>
                    <em>{mode}</em>
                  </button>
                )
              })}
            </div>
          </fieldset>

          <label className="span-2">Optional agent id
            <input
              value={form.agent_id}
              placeholder="Leave blank unless you have a specific agent"
              onChange={(event) => patchForm({ agent_id: event.target.value })}
            />
          </label>
          <div className="row span-2">
            <button className="btn" type="submit" disabled={busy}>
              {creating ? "Save setup" : "Save changes"}
            </button>
            <button className="btn secondary" type="button" disabled={busy} onClick={cancelForm}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="autonomy-suggestions">
        <h3>Suggestions waiting for you</h3>
        <p className="lede" style={{ margin: "0 0 12px" }}>
          When a setup is on Suggest, ideas show up here. Approving is what lets them become real work.
        </p>
        {pendingSuggestions.length === 0 && (
          <p className="lede" style={{ margin: 0 }}>Nothing waiting right now.</p>
        )}
        {pendingSuggestions.map((action) => (
          <div key={action.id} className="suggestion-row">
            <div>
              <strong>{action.trigger || "Suggestion"}</strong>
              <p>{action.rationale || "Jarvis proposed this and is waiting."}</p>
              <span className="badge waiting">{actionStatusLabel(action.status)}</span>
            </div>
            <button className="btn" type="button" disabled={busy} onClick={() => onApprove(action)}>
              Approve
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
