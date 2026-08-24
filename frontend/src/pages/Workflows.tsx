import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api, type Task } from "../api"

type Parameter = { key: string; label: string; default: string; placeholder: string; help: string }
type Step = { title: string; prompt: string }
type Workflow = {
  id: string
  name: string
  description: string
  category: string
  execution_mode: string
  builtin: boolean
  parameters: Parameter[]
  steps: Step[]
}
type GuideSection = { id: string; title: string; body: string }

const EMPTY: Workflow = {
  id: "",
  name: "Untitled workflow",
  description: "",
  category: "custom",
  execution_mode: "balanced",
  builtin: false,
  parameters: [{ key: "target", label: "Target", default: "", placeholder: "", help: "" }],
  steps: [{ title: "Do the work", prompt: "Complete the requested end state for {{target}}." }],
}

function cloneWorkflow(item: Workflow): Workflow {
  return {
    ...item,
    parameters: item.parameters.map((param) => ({ ...param })),
    steps: item.steps.map((step) => ({ ...step })),
  }
}

export function WorkflowsPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<"guide" | "library" | "editor">("guide")
  const [guide, setGuide] = useState<GuideSection[]>([])
  const [library, setLibrary] = useState<Workflow[]>([])
  const [draft, setDraft] = useState<Workflow>(EMPTY)
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")

  async function refresh() {
    const [sections, items] = await Promise.all([
      api<{ sections: GuideSection[] }>("/api/workflows/guide"),
      api<Workflow[]>("/api/workflows"),
    ])
    setGuide(sections.sections)
    setLibrary(items)
  }

  useEffect(() => { refresh().catch(() => undefined) }, [])

  function openEditor(item: Workflow) {
    const copy = cloneWorkflow(item)
    const next: Record<string, string> = {}
    for (const param of copy.parameters) next[param.key] = param.default || ""
    setDraft(copy)
    setValues(next)
    setTab("editor")
    setMessage("")
  }

  const preview = useMemo(() => {
    const filled = draft.steps.map((step, index) => {
      let prompt = step.prompt
      for (const [key, value] of Object.entries(values)) {
        prompt = prompt.replaceAll(`{{${key}}}`, value || `{{${key}}}`)
      }
      return `Stage ${index + 1} — ${step.title || "Untitled"}\n${prompt}`
    })
    return filled.join("\n\n")
  }, [draft, values])

  async function run() {
    if (!draft.steps.length) return
    setBusy(true)
    setMessage("")
    try {
      const result = await api<{ task: Task }>("/api/workflows/run", {
        method: "POST",
        body: JSON.stringify({
          workflow: { ...draft, builtin: false },
          parameters: values,
          execution_mode: draft.execution_mode,
        }),
      })
      navigate(`/tasks/${result.task.id}`)
    } catch (err: any) {
      setMessage(err.message || "Could not start the workflow")
    } finally {
      setBusy(false)
    }
  }

  async function savePreset() {
    setBusy(true)
    setMessage("")
    try {
      const payload = {
        ...draft,
        id: draft.builtin || !draft.id ? `${draft.id || "workflow"}-custom` : draft.id,
        builtin: false,
        name: draft.builtin ? `${draft.name} (custom)` : draft.name,
      }
      const saved = await api<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(payload) })
      await refresh()
      openEditor(saved)
      setMessage("Saved to data/workflows/.")
    } catch (err: any) {
      setMessage(err.message || "Could not save")
    } finally {
      setBusy(false)
    }
  }

  async function removePreset() {
    if (draft.builtin || !draft.id) return
    setBusy(true)
    try {
      await api(`/api/workflows/${draft.id}`, { method: "DELETE" })
      await refresh()
      setTab("library")
      setMessage("Preset deleted.")
    } catch (err: any) {
      setMessage(err.message || "Could not delete")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h1>Guide & Workflows</h1>
      <p className="lede">
        How to run Jarvis, plus ready-made workflows you can edit, chain, save, and launch in one click.
      </p>

      <div className="tabs">
        <button className={tab === "guide" ? "btn" : "btn secondary"} onClick={() => setTab("guide")}>Instructions</button>
        <button className={tab === "library" ? "btn" : "btn secondary"} onClick={() => setTab("library")}>Library</button>
        <button className={tab === "editor" ? "btn" : "btn secondary"} onClick={() => setTab("editor")}>Editor</button>
        <button className="btn secondary" onClick={() => openEditor({ ...EMPTY, id: "" })}>New workflow</button>
      </div>

      {message && <div className="card" style={{ marginBottom: 16, borderLeft: "4px solid var(--gold)" }}>{message}</div>}

      {tab === "guide" && (
        <div className="grid two">
          <div>
            {guide.map((section) => (
              <div className="card" key={section.id} style={{ marginBottom: 12 }}>
                <h2>{section.title}</h2>
                <p className="lede" style={{ margin: 0 }}>{section.body}</p>
              </div>
            ))}
          </div>
          <div className="card">
            <h2>Start from a template</h2>
            <p className="lede">Load any recipe into the editor, fill parameters, then Run. Jarvis treats the chain as one verified task.</p>
            <div className="row">
              <button className="btn" onClick={() => setTab("library")}>Open library</button>
            </div>
          </div>
        </div>
      )}

      {tab === "library" && (
        <div className="template-grid">
          {library.map((item) => (
            <button type="button" className="template-card" key={item.id} onClick={() => openEditor(item)}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{item.name}</strong>
                <span className={`badge ${item.builtin ? "queued" : "ok"}`}>{item.builtin ? "built-in" : "saved"}</span>
              </div>
              <p>{item.description}</p>
              <div className="stat">{item.category} · {item.steps.length} stages · {item.execution_mode}</div>
            </button>
          ))}
          {!library.length && <p className="lede">No workflows available.</p>}
        </div>
      )}

      {tab === "editor" && (
        <div className="grid two">
          <div>
            <div className="card">
              <h2>Workflow</h2>
              <label>Name
                <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </label>
              <label style={{ display: "block", marginTop: 10 }}>Description
                <textarea className="field" rows={3} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              </label>
              <label style={{ display: "block", marginTop: 10 }}>Execution mode
                <select value={draft.execution_mode} onChange={(e) => setDraft({ ...draft, execution_mode: e.target.value })}>
                  <option value="fast">Fast</option>
                  <option value="balanced">Balanced</option>
                  <option value="reliable">Reliable</option>
                </select>
              </label>
            </div>

            <div className="card" style={{ marginTop: 16 }}>
              <h2>Parameters</h2>
              {draft.parameters.map((param, index) => (
                <div key={`${param.key}-${index}`} style={{ marginBottom: 12 }}>
                  <label>{param.label || param.key}
                    <input
                      type="text"
                      placeholder={param.placeholder}
                      value={values[param.key] ?? ""}
                      onChange={(e) => setValues({ ...values, [param.key]: e.target.value })}
                    />
                  </label>
                  {param.help && <div className="stat" style={{ marginTop: 4 }}>{param.help}</div>}
                </div>
              ))}
              <button
                className="btn secondary"
                onClick={() => {
                  const key = `param${draft.parameters.length + 1}`
                  setDraft({
                    ...draft,
                    parameters: [...draft.parameters, { key, label: "New parameter", default: "", placeholder: "", help: "" }],
                  })
                  setValues({ ...values, [key]: "" })
                }}
              >
                Add parameter
              </button>
            </div>

            <div className="card" style={{ marginTop: 16 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 style={{ margin: 0 }}>Stages</h2>
                <button
                  className="btn secondary"
                  onClick={() => setDraft({ ...draft, steps: [...draft.steps, { title: "Next stage", prompt: "" }] })}
                >
                  Add stage
                </button>
              </div>
              {draft.steps.map((step, index) => (
                <div className="step-card" key={index}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <strong>Stage {index + 1}</strong>
                    <button
                      className="btn secondary"
                      onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, i) => i !== index) })}
                    >
                      Remove
                    </button>
                  </div>
                  <input
                    type="text"
                    value={step.title}
                    placeholder="Stage title"
                    style={{ marginTop: 8 }}
                    onChange={(e) => {
                      const steps = [...draft.steps]
                      steps[index] = { ...step, title: e.target.value }
                      setDraft({ ...draft, steps })
                    }}
                  />
                  <textarea
                    className="field"
                    rows={4}
                    style={{ marginTop: 8 }}
                    value={step.prompt}
                    placeholder="Prompt for this stage. Use {{parameter}} placeholders."
                    onChange={(e) => {
                      const steps = [...draft.steps]
                      steps[index] = { ...step, prompt: e.target.value }
                      setDraft({ ...draft, steps })
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="card">
              <h2>Launch</h2>
              <p className="lede">One click starts a single task that must complete every stage and verify the result.</p>
              <div className="row">
                <button className="btn" disabled={busy || !draft.steps.length} onClick={run}>Run workflow</button>
                <button className="btn secondary" disabled={busy} onClick={savePreset}>Save preset</button>
                {!draft.builtin && draft.id && (
                  <button className="btn secondary" disabled={busy} onClick={removePreset}>Delete preset</button>
                )}
              </div>
            </div>
            <div className="card" style={{ marginTop: 16 }}>
              <h2>Prompt preview</h2>
              <div className="report">{preview || "Add a stage to preview the composed prompt."}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
