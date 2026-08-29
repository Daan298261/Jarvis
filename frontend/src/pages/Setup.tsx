import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  advanceSetup,
  applySetup,
  completeSetup,
  getSetupRecommend,
  getSetupStatus,
  installSelectedComponents,
  installSetupComponent,
  listSetupComponents,
  putSetupState,
  type ComponentInstallState,
  type SetupRecommendation,
  type SetupState,
  type SetupWizardStep,
} from "../api"
import { DesktopBridge } from "../desktop/bridge"

const STEPS: { id: SetupWizardStep; title: string }[] = [
  { id: "welcome", title: "Welcome" },
  { id: "system", title: "System" },
  { id: "role", title: "Role" },
  { id: "resources", title: "Resources" },
  { id: "inference", title: "AI / Inference" },
  { id: "runtime", title: "Runtime & Models" },
  { id: "desktop", title: "Desktop" },
  { id: "verification", title: "Verification" },
]

const RESOURCE_CHOICES = [
  { id: "minimal", label: "Minimal", help: "Light footprint (~15%)" },
  { id: "balanced", label: "Balanced", help: "Static mid budget (~50%)" },
  { id: "dynamic", label: "Dynamic", help: "Recommended — adapts with load" },
  { id: "maximum", label: "Maximum", help: "Use nearly all capacity" },
  { id: "custom", label: "Custom", help: "Set percent and advanced limits" },
]

