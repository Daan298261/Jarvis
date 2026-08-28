import { useEffect, useMemo, useState, type FormEvent } from "react"
import {
  createRuntimeProfile,
  deleteRuntimeProfile,
  getSelectedRuntimeMode,
  getSelectedRuntimePolicy,
  getSelectedRuntimeProfileId,
  listRuntimeProfiles,
  previewRuntimeRoute,
  resetRuntimeProfiles,
  RUNTIME_PRIVACY_CLASSES,
  RUNTIME_PROFILE_PROVIDERS,
  setSelectedRuntimeMode,
  setSelectedRuntimePolicy,
  setSelectedRuntimeProfileId,
  updateRuntimeProfile,
  type RuntimeProfile,
  type RuntimeProfileIn,
  type RuntimeProfileUpdate,
  type RuntimeRouteDecision,
  type RuntimeSelectMode,
} from "../api"

type FormState = {
  name: string
  label: string
  model: string
  provider: string
  endpoint: string
  context_limit: string
  quantization: string
  privacy_class: string
  cost_ceiling_usd: string
  capability_tags: string
  model_profile: string
  specialization_tags: string
  is_local: boolean
  description: string
}

const MODEL_PRESETS = ["fast", "balanced", "quality", "expert"] as const

const PRIVACY_LABELS: Record<string, string> = {
  "local-only": "This PC only",
  "trusted-remote": "Trusted machine",
  "public-remote": "Public cloud",
}

const POLICY_LABELS: Record<string, string> = {
  "local-only": "Stay on this PC",
  "local-first": "Prefer this PC",
  "best-result": "Best result",
  "cost-optimized": "Keep cost down",
}

function emptyForm(): FormState {
  return {
    name: "",
    label: "",
    model: "",
    provider: "openai-compat",
    endpoint: "http://127.0.0.1:8088/v1",
    context_limit: "16384",
    quantization: "",
    privacy_class: "trusted-remote",
    cost_ceiling_usd: "",
    capability_tags: "llm_inference, text",
    model_profile: "",
    specialization_tags: "",
    is_local: false,
    description: "",
  }
}

function formFromProfile(profile: RuntimeProfile): FormState {
  return {
    name: profile.name,
    label: profile.label || profile.name,
    model: profile.model,
    provider: profile.provider || "openai-compat",
    endpoint: profile.endpoint,
    context_limit: String(profile.context_limit ?? 16384),
    quantization: profile.quantization || "",
    privacy_class: profile.privacy_class || "trusted-remote",
    cost_ceiling_usd: profile.cost_ceiling_usd == null ? "" : String(profile.cost_ceiling_usd),
    capability_tags: (profile.capability_tags || []).join(", "),
    model_profile: profile.model_profile || "",
    specialization_tags: (profile.specialization_tags || []).join(", "),
    is_local: !!profile.is_local,
    description: profile.description || "",
  }
}

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "")
}

function parseTags(value: string): string[] {
  return value.split(/[,;\n]/).map((part) => part.trim()).filter(Boolean)
}

