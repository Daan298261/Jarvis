import { useEffect, useMemo, useState, type ReactNode } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  AGENT_AUTONOMY_LEVELS,
  createAgentPolicyProfile,
  getAgentPolicyProfile,
  listAgentPolicyAudit,
  normalizeInterviewAnswers,
  updateAgentPolicyProfile,
  type AgentPolicyAuditEvent,
  type AgentPolicyDocument,
} from "../api"
import {
  APPROVAL_OPTIONS,
  AUTONOMY_COPY,
  answersFromForm,
  approvalLabel,
  autonomyTitle,
  CAPABILITY_OPTIONS,
  CHANNEL_OPTIONS,
  channelLabel,
  emptyInterviewForm,
  formFromAnswers,
  INTERVIEW_STEPS,
  overlayAutonomy,
  TONE_OPTIONS,
  type InterviewForm,
} from "./agentInterviewCopy"

type Phase = "interview" | "summary" | "policy"

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
}

function prettyPolicy(policy: AgentPolicyDocument): string {
  return JSON.stringify(policy, null, 2)
}

function formatWhen(value: string | undefined): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function Chip({
  selected,
  onClick,
  children,
}: {
  selected: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button type="button" className={`chip${selected ? " on" : ""}`} aria-pressed={selected} onClick={onClick}>
      {children}
    </button>
  )
}

function TagAdder({
  values,
  onChange,
  placeholder,
}: {
  values: string[]
  onChange: (next: string[]) => void
  placeholder: string
}) {
  const [draft, setDraft] = useState("")
  function add() {
    const value = draft.trim()
    if (!value || values.includes(value)) {
      setDraft("")
      return
    }
    onChange([...values, value])
    setDraft("")
  }
  return (
    <div>
      <div className="chip-row">
        {values.map((value) => (
          <Chip key={value} selected onClick={() => onChange(values.filter((item) => item !== value))}>
            {value} ×
          </Chip>
        ))}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input
          type="text"
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              add()
            }
          }}
        />
        <button className="btn secondary" type="button" onClick={add}>
          Add
        </button>
      </div>
    </div>
  )
}