function formatBytes(done: number, total: number): string {
  if (!total && !done) return ""
  const fmt = (n: number) => {
    if (n > 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`
    if (n > 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`
    if (n > 1024) return `${(n / 1024).toFixed(0)} KB`
    return `${n} B`
  }
  return total ? `${fmt(done)} / ${fmt(total)}` : fmt(done)
}

export function SetupPage() {
  const navigate = useNavigate()
  const [state, setState] = useState<SetupState | null>(null)
  const [rec, setRec] = useState<SetupRecommendation | null>(null)
  const [components, setComponents] = useState<Record<string, ComponentInstallState>>({})
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const desktop = DesktopBridge.isDesktop()

  async function refresh() {
    const status = await getSetupStatus()
    setState(status.state)
    setComponents(status.components || {})
    if (status.state.completed) {
      navigate("/", { replace: true })
    }
  }

  useEffect(() => {
    refresh().catch((err) => setError(String(err)))
    getSetupRecommend()
      .then(setRec)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (state?.current_step !== "runtime") return
    const id = setInterval(() => {
      listSetupComponents()
        .then((r) => setComponents(r.components))
        .catch(() => undefined)
    }, 1500)
    return () => clearInterval(id)
  }, [state?.current_step])

  const stepIndex = useMemo(() => {
    const idx = STEPS.findIndex((s) => s.id === state?.current_step)
    return idx < 0 ? 0 : idx
  }, [state?.current_step])

  async function patch(partial: Partial<SetupState>) {
    const res = await putSetupState(partial)
    setState(res.state)
  }

  async function goNext(patchBody?: Partial<SetupState>) {
    if (!state) return
    setBusy(true)
    setError("")
    try {
      const next = STEPS[stepIndex + 1]?.id
      const res = await advanceSetup(state.current_step, next, patchBody as Record<string, unknown>)
      setState(res.state)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  async function goBack() {
    if (!state || stepIndex <= 0) return
    const prev = STEPS[stepIndex - 1].id
    await patch({ current_step: prev })
  }

  async function finish(opts?: { withoutLocalModel?: boolean }) {
    setBusy(true)
    setError("")
    try {
      await applySetup()
      const prefs = state?.desktop_prefs || {}
      if (desktop) {
        if (prefs.start_with_windows) await DesktopBridge.setAutostart(true)
        if (prefs.close_to_tray != null) await DesktopBridge.setCloseToTray(!!prefs.close_to_tray)
      }
      await completeSetup({
        apply: false,
        without_local_model: opts?.withoutLocalModel,
      })
      navigate("/", { replace: true })
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!state) {
    return (
      <div className="setup-shell">
        <h1>Jarvis setup</h1>
        <p className="lede">{error || "Loading setup…"}</p>
      </div>
    )
  }

  return (
    <div className="setup-shell">
      <header className="setup-header">
        <div>
          <strong className="setup-brand">JARVIS</strong>
          <h1>First-run setup</h1>
          <p className="lede">Configure this machine as a one-node Jarvis swarm. Progress is saved if a download fails.</p>
        </div>
        <ol className="setup-steps">
          {STEPS.map((s, i) => (
            <li key={s.id} className={i === stepIndex ? "active" : i < stepIndex ? "done" : ""}>
              {s.title}
            </li>
          ))}
        </ol>
      </header>

      {error && (
        <div className="card setup-error">
          <strong>Something went wrong</strong>
          <p>{error}</p>
          <button className="btn secondary" type="button" onClick={() => setError("")}>
            Dismiss
          </button>
        </div>
      )}

      <section className="card setup-panel">
        {state.current_step === "welcome" && (
          <>
            <h2>Welcome</h2>
            <p>Jarvis will run as a desktop application with a local backend. Models and runtimes stay outside the app install folder so upgrades keep your data.</p>
            <ul className="setup-list">
              <li>This device becomes a first-class Jarvis Node (standalone / one-node swarm).</li>
              <li>Join existing swarm is not available yet (P3).</li>
              <li>You can finish without a local model and use remote inference later.</li>
            </ul>
          </>
        )}

        {state.current_step === "system" && (
          <>
            <h2>System detection</h2>
            <p className="lede">Hardware already known to Jarvis (same probe as Swarm / System).</p>
            <div className="grid cards">
              {Object.entries(rec?.hardware_summary || {}).map(([key, value]) => (
                <div className="card" key={key}>
                  <div className="lede">{key.replaceAll("_", " ")}</div>
                  <strong>{String(value ?? "—")}</strong>
                </div>
              ))}
            </div>
            {rec?.notes?.length ? (
              <ul className="setup-list" style={{ marginTop: 16 }}>
                {rec.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : null}
          </>
        )}

        {state.current_step === "role" && (
          <>
            <h2>Jarvis role</h2>
            <p className="lede">
              Node class recommendation is derived from hardware. Orchestrator and Leader are roles with policies
              (AUTO / PREFERRED / FORCED / AVOID / DISABLED) — not the same as Workers or Capabilities.
            </p>
            <div className="kv">
              <b>This device</b>
              <span>Standalone / one-node swarm</span>
              <b>Recommended class</b>
              <span>{rec?.recommended_class || state.recommended_class || "—"}</span>
              <b>Join existing swarm</b>
              <span className="badge queued">Not yet implemented (P3)</span>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="lede">Suitable for</div>
              <ul className="setup-list">
                {(rec?.suitable_for || []).map((item) => (
                  <li key={item}>✓ {item.replaceAll("_", " ")}</li>
                ))}
              </ul>
            </div>
            <div className="row" style={{ marginTop: 16, gap: 12, flexWrap: "wrap" }}>
              {(["orchestrator", "leader"] as const).map((role) => (
                <label key={role} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span className="lede">{role}</span>
                  <select
                    value={state.role_policies?.[role] || rec?.role_policies?.[role] || "AUTO"}
                    onChange={(e) =>
                      patch({
                        role_policies: { ...(state.role_policies || {}), [role]: e.target.value },
                        recommended_class: rec?.recommended_class || state.recommended_class,
                      })
                    }
                  >
                    {["AUTO", "PREFERRED", "FORCED", "AVOID", "DISABLED"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <button
              className="btn secondary"
              type="button"
              style={{ marginTop: 12 }}
              onClick={() =>
                patch({
                  recommended_class: rec?.recommended_class || "",
                  role_policies: rec?.role_policies || {},
                  resource_preset: rec?.resource_preset || "dynamic",
                  inference_choice: rec?.inference_default || "local",
                })
              }
            >
              Apply recommendations
            </button>
          </>
        )}

        {state.current_step === "resources" && (
          <>
            <h2>Resource usage</h2>
            <p className="lede">How much of this machine Jarvis may use. Dynamic is the recommended default when hardware allows.</p>
            <div className="setup-choice-grid">
              {RESOURCE_CHOICES.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`setup-choice ${state.resource_preset === c.id ? "selected" : ""}`}
                  onClick={() => patch({ resource_preset: c.id, resource_mode: c.id === "dynamic" ? "dynamic" : "static" })}
                >
                  <strong>{c.label}</strong>
                  <span>{c.help}</span>
                </button>
              ))}
            </div>
            <label style={{ display: "block", marginTop: 16 }}>
              <div className="lede">Maximum resources available to Jarvis — {state.global_percent}%</div>
              <input
                type="range"
                min={5}
                max={100}
                value={state.global_percent}
                onChange={(e) => patch({ global_percent: Number(e.target.value), resource_preset: state.resource_preset === "dynamic" ? "dynamic" : "custom" })}
                style={{ width: "100%" }}
              />
            </label>
          </>
        )}

        {state.current_step === "inference" && (
          <>
            <h2>AI / Inference</h2>
            <div className="setup-choice-grid">
              {[
                { id: "local", label: "Local AI on this machine", help: "Uses Jarvis model profiles + llama.cpp (primary 9B by default)." },
                { id: "remote", label: "Remote / OpenAI-compatible server", help: "Point at an existing inference host." },
                { id: "later", label: "Configure later", help: "Finish setup without loading a model now." },
              ].map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`setup-choice ${state.inference_choice === c.id ? "selected" : ""}`}
                  onClick={() => patch({ inference_choice: c.id })}
                >
                  <strong>{c.label}</strong>
                  <span>{c.help}</span>
                </button>
              ))}
            </div>
            {state.inference_choice === "local" && (
              <label style={{ display: "block", marginTop: 16 }}>
                <div className="lede">Default local profile</div>
                <select
                  value={state.inference_profile}
                  onChange={(e) => patch({ inference_profile: e.target.value })}
                >
                  <option value="balanced">Balanced (9B primary)</option>
                  <option value="fast">Fast (9B)</option>
                  <option value="quality">Quality (9B)</option>
                </select>
              </label>
            )}
            {state.inference_choice === "remote" && (
              <div className="row" style={{ marginTop: 16, gap: 12 }}>
                <label>
                  <div className="lede">Host</div>
                  <input
                    value={state.remote_host}
                    onChange={(e) => patch({ remote_host: e.target.value })}
                  />
                </label>
                <label>
                  <div className="lede">Port</div>
                  <input
                    type="number"
                    value={state.remote_port}
                    onChange={(e) => patch({ remote_port: Number(e.target.value) })}
                  />
                </label>
              </div>
            )}
            <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 16 }}>
              <input
                type="checkbox"
                checked={!!state.install_expert_27b}
                onChange={(e) => patch({ install_expert_27b: e.target.checked })}
              />
              Also prepare optional Expert 27B (large download)
            </label>
          </>
        )}

        {state.current_step === "runtime" && (
          <>
            <h2>Runtime & model installation</h2>
            <p className="lede">Downloads are restartable. Existing valid files are not re-downloaded. Models stay outside the application binary.</p>
            <div className="row" style={{ marginBottom: 12, gap: 8 }}>
              <button
                className="btn"
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true)
                  setError("")
                  try {
                    await installSelectedComponents()
                    const listed = await listSetupComponents()
                    setComponents(listed.components)
                  } catch (err) {
                    setError(String(err))
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                Start / resume downloads
              </button>
            </div>
            <div className="setup-components">
              {Object.values(components).map((c) => (
                <div className="card" key={c.id}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <strong>{c.label}</strong>
                    <span className={`badge ${c.status === "ready" ? "completed" : c.status === "error" ? "failed" : "queued"}`}>
                      {c.status}
                    </span>
                  </div>
                  {c.bytes_total > 0 && (
                    <div className="setup-progress">
                      <div
                        style={{
                          width: `${Math.min(100, Math.round((100 * c.bytes_done) / c.bytes_total))}%`,
                        }}
                      />
                    </div>
                  )}
                  <div className="lede">
                    {formatBytes(c.bytes_done, c.bytes_total)}
                    {c.detail ? ` · ${c.detail}` : ""}
                  </div>
                  {c.error && <p style={{ color: "var(--bad)" }}>{c.error}</p>}
                  {(c.status === "error" || c.status === "pending") && (
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={async () => {
                        try {
                          await installSetupComponent(c.id)
                          const listed = await listSetupComponents()
                          setComponents(listed.components)
                        } catch (err) {
                          setError(String(err))
                        }
                      }}
                    >
                      Retry
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 12, gap: 8, flexWrap: "wrap" }}>
              <button className="btn secondary" type="button" onClick={() => patch({ inference_choice: "remote" })}>
                Configure remote inference instead
              </button>
              <button className="btn secondary" type="button" onClick={() => finish({ withoutLocalModel: true })}>
                Finish setup without local model
              </button>
            </div>
          </>
        )}

        {state.current_step === "desktop" && (
          <>
            <h2>Desktop preferences</h2>
            {!desktop && (
              <p className="lede">Running in browser mode — these preferences apply when launched as Jarvis.exe.</p>
            )}
            {(
              [
                ["start_with_windows", "Start with Windows (opt-in)"],
                ["start_minimized", "Start minimized to tray"],
                ["close_to_tray", "Close window hides to tray (backend keeps running)"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
                <input
                  type="checkbox"
                  checked={!!state.desktop_prefs?.[key]}
                  onChange={(e) =>
                    patch({
                      desktop_prefs: { ...(state.desktop_prefs || {}), [key]: e.target.checked },
                    })
                  }
                />
                {label}
              </label>
            ))}
          </>
        )}

        {state.current_step === "verification" && (
          <>
            <h2>Verification</h2>
            <div className="kv">
              <b>Role class</b>
              <span>{state.recommended_class || rec?.recommended_class || "—"}</span>
              <b>Resource preset</b>
              <span>
                {state.resource_preset} @ {state.global_percent}%
              </span>
              <b>Inference</b>
              <span>{state.inference_choice}</span>
              <b>Primary model</b>
              <span>{components.primary_model?.status || "—"}</span>
              <b>llama.cpp</b>
              <span>{components.llama_cpp?.status || "—"}</span>
            </div>
            <p className="lede" style={{ marginTop: 12 }}>
              Applying writes budget, role policies, and inference settings for this Node. You can change them later on Swarm / Settings.
            </p>
          </>
        )}
      </section>

      <footer className="setup-footer">
        <button className="btn secondary" type="button" disabled={stepIndex === 0 || busy} onClick={goBack}>
          Back
        </button>
        {state.current_step !== "verification" ? (
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() =>
              goNext(
                state.current_step === "system"
                  ? {
                      recommended_class: rec?.recommended_class || "",
                      role_policies: state.role_policies?.orchestrator
                        ? state.role_policies
                        : rec?.role_policies || {},
                      resource_preset: state.resource_preset || rec?.resource_preset || "dynamic",
                      inference_choice: state.inference_choice || rec?.inference_default || "local",
                    }
                  : undefined,
              )
            }
          >
            Continue
          </button>
        ) : (
          <button className="btn" type="button" disabled={busy} onClick={() => finish()}>
            Finish and open Jarvis
          </button>
        )}
      </footer>
    </div>
  )
}