function parseCost(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

function privacyLabel(value: string): string {
  return PRIVACY_LABELS[value] || value
}

function policyLabel(value: string): string {
  return POLICY_LABELS[value] || value
}

function profileMatchesSelection(profile: RuntimeProfile, selectedId: string): boolean {
  if (!selectedId) return false
  return profile.id === selectedId || profile.name === selectedId
}

function toCreateBody(form: FormState): RuntimeProfileIn {
  const name = slugify(form.name || form.label)
  return {
    name,
    label: form.label.trim() || name,
    model: form.model.trim(),
    provider: form.provider,
    endpoint: form.endpoint.trim(),
    context_limit: Number(form.context_limit) || 16384,
    quantization: form.quantization.trim(),
    privacy_class: form.privacy_class,
    cost_ceiling_usd: parseCost(form.cost_ceiling_usd),
    capability_tags: parseTags(form.capability_tags),
    model_profile: form.model_profile.trim() || null,
    specialization_tags: parseTags(form.specialization_tags),
    is_local: form.is_local,
    description: form.description.trim(),
  }
}

function toUpdateBody(form: FormState): RuntimeProfileUpdate {
  return {
    label: form.label.trim() || form.name,
    model: form.model.trim(),
    provider: form.provider,
    endpoint: form.endpoint.trim(),
    context_limit: Number(form.context_limit) || 16384,
    quantization: form.quantization.trim(),
    privacy_class: form.privacy_class,
    cost_ceiling_usd: parseCost(form.cost_ceiling_usd),
    capability_tags: parseTags(form.capability_tags),
    model_profile: form.model_profile.trim() || null,
    specialization_tags: parseTags(form.specialization_tags),
    is_local: form.is_local,
    description: form.description.trim(),
  }
}

export function RuntimeProfilesSection() {
  const [profiles, setProfiles] = useState<RuntimeProfile[]>([])
  const [policies, setPolicies] = useState<string[]>(["local-first", "local-only", "best-result", "cost-optimized"])
  const [selectedId, setSelectedId] = useState(getSelectedRuntimeProfileId)
  const [selectMode, setSelectMode] = useState<RuntimeSelectMode>(getSelectedRuntimeMode)
  const [policy, setPolicy] = useState(getSelectedRuntimePolicy)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [error, setError] = useState("")
  const [preview, setPreview] = useState<RuntimeRouteDecision | null>(null)
  const [catalogTick, setCatalogTick] = useState(0)

  const selected = useMemo(
    () => profiles.find((profile) => profileMatchesSelection(profile, selectedId)) || null,
    [profiles, selectedId],
  )

  async function refresh() {
    const data = await listRuntimeProfiles()
    setProfiles(data.profiles || [])
    if (data.policies?.length) setPolicies(data.policies)
    setCatalogTick((tick) => tick + 1)
    return data.profiles || []
  }

  async function refreshPreview(nextId = selectedId, nextMode = selectMode, nextPolicy = policy) {
    const body =
      nextMode === "force" && nextId
        ? { force_profile: nextId, policy: nextPolicy }
        : { preferred_profiles: nextId ? [nextId] : [], policy: nextPolicy }
    try {
      setPreview(await previewRuntimeRoute(body))
    } catch {
      setPreview(null)
    }
  }

  useEffect(() => {
    refresh()
      .then((items) => {
        const stored = getSelectedRuntimeProfileId()
        if (stored && !items.some((item) => profileMatchesSelection(item, stored))) {
          setSelectedRuntimeProfileId("")
          setSelectedId("")
        }
      })
      .catch(() => setError("Could not load runtimes. Start Jarvis and try again."))
  }, [])

  useEffect(() => {
    void refreshPreview()
  }, [selectedId, selectMode, policy, catalogTick])

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

  function startEdit(profile: RuntimeProfile) {
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

  function persistSelection(id: string, mode: RuntimeSelectMode, nextPolicy = policy) {
    setSelectedRuntimeProfileId(id)
    setSelectedRuntimeMode(mode)
    setSelectedRuntimePolicy(nextPolicy)
    setSelectedId(id)
    setSelectMode(mode)
    setPolicy(nextPolicy)
  }

  function selectProfile(profile: RuntimeProfile, mode: RuntimeSelectMode = selectMode) {
    persistSelection(profile.id, mode)
    const label = profile.label || profile.name
    setMsg(mode === "force" ? `Locked on ${label}.` : `${label} is preferred.`)
    setError("")
  }

  function clearSelection() {
    persistSelection("", "prefer")
    setMsg("No runtime preferred.")
    setPreview(null)
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const createBody = toCreateBody(form)
    if (creating) {
      if (!createBody.name) {
        setError("Give this runtime a name.")
        return
      }
      if (!createBody.model || !createBody.endpoint) {
        setError("Model and address are required.")
        return
      }
    } else if (editingId) {
      if (!form.model.trim() || !form.endpoint.trim()) {
        setError("Model and address are required.")
        return
      }
    }
    setBusy(true)
    setError("")
    try {
      if (creating) {
        const created = await createRuntimeProfile(createBody)
        await refresh()
        persistSelection(created.id, selectMode)
        setMsg(`Created ${created.label || created.name}.`)
        cancelForm()
      } else if (editingId) {
        const updated = await updateRuntimeProfile(editingId, toUpdateBody(form))
        await refresh()
        setMsg(`Updated ${updated.label || updated.name}.`)
        cancelForm()
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save this runtime.")
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(profile: RuntimeProfile) {
    const label = profile.label || profile.name
    if (!window.confirm(`Remove runtime “${label}”?`)) return
    setBusy(true)
    setError("")
    try {
      await deleteRuntimeProfile(profile.id)
      if (profileMatchesSelection(profile, selectedId)) persistSelection("", selectMode)
      if (editingId === profile.id) cancelForm()
      await refresh()
      setMsg(`Removed ${label}.`)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not remove this runtime.")
    } finally {
      setBusy(false)
    }
  }

  async function onReset() {
    if (!window.confirm("Restore the starter runtimes? Custom runtimes will be replaced.")) return
    setBusy(true)
    setError("")
    try {
      await resetRuntimeProfiles()
      const items = await refresh()
      const stillThere = items.some((item) => profileMatchesSelection(item, selectedId))
      if (!stillThere) persistSelection("", selectMode)
      cancelForm()
      setMsg("Starter runtimes restored.")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not restore starter runtimes.")
    } finally {
      setBusy(false)
    }
  }

  const formOpen = creating || !!editingId
  const pick = preview?.runtime_profile

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>Runtimes</h2>
      <p className="lede">
        Named setups Jarvis can choose from: the model, where it lives, how much it can remember,
        how private it is, and a spend ceiling. Prefer one, or lock it so policy will not override.
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

      <div className="row" style={{ marginBottom: 14 }}>
        <button className="btn" type="button" disabled={busy} onClick={startCreate}>
          New runtime
        </button>
        <button className="btn secondary" type="button" disabled={busy} onClick={onReset}>
          Restore starters
        </button>
        {selected && (
          <button className="btn secondary" type="button" disabled={busy} onClick={clearSelection}>
            Clear pick
          </button>
        )}
      </div>

      <div className="grid two" style={{ marginBottom: 16 }}>
        <label>How Jarvis should choose
          <select
            value={policy}
            onChange={(event) => {
              const next = event.target.value
              persistSelection(selectedId, selectMode, next)
            }}
          >
            {policies.map((item) => (
              <option key={item} value={item}>
                {policyLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <label>When a runtime is picked
          <select
            value={selectMode}
            onChange={(event) => {
              const next = event.target.value === "force" ? "force" : "prefer"
              persistSelection(selectedId, next)
            }}
          >
            <option value="prefer">Prefer it — policy may still switch</option>
            <option value="force">Always use it</option>
          </select>
        </label>
      </div>

      <p className="lede" style={{ marginTop: 0 }}>
        {selected
          ? selectMode === "force"
            ? `Locked on ${selected.label}.`
            : `${selected.label} is preferred.`
          : "No runtime preferred yet. Pick one below."}
        {preview && pick ? ` Jarvis would use ${pick.label || pick.name}${preview.reason ? ` — ${preview.reason}` : "."}` : ""}
        {preview && !preview.accepted ? ` ${preview.reason || "No runtime fits this policy."}` : ""}
      </p>

      <div className="template-grid">
        {profiles.map((profile) => {
          const active = profileMatchesSelection(profile, selectedId)
          const tags = [...(profile.capability_tags || []), ...(profile.specialization_tags || [])]
          return (
            <article
              key={profile.id}
              className={`template-card runtime-card${active ? " selected" : ""}`}
              onClick={() => selectProfile(profile)}
            >
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>{profile.label || profile.name}</h3>
                {active && (
                  <span className={`badge ${selectMode === "force" ? "running" : "ok"}`}>
                    {selectMode === "force" ? "Locked" : "Preferred"}
                  </span>
                )}
              </div>
              <p>
                {profile.model}
                {profile.quantization ? ` · ${profile.quantization}` : ""}
                {" · "}
                {profile.context_limit.toLocaleString()} context
              </p>
              <p style={{ marginTop: 0 }}>
                {privacyLabel(profile.privacy_class)}
                {" · "}
                {profile.is_local ? "This PC" : profile.endpoint}
                {profile.cost_ceiling_usd != null ? ` · ceiling $${profile.cost_ceiling_usd}` : ""}
              </p>
              {tags.length > 0 && (
                <div className="runtime-tags">
                  {tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              )}
              <div className="row" style={{ marginTop: 12 }} onClick={(event) => event.stopPropagation()}>
                <button className="btn" type="button" disabled={busy} onClick={() => selectProfile(profile)}>
                  {active ? "Selected" : "Use this"}
                </button>
                <button className="btn secondary" type="button" disabled={busy} onClick={() => startEdit(profile)}>
                  Edit
                </button>
                <button className="btn secondary" type="button" disabled={busy} onClick={() => onDelete(profile)}>
                  Remove
                </button>
              </div>
            </article>
          )
        })}
      </div>

      {!profiles.length && <p className="lede">No runtimes yet. Create one or restore the starters.</p>}

      {formOpen && (
        <form className="runtime-form" onSubmit={onSubmit} style={{ marginTop: 18 }}>
          <h3 className="span-2" style={{ margin: 0 }}>
            {creating ? "New runtime" : `Edit ${form.label || form.name}`}
          </h3>
          {creating && (
            <label>Short name
              <input
                value={form.name}
                placeholder="cloud-fast"
                onChange={(event) => patchForm({ name: event.target.value })}
              />
            </label>
          )}
          <label className={creating ? undefined : "span-2"}>Display name
            <input
              value={form.label}
              placeholder="Cloud Fast"
              onChange={(event) => patchForm({ label: event.target.value })}
            />
          </label>
          <label>Model
            <input
              value={form.model}
              placeholder="Qwen3.5-9B"
              onChange={(event) => patchForm({ model: event.target.value })}
            />
          </label>
          <label>Provider
            <select value={form.provider} onChange={(event) => patchForm({ provider: event.target.value })}>
              {RUNTIME_PROFILE_PROVIDERS.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
              {form.provider && !RUNTIME_PROFILE_PROVIDERS.includes(form.provider as typeof RUNTIME_PROFILE_PROVIDERS[number]) && (
                <option value={form.provider}>{form.provider}</option>
              )}
            </select>
          </label>
          <label className="span-2">Address
            <input
              value={form.endpoint}
              placeholder="http://127.0.0.1:8088/v1"
              onChange={(event) => patchForm({ endpoint: event.target.value })}
            />
          </label>
          <label>Context limit
            <input
              type="number"
              value={form.context_limit}
              onChange={(event) => patchForm({ context_limit: event.target.value })}
            />
          </label>
          <label>Quantization
            <input
              value={form.quantization}
              placeholder="Q8_0"
              onChange={(event) => patchForm({ quantization: event.target.value })}
            />
          </label>
          <label>Privacy
            <select
              value={form.privacy_class}
              onChange={(event) => patchForm({ privacy_class: event.target.value })}
            >
              {RUNTIME_PRIVACY_CLASSES.map((item) => (
                <option key={item} value={item}>{privacyLabel(item)}</option>
              ))}
            </select>
          </label>
          <label>Cost ceiling (USD)
            <input
              type="number"
              step="0.0001"
              min="0"
              value={form.cost_ceiling_usd}
              placeholder="Leave blank for none"
              onChange={(event) => patchForm({ cost_ceiling_usd: event.target.value })}
            />
          </label>
          <label>Load preset (optional)
            <select
              value={form.model_profile}
              onChange={(event) => patchForm({ model_profile: event.target.value })}
            >
              <option value="">None</option>
              {MODEL_PRESETS.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="row" style={{ alignItems: "center", marginTop: 22 }}>
            <input
              type="checkbox"
              checked={form.is_local}
              onChange={(event) => patchForm({ is_local: event.target.checked })}
            />
            This runtime lives on this PC
          </label>
          <label className="span-2">What it can do (tags)
            <input
              value={form.capability_tags}
              placeholder="llm_inference, text, vision"
              onChange={(event) => patchForm({ capability_tags: event.target.value })}
            />
          </label>
          <label className="span-2">Specialties
            <input
              value={form.specialization_tags}
              placeholder="reasoning, low-latency"
              onChange={(event) => patchForm({ specialization_tags: event.target.value })}
            />
          </label>
          <label className="span-2">Notes
            <textarea
              className="field"
              rows={3}
              value={form.description}
              onChange={(event) => patchForm({ description: event.target.value })}
            />
          </label>
          <div className="row span-2">
            <button className="btn" type="submit" disabled={busy}>
              {creating ? "Create runtime" : "Save changes"}
            </button>
            <button className="btn secondary" type="button" disabled={busy} onClick={cancelForm}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