export function AgentInterviewPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const editing = !!id
  const [form, setForm] = useState<InterviewForm>(emptyInterviewForm)
  const [phase, setPhase] = useState<Phase>("interview")
  const [step, setStep] = useState(0)
  const [policy, setPolicy] = useState<AgentPolicyDocument>({})
  const [policyText, setPolicyText] = useState("{}")
  const [policyError, setPolicyError] = useState("")
  const [prompt, setPrompt] = useState("")
  const [events, setEvents] = useState<AgentPolicyAuditEvent[]>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(editing)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setLoading(true)
    Promise.all([getAgentPolicyProfile(id), listAgentPolicyAudit({ profileId: id, limit: 8 }).catch(() => ({ events: [] }))])
      .then(([profile, audit]) => {
        if (cancelled) return
        setForm(formFromAnswers(profile.name, profile.interview_answers, profile.policy))
        setPolicy(profile.policy || {})
        setPolicyText(prettyPolicy(profile.policy || {}))
        setPrompt(profile.generated_prompt || "")
        setEvents(audit.events || [])
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "Could not load this agent.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  function patch(next: Partial<InterviewForm>) {
    setForm((current) => ({ ...current, ...next }))
  }

  const progress = useMemo(() => {
    if (phase === "summary") return 92
    if (phase === "policy") return 100
    return Math.round(((step + 1) / INTERVIEW_STEPS.length) * 86)
  }, [phase, step])

  async function goToPolicy(fromSummary = true) {
    setBusy(true)
    setError("")
    try {
      const answers = answersFromForm(form)
      const generated = await normalizeInterviewAnswers(answers)
      const merged = overlayAutonomy(generated.policy, form)
      setPolicy(merged)
      setPolicyText(prettyPolicy(merged))
      setPolicyError("")
      if (fromSummary) setPhase("policy")
      setMsg("Policy built from this interview. You can still edit it before saving.")
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not build policy from these answers.")
    } finally {
      setBusy(false)
    }
  }

  function applyPolicyText() {
    try {
      const parsed = JSON.parse(policyText) as AgentPolicyDocument
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setPolicyError("Policy must be a JSON object.")
        return false
      }
      setPolicy(parsed)
      setPolicyError("")
      return true
    } catch {
      setPolicyError("That JSON is not valid yet.")
      return false
    }
  }

  async function onSave() {
    if (!form.name.trim()) {
      setError("Give this agent a name before saving.")
      setPhase("interview")
      setStep(0)
      return
    }
    if (!applyPolicyText()) return
    setBusy(true)
    setError("")
    try {
      const answers = answersFromForm(form)
      const body = { name: form.name.trim(), interview_answers: answers, policy }
      const saved = id
        ? await updateAgentPolicyProfile(id, body)
        : await createAgentPolicyProfile(body)
      setPrompt(saved.generated_prompt || "")
      setMsg(`Saved “${saved.name}”. The policy stays visible and you can edit it again anytime.`)
      navigate(`/agents/${saved.id}`, { replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save this agent.")
    } finally {
      setBusy(false)
    }
  }

  function nextInterview() {
    if (step >= INTERVIEW_STEPS.length - 1) {
      setPhase("summary")
      return
    }
    setStep((current) => current + 1)
  }

  function back() {
    if (phase === "policy") {
      setPhase("summary")
      return
    }
    if (phase === "summary") {
      setPhase("interview")
      setStep(INTERVIEW_STEPS.length - 1)
      return
    }
    if (step === 0) {
      navigate("/agents")
      return
    }
    setStep((current) => current - 1)
  }

  if (loading) return <div>Loading this agent…</div>

  const current = INTERVIEW_STEPS[step]

  return (
    <div className="interview-page">
      <p className="interview-kicker">
        <Link to="/agents">Agents</Link>
        <span> / {editing ? "Edit profile" : "New profile"}</span>
      </p>
      <h1>{editing ? `Interview: ${form.name || "untitled"}` : "New agent interview"}</h1>
      <p className="lede">
        Answer in ordinary language. Jarvis will turn this into a structured policy you can read and
        change. This is not a server console.
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

      <div className="interview-progress" aria-hidden="true">
        <div className="interview-progress-bar" style={{ width: `${progress}%` }} />
      </div>
      <div className="interview-dots" role="tablist" aria-label="Interview stages">
        {INTERVIEW_STEPS.map((item, index) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            className={`interview-dot${phase === "interview" && index === step ? " on" : ""}${index < step || phase !== "interview" ? " done" : ""}`}
            aria-selected={phase === "interview" && index === step}
            title={item.title}
            onClick={() => {
              setPhase("interview")
              setStep(index)
            }}
          >
            {index + 1}
          </button>
        ))}
        <button
          type="button"
          className={`interview-dot${phase === "summary" ? " on" : ""}`}
          onClick={() => setPhase("summary")}
        >
          Review
        </button>
        <button
          type="button"
          className={`interview-dot${phase === "policy" ? " on" : ""}`}
          onClick={() => {
            if (phase === "policy") return
            if (policy.autonomy || policy.channels) setPhase("policy")
            else void goToPolicy()
          }}
        >
          Policy
        </button>
      </div>

      {phase === "interview" && (
        <div className="card interview-card">
          <p className="interview-step-label">
            Question {step + 1} of {INTERVIEW_STEPS.length}
          </p>
          <h2>{current.title}</h2>
          <p className="lede" style={{ marginTop: 0 }}>{current.hint}</p>
          {step === 0 && (
            <div className="grid">
              <label>
                Name
                <input
                  type="text"
                  value={form.name}
                  placeholder="Research analyst"
                  onChange={(event) => patch({ name: event.target.value })}
                />
              </label>
              <label>
                What is this agent here to do?
                <textarea
                  className="field"
                  rows={5}
                  value={form.mission}
                  placeholder="Research competitors each week and write a short brief I can act on."
                  onChange={(event) => patch({ mission: event.target.value })}
                />
              </label>
            </div>
          )}
          {step === 1 && (
            <label>
              What does good work look like?
              <textarea
                className="field"
                rows={6}
                value={form.success_criteria}
                placeholder="A one-page brief with sources, risks, and a recommended next step."
                onChange={(event) => patch({ success_criteria: event.target.value })}
              />
            </label>
          )}
          {step === 2 && (
            <div className="axis-options" role="radiogroup" aria-label="Tone">
              {TONE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={form.tone === option.value}
                  className={`axis-option${form.tone === option.value ? " selected" : ""}`}
                  onClick={() => patch({ tone: option.value })}
                >
                  <strong>{option.title}</strong>
                  <span>{option.body}</span>
                </button>
              ))}
            </div>
          )}
          {step === 3 && (
            <div>
              <p className="lede" style={{ marginTop: 0 }}>Choose the places this specialist may work.</p>
              <div className="chip-row">
                {CHANNEL_OPTIONS.map((option) => (
                  <Chip
                    key={option.value}
                    selected={form.allowed_channels.includes(option.value)}
                    onClick={() => patch({ allowed_channels: toggleValue(form.allowed_channels, option.value) })}
                  >
                    {option.label}
                  </Chip>
                ))}
              </div>
              <p className="lede" style={{ margin: "14px 0 8px" }}>Anything else? Add a channel name.</p>
              <TagAdder
                values={form.allowed_channels.filter((value) => !CHANNEL_OPTIONS.some((option) => option.value === value))}
                onChange={(custom) => {
                  const known = form.allowed_channels.filter((value) => CHANNEL_OPTIONS.some((option) => option.value === value))
                  patch({ allowed_channels: [...known, ...custom] })
                }}
                placeholder="e.g. slack"
              />
            </div>
          )}
          {step === 4 && (
            <div>
              <p className="lede" style={{ marginTop: 0 }}>These wait for you, even if the agent is otherwise trusted.</p>
              <div className="chip-row">
                {APPROVAL_OPTIONS.map((option) => (
                  <Chip
                    key={option.value}
                    selected={form.approval_required_actions.includes(option.value)}
                    onClick={() => patch({
                      approval_required_actions: toggleValue(form.approval_required_actions, option.value),
                    })}
                  >
                    {option.label}
                  </Chip>
                ))}
              </div>
              <p className="lede" style={{ margin: "14px 0 8px" }}>Add another action that must wait.</p>
              <TagAdder
                values={form.approval_required_actions.filter((value) => !APPROVAL_OPTIONS.some((option) => option.value === value))}
                onChange={(custom) => {
                  const known = form.approval_required_actions.filter((value) => APPROVAL_OPTIONS.some((option) => option.value === value))
                  patch({ approval_required_actions: [...known, ...custom] })
                }}
                placeholder="e.g. deploy"
              />
            </div>
          )}
          {step === 5 && (
            <div className="runtime-form">
              <label>
                Daily spend (USD)
                <input type="number" value={form.budgetDaily} onChange={(event) => patch({ budgetDaily: event.target.value })} />
              </label>
              <label>
                Monthly spend (USD)
                <input type="number" value={form.budgetMonthly} onChange={(event) => patch({ budgetMonthly: event.target.value })} />
              </label>
              <label>
                Tool calls per job
                <input type="number" value={form.budgetToolCalls} onChange={(event) => patch({ budgetToolCalls: event.target.value })} />
              </label>
              <label className="span-2">
                Other limits
                <textarea
                  className="field"
                  rows={3}
                  value={form.budgetNotes}
                  placeholder="Keep paid APIs off unless I ask."
                  onChange={(event) => patch({ budgetNotes: event.target.value })}
                />
              </label>
            </div>
          )}
          {step === 6 && (
            <div className="grid">
              <label className="row">
                <input
                  type="checkbox"
                  checked={form.privacyLeaveNetwork}
                  onChange={(event) => patch({ privacyLeaveNetwork: event.target.checked })}
                />
                Data from this agent may leave this PC
              </label>
              <label className="row">
                <input
                  type="checkbox"
                  checked={form.privacyRetainMemory}
                  onChange={(event) => patch({ privacyRetainMemory: event.target.checked })}
                />
                Remember useful notes for later jobs
              </label>
              <label>
                Private notes
                <textarea
                  className="field"
                  rows={4}
                  value={form.privacyNotes}
                  placeholder="Customer names stay on this PC. Do not paste secrets into the web."
                  onChange={(event) => patch({ privacyNotes: event.target.value })}
                />
              </label>
            </div>
          )}
          {step === 7 && (
            <div className="grid">
              <label className="row">
                <input
                  type="checkbox"
                  checked={form.schedulingProactive}
                  onChange={(event) => patch({ schedulingProactive: event.target.checked })}
                />
                This agent may look for work on a schedule
              </label>
              <label>
                Check-in interval (minutes)
                <input type="number" value={form.schedulingInterval} onChange={(event) => patch({ schedulingInterval: event.target.value })} />
              </label>
              <label>
                Quiet hours
                <input
                  type="text"
                  value={form.schedulingQuietHours}
                  placeholder="22:00–07:00"
                  onChange={(event) => patch({ schedulingQuietHours: event.target.value })}
                />
              </label>
              <label>
                When should it nudge you?
                <textarea
                  className="field"
                  rows={3}
                  value={form.schedulingNotifyWhen}
                  placeholder="Only if a brief is ready, or something is blocked."
                  onChange={(event) => patch({ schedulingNotifyWhen: event.target.value })}
                />
              </label>
            </div>
          )}
          {step === 8 && (
            <div className="grid">
              <label>
                Come to me when
                <textarea
                  className="field"
                  rows={3}
                  value={form.escalationNotifyOn}
                  placeholder="It cannot finish, spend would exceed the budget, or a hard prohibition is in play."
                  onChange={(event) => patch({ escalationNotifyOn: event.target.value })}
                />
              </label>
              <label>
                Who to contact
                <input
                  type="text"
                  value={form.escalationContact}
                  placeholder="You, on this PC"
                  onChange={(event) => patch({ escalationContact: event.target.value })}
                />
              </label>
              <label>
                After how many failures
                <input
                  type="number"
                  value={form.escalationAfterFailures}
                  onChange={(event) => patch({ escalationAfterFailures: event.target.value })}
                />
              </label>
            </div>
          )}
          {step === 9 && (
            <div>
              <p className="lede" style={{ marginTop: 0 }}>Write the lines it must not cross. One per item.</p>
              <TagAdder
                values={form.hard_prohibitions}
                onChange={(hard_prohibitions) => patch({ hard_prohibitions })}
                placeholder="e.g. no terminal shell access"
              />
            </div>
          )}
          {step === 10 && (
            <div>
              <p className="lede" style={{ marginTop: 0 }}>A default for most work, then exceptions for specific tools or actions.</p>
              <div className="axis-options" role="radiogroup" aria-label="Default autonomy">
                {AGENT_AUTONOMY_LEVELS.map((level) => (
                  <button
                    key={level}
                    type="button"
                    role="radio"
                    aria-checked={form.default_autonomy === level}
                    className={`axis-option${form.default_autonomy === level ? " selected" : ""}`}
                    onClick={() => {
                      const nextRows = form.capabilityLevels.map((row) =>
                        row.key === "*" ? { ...row, level } : row,
                      )
                      if (!nextRows.some((row) => row.key === "*")) nextRows.unshift({ key: "*", level })
                      patch({ default_autonomy: level, capabilityLevels: nextRows })
                    }}
                  >
                    <strong>{AUTONOMY_COPY[level].title}</strong>
                    <span>{AUTONOMY_COPY[level].body}</span>
                    <em>{level}</em>
                  </button>
                ))}
              </div>
              <h3 style={{ margin: "18px 0 8px", fontSize: 15 }}>By kind of work</h3>
              <div className="autonomy-rows">
                {form.capabilityLevels.map((row, index) => (
                  <div className="autonomy-row" key={`${row.key}-${index}`}>
                    <select
                      value={CAPABILITY_OPTIONS.some((option) => option.key === row.key) ? row.key : "__custom"}
                      aria-label="Capability"
                      onChange={(event) => {
                        const next = [...form.capabilityLevels]
                        next[index] = {
                          ...row,
                          key: event.target.value === "__custom" ? "" : event.target.value,
                        }
                        patch({ capabilityLevels: next })
                      }}
                    >
                      {CAPABILITY_OPTIONS.map((option) => (
                        <option key={option.key} value={option.key}>
                          {option.label}
                        </option>
                      ))}
                      <option value="__custom">Other…</option>
                    </select>
                    {!CAPABILITY_OPTIONS.some((option) => option.key === row.key) && (
                      <input
                        type="text"
                        value={row.key}
                        placeholder="tool.action"
                        onChange={(event) => {
                          const next = [...form.capabilityLevels]
                          next[index] = { ...row, key: event.target.value }
                          patch({ capabilityLevels: next })
                        }}
                      />
                    )}
                    <select
                      value={row.level}
                      aria-label="Autonomy level"
                      onChange={(event) => {
                        const next = [...form.capabilityLevels]
                        next[index] = { ...row, level: event.target.value }
                        patch({ capabilityLevels: next })
                      }}
                    >
                      {AGENT_AUTONOMY_LEVELS.map((level) => (
                        <option key={level} value={level}>
                          {AUTONOMY_COPY[level].title}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => patch({ capabilityLevels: form.capabilityLevels.filter((_, i) => i !== index) })}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
              <button
                className="btn secondary"
                type="button"
                style={{ marginTop: 10 }}
                onClick={() => patch({
                  capabilityLevels: [...form.capabilityLevels, { key: "terminal", level: "L3_EXECUTE_WITH_GATES" }],
                })}
              >
                Add a capability
              </button>
            </div>
          )}
        </div>
      )}

      {phase === "summary" && (
        <div className="card interview-card">
          <h2>Summary</h2>
          <p className="lede" style={{ marginTop: 0 }}>
            Check this before Jarvis writes the policy. You can still go back and change an answer.
          </p>
          <div className="summary-grid">
            <div>
              <b>Name</b>
              <span>{form.name || "Untitled"}</span>
            </div>
            <div>
              <b>Mission</b>
              <span>{form.mission || "—"}</span>
            </div>
            <div>
              <b>Success</b>
              <span>{form.success_criteria || "—"}</span>
            </div>
            <div>
              <b>Tone</b>
              <span>{TONE_OPTIONS.find((option) => option.value === form.tone)?.title || form.tone}</span>
            </div>
            <div>
              <b>Allowed channels</b>
              <span>{form.allowed_channels.length ? form.allowed_channels.map(channelLabel).join(", ") : "None chosen"}</span>
            </div>
            <div>
              <b>Needs your OK</b>
              <span>
                {form.approval_required_actions.length
                  ? form.approval_required_actions.map(approvalLabel).join(", ")
                  : "None chosen"}
              </span>
            </div>
            <div>
              <b>Budgets</b>
              <span>
                {[
                  form.budgetDaily && `$${form.budgetDaily}/day`,
                  form.budgetMonthly && `$${form.budgetMonthly}/month`,
                  form.budgetToolCalls && `${form.budgetToolCalls} tool calls`,
                  form.budgetNotes,
                ].filter(Boolean).join(" · ") || "No extra limits"}
              </span>
            </div>
            <div>
              <b>Privacy</b>
              <span>
                {form.privacyLeaveNetwork ? "May leave this PC" : "Stay on this PC"}
                {form.privacyRetainMemory ? " · remember later" : " · do not keep memory"}
                {form.privacyNotes ? ` · ${form.privacyNotes}` : ""}
              </span>
            </div>
            <div>
              <b>Schedule</b>
              <span>
                {form.schedulingProactive ? "May look for work" : "Wait until asked"}
                {form.schedulingInterval ? ` · every ${form.schedulingInterval} min` : ""}
                {form.schedulingQuietHours ? ` · quiet ${form.schedulingQuietHours}` : ""}
                {form.schedulingNotifyWhen ? ` · ${form.schedulingNotifyWhen}` : ""}
              </span>
            </div>
            <div>
              <b>Escalation</b>
              <span>
                {form.escalationNotifyOn || "When it cannot finish"}
                {form.escalationContact ? ` · ${form.escalationContact}` : ""}
                {form.escalationAfterFailures ? ` · after ${form.escalationAfterFailures} failures` : ""}
              </span>
            </div>
            <div>
              <b>Never do</b>
              <span>{form.hard_prohibitions.length ? form.hard_prohibitions.join("; ") : "None written"}</span>
            </div>
            <div>
              <b>Freedom</b>
              <span>
                Default {autonomyTitle(form.default_autonomy)} ({form.default_autonomy}).{" "}
                {form.capabilityLevels
                  .filter((row) => row.key && row.key !== "*")
                  .map((row) => `${row.key}: ${autonomyTitle(row.level)}`)
                  .join(" · ") || "No extra per-tool rules yet."}
              </span>
            </div>
          </div>
        </div>
      )}

      {phase === "policy" && (
        <div className="card interview-card">
          <h2>Generated policy</h2>
          <p className="lede" style={{ marginTop: 0 }}>
            Built from your answers. Edit the fields or the JSON. Saving stores both the interview
            and this policy — not just a written prompt.
          </p>
          <h3 style={{ fontSize: 15 }}>Freedom by capability</h3>
          <div className="autonomy-rows">
            {Object.entries(policy.autonomy || {}).map(([key, level]) => (
              <div className="autonomy-row" key={key}>
                <input
                  type="text"
                  value={key}
                  aria-label="Capability"
                  onChange={(event) => {
                    const autonomy = { ...(policy.autonomy || {}) }
                    const currentLevel = autonomy[key]
                    delete autonomy[key]
                    autonomy[event.target.value] = currentLevel
                    const next = { ...policy, autonomy }
                    setPolicy(next)
                    setPolicyText(prettyPolicy(next))
                  }}
                />
                <select
                  value={level}
                  aria-label="Level"
                  onChange={(event) => {
                    const next = {
                      ...policy,
                      autonomy: { ...(policy.autonomy || {}), [key]: event.target.value },
                    }
                    setPolicy(next)
                    setPolicyText(prettyPolicy(next))
                  }}
                >
                  {AGENT_AUTONOMY_LEVELS.map((item) => (
                    <option key={item} value={item}>
                      {AUTONOMY_COPY[item].title} — {item}
                    </option>
                  ))}
                </select>
                <button
                  className="btn secondary"
                  type="button"
                  onClick={() => {
                    const autonomy = { ...(policy.autonomy || {}) }
                    delete autonomy[key]
                    const next = { ...policy, autonomy }
                    setPolicy(next)
                    setPolicyText(prettyPolicy(next))
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
          <button
            className="btn secondary"
            type="button"
            style={{ marginTop: 10 }}
            onClick={() => {
              const next = {
                ...policy,
                autonomy: { ...(policy.autonomy || {}), "": "L2_EXECUTE_SAFE" },
              }
              setPolicy(next)
              setPolicyText(prettyPolicy(next))
            }}
          >
            Add a rule
          </button>

          <div className="runtime-form" style={{ marginTop: 18 }}>
            <label className="span-2">
              Allowed channels
              <input
                type="text"
                value={(policy.channels || []).join(", ")}
                onChange={(event) => {
                  const channels = event.target.value.split(",").map((part) => part.trim()).filter(Boolean)
                  const next = { ...policy, channels }
                  setPolicy(next)
                  setPolicyText(prettyPolicy(next))
                }}
              />
            </label>
            <label className="span-2">
              Approval-required actions
              <input
                type="text"
                value={(policy.approval_required_actions || []).join(", ")}
                onChange={(event) => {
                  const approval_required_actions = event.target.value.split(",").map((part) => part.trim()).filter(Boolean)
                  const next = { ...policy, approval_required_actions }
                  setPolicy(next)
                  setPolicyText(prettyPolicy(next))
                }}
              />
            </label>
            <label className="span-2">
              Hard prohibitions
              <textarea
                className="field"
                rows={3}
                value={(policy.hard_prohibitions || []).join("\n")}
                onChange={(event) => {
                  const hard_prohibitions = event.target.value.split("\n").map((part) => part.trim()).filter(Boolean)
                  const next = { ...policy, hard_prohibitions }
                  setPolicy(next)
                  setPolicyText(prettyPolicy(next))
                }}
              />
            </label>
          </div>

          <label style={{ marginTop: 16 }}>
            Policy JSON
            <textarea
              className="field policy-json"
              rows={14}
              value={policyText}
              onChange={(event) => {
                setPolicyText(event.target.value)
                setPolicyError("")
              }}
              onBlur={() => applyPolicyText()}
            />
          </label>
          {policyError && <p className="lede" style={{ color: "var(--bad)" }}>{policyError}</p>}
          {prompt && (
            <label style={{ marginTop: 16 }}>
              Brief Jarvis will use (updated on save)
              <textarea className="field" rows={5} value={prompt} readOnly />
            </label>
          )}
          {!!events.length && (
            <div style={{ marginTop: 16 }}>
              <h3 style={{ fontSize: 15 }}>Changes to this profile</h3>
              {events.map((event) => (
                <div className="suggestion-row" key={event.id}>
                  <div>
                    <strong>{event.field}</strong>
                    <p>{event.actor} · {formatWhen(event.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="interview-nav">
        <button className="btn secondary" type="button" disabled={busy} onClick={back}>
          {phase === "interview" && step === 0 ? "Back to list" : "Back"}
        </button>
        <div className="row">
          {phase === "interview" && (
            <>
              {editing && (
                <button className="btn secondary" type="button" disabled={busy} onClick={() => setPhase("summary")}>
                  Jump to summary
                </button>
              )}
              <button className="btn" type="button" disabled={busy} onClick={nextInterview}>
                {step >= INTERVIEW_STEPS.length - 1 ? "See summary" : "Next"}
              </button>
            </>
          )}
          {phase === "summary" && (
            <button className="btn" type="button" disabled={busy} onClick={() => void goToPolicy()}>
              Build policy
            </button>
          )}
          {phase === "policy" && (
            <>
              <button className="btn secondary" type="button" disabled={busy} onClick={() => void goToPolicy(false)}>
                Rebuild from answers
              </button>
              <button className="btn" type="button" disabled={busy} onClick={() => void onSave()}>
                {editing ? "Save agent" : "Create agent"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
