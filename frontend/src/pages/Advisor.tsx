import { useMemo, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import {
  ADVISOR_STUB_PROVIDER,
  escalateAdvisor,
  formatAdvisorError,
  previewAdvisor,
  type AdvisorDisclosureField,
  type AdvisorDisclosurePackage,
  type AdvisorPreviewRequest,
  type AdvisorResponse,
} from "../api"

const TASK_CLASSES = [
  { value: "mixed", label: "Mixed" },
  { value: "filesystem", label: "Files" },
  { value: "coding", label: "Code" },
  { value: "office", label: "Office" },
  { value: "shell", label: "Terminal" },
  { value: "browser", label: "Browser" },
] as const

type FormState = {
  goal: string
  task_class: string
  unresolved_problem: string
  observations: string
  failed_approaches: string
  relevant_files: string
  retained_facts: string
  consecutive_failures: string
  confidence: string
  local_attempts: string
  already_escalated: string
  max_cost_usd: string
  advisor_cost_usd: string
}

function emptyForm(): FormState {
  return {
    goal: "",
    task_class: "mixed",
    unresolved_problem: "",
    observations: "",
    failed_approaches: "",
    relevant_files: "",
    retained_facts: "",
    consecutive_failures: "3",
    confidence: "0.4",
    local_attempts: "2",
    already_escalated: "0",
    max_cost_usd: "0.10",
    advisor_cost_usd: "0.02",
  }
}

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseNumber(value: string, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function compactJson(value: unknown): string {
  if (value == null) return "—"
  if (typeof value === "string") return value || "—"
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return `$${value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}`
}

function fieldValue(field: AdvisorDisclosureField): string {
  return compactJson(field.value)
}

function planSteps(plan: Record<string, unknown> | null): string[] {
  if (!plan) return []
  const raw = plan.steps
  if (!Array.isArray(raw)) return []
  return raw.map((step) => (typeof step === "string" ? step : compactJson(step))).filter(Boolean)
}

function unusedReason(reason: string): string {
  const key = reason.toLowerCase()
  if (key.includes("cost")) {
    return "The estimated advisor cost is above the ceiling you set. Nothing was sent."
  }
  if (key.includes("budget")) {
    return "This job has already used its advisor asks. Nothing was sent."
  }
  if (key.includes("no advisor provider")) {
    return "No advisor is configured. The built-in practice advisor was not used."
  }
  if (key.includes("denied") || key.includes("still viable")) {
    return "The local job still looks viable, so nothing was sent."
  }
  return reason || "The advisor was not used."
}

function buildPreviewBody(form: FormState): AdvisorPreviewRequest {
  return {
    goal: form.goal.trim(),
    task_class: form.task_class.trim() || "mixed",
    observations: lines(form.observations),
    failed_approaches: lines(form.failed_approaches),
    unresolved_problem: form.unresolved_problem.trim(),
    relevant_files: lines(form.relevant_files),
    retained_facts: lines(form.retained_facts),
    consecutive_failures: Math.max(0, Math.trunc(parseNumber(form.consecutive_failures, 0))),
    confidence: Math.min(1, Math.max(0, parseNumber(form.confidence, 1))),
    local_attempts: Math.max(0, Math.trunc(parseNumber(form.local_attempts, 0))),
    already_escalated: Math.max(0, Math.trunc(parseNumber(form.already_escalated, 0))),
    user_requested: true,
    max_cost_usd: Math.max(0, parseNumber(form.max_cost_usd, 0.1)),
    advisor_cost_usd: Math.max(0, parseNumber(form.advisor_cost_usd, 0.02)),
  }
}

export function AdvisorPage() {
  const [form, setForm] = useState<FormState>(emptyForm)
  const [preview, setPreview] = useState<AdvisorDisclosurePackage | null>(null)
  const [previewedFingerprint, setPreviewedFingerprint] = useState("")
  const [reviewed, setReviewed] = useState(false)
  const [result, setResult] = useState<AdvisorResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [msg, setMsg] = useState("")

  const requestBody = useMemo(() => buildPreviewBody(form), [form])
  const currentFingerprint = JSON.stringify(requestBody)
  const previewMatches = Boolean(preview) && previewedFingerprint === currentFingerprint
  const canEscalate = previewMatches && reviewed && !busy && Boolean(preview?.id)

  function patchForm(patch: Partial<FormState>) {
    setForm((current) => ({ ...current, ...patch }))
    setPreview(null)
    setPreviewedFingerprint("")
    setReviewed(false)
    setResult(null)
    setMsg("")
  }

  async function onPreview(event?: FormEvent) {
    event?.preventDefault()
    if (!requestBody.goal) {
      setError("Describe the stuck local task first.")
      return
    }
    setBusy(true)
    setError("")
    setMsg("")
    setResult(null)
    try {
      const packagePayload = await previewAdvisor(requestBody)
      setPreview(packagePayload)
      setPreviewedFingerprint(currentFingerprint)
      setReviewed(false)
      setMsg("Review exactly what would leave this PC. Nothing has been sent yet.")
    } catch (err: unknown) {
      setPreview(null)
      setPreviewedFingerprint("")
      setReviewed(false)
      setError(formatAdvisorError(err))
    } finally {
      setBusy(false)
    }
  }

  async function onEscalate() {
    if (!canEscalate || !preview) return
    setBusy(true)
    setError("")
    setMsg("")
    try {
      const response = await escalateAdvisor({
        package_id: preview.id,
        provider: ADVISOR_STUB_PROVIDER,
        consecutive_failures: requestBody.consecutive_failures,
        confidence: requestBody.confidence,
        local_attempts: requestBody.local_attempts,
        already_escalated: requestBody.already_escalated,
        user_requested: true,
        max_cost_usd: requestBody.max_cost_usd,
        advisor_cost_usd: requestBody.advisor_cost_usd,
      })
      setResult(response)
      if (response.used) {
        setMsg("Recommendations only. Nothing ran. You decide what the local orchestrator does next.")
      } else {
        setMsg(unusedReason(response.reason))
      }
    } catch (err: unknown) {
      setError(formatAdvisorError(err))
    } finally {
      setBusy(false)
    }
  }

  const outboundFields = preview?.fields.filter((field) => field.leaves_local) ?? []
  const keptLocal = preview?.local_only_retained ?? []
  const toolCalls = result?.tool_calls
  const leakedTools = Array.isArray(toolCalls) && toolCalls.length > 0
  const steps = planSteps(result?.structured_plan ?? null)

  return (
    <div className="advisor-page">
      <h1>Advisor</h1>
      <p className="lede">
        When a local job is stuck, preview exactly what would leave this PC, then ask for
        recommendations. The advisor can recommend. It cannot act. It has no tools, no file access,
        no spend, and cannot change anything. Nothing runs until you — the local orchestrator — do.
      </p>

      <div className="card advisor-limits">
        <p className="license-kicker">Recommend only</p>
        <ul>
          <li>No tools</li>
          <li>No file access</li>
          <li>No spending</li>
          <li>No changes on this PC</li>
          <li>Local Jarvis keeps execution</li>
        </ul>
      </div>

      {error && (
        <div className="card advisor-banner bad" role="alert">
          {error}
        </div>
      )}
      {msg && (
        <div className="card advisor-banner ok">
          {msg}
        </div>
      )}

      <form className="card grid" style={{ maxWidth: 760 }} onSubmit={onPreview}>
        <h2>Stuck local task</h2>
        <p className="lede" style={{ margin: "0 0 4px" }}>
          Describe what the local model already tried. The advisor only sees what you preview below.
        </p>
        <label>
          What is stuck?
          <textarea
            className="field"
            rows={4}
            value={form.goal}
            onChange={(event) => patchForm({ goal: event.target.value })}
            placeholder="The local job that is stuck on this PC"
            required
          />
        </label>
        <label>
          Kind of work
          <select
            value={form.task_class}
            onChange={(event) => patchForm({ task_class: event.target.value })}
          >
            {TASK_CLASSES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          What is still unsolved?
          <textarea
            className="field"
            rows={3}
            value={form.unresolved_problem}
            onChange={(event) => patchForm({ unresolved_problem: event.target.value })}
            placeholder="The remaining problem, if different from the goal"
          />
        </label>
        <label>
          What you already saw
          <textarea
            className="field"
            rows={3}
            value={form.observations}
            onChange={(event) => patchForm({ observations: event.target.value })}
            placeholder="One note per line"
          />
        </label>
        <label>
          What already failed
          <textarea
            className="field"
            rows={3}
            value={form.failed_approaches}
            onChange={(event) => patchForm({ failed_approaches: event.target.value })}
            placeholder="One approach per line"
          />
        </label>
        <label>
          File names that may be mentioned
          <textarea
            className="field"
            rows={3}
            value={form.relevant_files}
            onChange={(event) => patchForm({ relevant_files: event.target.value })}
            placeholder="Names only, one per line. The advisor cannot open files."
          />
        </label>
        <label>
          Facts to include
          <textarea
            className="field"
            rows={3}
            value={form.retained_facts}
            onChange={(event) => patchForm({ retained_facts: event.target.value })}
            placeholder="Short facts the advisor may see, one per line"
          />
        </label>
        <div className="advisor-metrics">
          <label>
            Local tries
            <input
              type="number"
              min={0}
              value={form.local_attempts}
              onChange={(event) => patchForm({ local_attempts: event.target.value })}
            />
          </label>
          <label>
            Failures in a row
            <input
              type="number"
              min={0}
              value={form.consecutive_failures}
              onChange={(event) => patchForm({ consecutive_failures: event.target.value })}
            />
          </label>
          <label>
            Local confidence (0–1)
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.confidence}
              onChange={(event) => patchForm({ confidence: event.target.value })}
            />
          </label>
          <label>
            Times already asked
            <input
              type="number"
              min={0}
              value={form.already_escalated}
              onChange={(event) => patchForm({ already_escalated: event.target.value })}
            />
          </label>
          <label>
            Cost ceiling
            <input
              type="number"
              min={0}
              step={0.01}
              value={form.max_cost_usd}
              onChange={(event) => patchForm({ max_cost_usd: event.target.value })}
            />
          </label>
          <label>
            Estimated advisor cost
            <input
              type="number"
              min={0}
              step={0.01}
              value={form.advisor_cost_usd}
              onChange={(event) => patchForm({ advisor_cost_usd: event.target.value })}
            />
          </label>
        </div>
        <label>
          Advisor
          <input value="Built-in practice advisor (stub). No commercial cloud." readOnly />
        </label>
        <div className="row">
          <button className="btn" type="submit" disabled={busy || !form.goal.trim()}>
            {busy && !previewMatches ? "Building preview…" : "Preview what would leave"}
          </button>
        </div>
      </form>

      <div className="card" style={{ maxWidth: 920, marginTop: 16 }}>
        <h2>What would leave this PC</h2>
        {!previewMatches && (
          <p className="lede">
            Preview is required before you can ask the advisor. Escalate stays off until you review
            the outbound context below.
          </p>
        )}
        {previewMatches && preview && (
          <>
            <div className="advisor-estimates">
              <div>
                <b>Tokens</b>
                <span>{preview.token_estimate}</span>
              </div>
              <div>
                <b>Estimated cost</b>
                <span>{formatUsd(preview.cost_estimate_usd)}</span>
              </div>
              <div>
                <b>Package</b>
                <span className="stat">{preview.id}</span>
              </div>
            </div>
            <div className="advisor-split">
              <section className="advisor-column leave">
                <h3>Leaves this PC</h3>
                <p className="lede">Exactly what the advisor would receive. Nothing else.</p>
                {outboundFields.length === 0 && (
                  <p className="lede">No outbound fields in this preview.</p>
                )}
                {outboundFields.map((field) => (
                  <div key={field.key} className="advisor-field">
                    <strong>{field.label}</strong>
                    <pre className="advisor-json">{fieldValue(field)}</pre>
                  </div>
                ))}
                <details className="advisor-raw">
                  <summary>Full outbound package</summary>
                  <pre className="advisor-json">{compactJson(preview.outbound_preview)}</pre>
                </details>
              </section>
              <section className="advisor-column keep">
                <h3>Stays on this PC</h3>
                <p className="lede">Kept local. The advisor cannot use these.</p>
                <ul className="advisor-keep-list">
                  {keptLocal.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                  <li>Tools and execution</li>
                  <li>File contents</li>
                  <li>Spend and state changes</li>
                </ul>
              </section>
            </div>
            <label className="row advisor-confirm">
              <input
                type="checkbox"
                checked={reviewed}
                onChange={(event) => setReviewed(event.target.checked)}
              />
              <span>I reviewed what would leave this PC. The advisor can only recommend.</span>
            </label>
            <div className="row">
              <button className="btn" type="button" disabled={!canEscalate} onClick={onEscalate}>
                {busy && previewMatches ? "Asking advisor…" : "Ask advisor for recommendations"}
              </button>
            </div>
            {!canEscalate && (
              <p className="lede" style={{ margin: "10px 0 0" }}>
                {!reviewed
                  ? "Confirm the outbound preview before asking."
                  : "Preview what would leave this PC first."}
              </p>
            )}
          </>
        )}
      </div>

      {result && (
        <div className="card" style={{ maxWidth: 760, marginTop: 16 }}>
          <h2>Advisor reply</h2>
          <p className="lede">
            Execution stays with you. The advisor cannot run this plan.
          </p>
          <div className="kv">
            <b>Used</b>
            <span>{result.used ? "Yes — recommendations only" : "No"}</span>
            <b>Advisor</b>
            <span>{result.advisor_name || "stub"}</span>
            <b>Who can act</b>
            <span>Local orchestrator — not the advisor</span>
            <b>Tools</b>
            <span>{leakedTools ? "Blocked — advisors cannot use tools" : "None"}</span>
          </div>
          {result.reason && (
            <p className="lede" style={{ marginTop: 12 }}>
              {result.used ? result.reason : unusedReason(result.reason)}
            </p>
          )}
          {leakedTools && (
            <div className="card advisor-banner bad" style={{ marginTop: 12 }}>
              The advisor tried to include tools. Those were ignored. Advisors cannot run anything.
            </div>
          )}
          {result.analysis && (
            <div className="advisor-reply-block">
              <h3>Analysis</h3>
              <p>{result.analysis}</p>
            </div>
          )}
          {result.recommendations?.length > 0 && (
            <div className="advisor-reply-block">
              <h3>Recommendations</h3>
              <ul>
                {result.recommendations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {steps.length > 0 && (
            <div className="advisor-reply-block">
              <h3>Suggested plan</h3>
              <ol>
                {steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </div>
          )}
          {result.structured_plan && steps.length === 0 && (
            <div className="advisor-reply-block">
              <h3>Suggested plan</h3>
              <pre className="advisor-json">{compactJson(result.structured_plan)}</pre>
            </div>
          )}
          <p className="lede" style={{ marginTop: 12 }}>
            To act, start a local task yourself.{" "}
            <Link to="/">New task</Link>
          </p>
        </div>
      )}
    </div>
  )
}
