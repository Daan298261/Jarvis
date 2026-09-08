import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api"
import "./setup-conversation.css"

type SetupQuestion = {
  id: string
  question: string
  help?: string
  choices?: string[]
}

type PlannedModel = {
  id: string
  label: string
  role: string
  status: string
  selected: boolean
  bundled: boolean
  installed: boolean
  downloadable: boolean
  estimated_disk_gb?: number
  why: string
  limitations: string
  reason: string
}

type DiskPlan = {
  free_gb: number
  required_download_gb: number
  jarvis_runtime_gb: number
  lm_studio_gb: number
  safety_reserve_gb: number
  required_with_reserve_gb: number
  free_after_gb: number
  enough: boolean
  shortfall_gb: number
  message: string
}

type LmStudioPlan = {
  required: boolean
  installed: boolean
  path?: string
  reason: string
  install_script: string
}

type MobilePlan = {
  client: string
  apk_supported: boolean
  apk_script: string
  pairing_script: string
  same_lan: string
  remote_access: string
  router_forwarding_required: boolean
  router_forwarding: string
  reason: string
}

type InterviewPlan = {
  version: number
  answers: Record<string, any>
  hardware: Record<string, unknown>
  recommended_models: PlannedModel[]
  download_models: PlannedModel[]
  keep_loaded: string[]
  routing_policy: string
  disk: DiskPlan
  lm_studio: LmStudioPlan
  mobile: MobilePlan
  reasoning: string[]
}

type InterviewPayload = {
  version: number
  questions: SetupQuestion[]
  answers: Record<string, unknown>
  plan?: InterviewPlan
  completed: boolean
}

type PlanResponse = { plan: InterviewPlan }
type ApplyResponse = { ok: boolean; plan: InterviewPlan; download_script_path: string }

type SpeechRecognitionLike = {
  lang: string
  interimResults: boolean
  continuous: boolean
  start: () => void
  stop: () => void
  onresult: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onend: (() => void) | null
}

function speechRecognitionFactory(): (new () => SpeechRecognitionLike) | null {
  const host = window as any
  return host.SpeechRecognition || host.webkitSpeechRecognition || null
}

function shortHardware(hw: Record<string, unknown>): string {
  const ram = Number(hw.ram_total_gb || 0)
  const vram = Number(hw.vram_total_mib || 0) / 1024
  const gpu = String(hw.gpu_name || "CPU")
  const bits = []
  if (gpu && gpu !== "None") bits.push(gpu)
  if (ram) bits.push(`${Math.round(ram)} GB RAM`)
  if (vram) bits.push(`${vram.toFixed(0)} GB VRAM`)
  return bits.join(" · ") || "Hardware detected"
}

function fmtGb(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return `${Math.round(value * 10) / 10} GB`
}

export function SetupPage() {
  const navigate = useNavigate()
  const [questions, setQuestions] = useState<SetupQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [index, setIndex] = useState(0)
  const [input, setInput] = useState("")
  const [plan, setPlan] = useState<InterviewPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [error, setError] = useState("")
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const speechAvailable = useMemo(() => !!speechRecognitionFactory(), [])

  useEffect(() => {
    api<InterviewPayload>("/api/setup/interview")
      .then((payload) => {
        if (payload.completed) {
          navigate("/", { replace: true })
          return
        }
        setQuestions(payload.questions || [])
        const restored: Record<string, string> = {}
        for (const [key, value] of Object.entries(payload.answers || {})) {
          if (typeof value === "string") restored[key] = value
        }
        setAnswers(restored)
        if (payload.plan && Object.keys(payload.plan).length) setPlan(payload.plan)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [navigate])

  useEffect(() => () => recognitionRef.current?.stop(), [])

  const question = questions[index]

  function speakQuestion() {
    if (!question || !("speechSynthesis" in window)) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(question.question)
    utterance.rate = 1.02
    window.speechSynthesis.speak(utterance)
  }

  function startListening() {
    const Factory = speechRecognitionFactory()
    if (!Factory || listening) return
    const recognition = new Factory()
    recognition.lang = navigator.language || "en-US"
    recognition.interimResults = false
    recognition.continuous = false
    recognition.onresult = (event: any) => {
      const transcript = String(event?.results?.[0]?.[0]?.transcript || "").trim()
      if (transcript) setInput(transcript)
    }
    recognition.onerror = (event: any) => {
      setError(event?.error ? `Speech input: ${event.error}` : "Speech input failed. You can keep typing.")
      setListening(false)
    }
    recognition.onend = () => setListening(false)
    recognitionRef.current = recognition
    setListening(true)
    recognition.start()
  }

  async function buildPlan(nextAnswers: Record<string, string>) {
    setBusy(true)
    setError("")
    try {
      const result = await api<PlanResponse>("/api/setup/interview/plan", {
        method: "POST",
        body: JSON.stringify({ answers: nextAnswers }),
      })
      setPlan(result.plan)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function answer(value: string) {
    if (!question || !value.trim()) return
    const next = { ...answers, [question.id]: value.trim() }
    setAnswers(next)
    setInput("")
    if (index < questions.length - 1) {
      setIndex(index + 1)
      return
    }
    await buildPlan(next)
  }

  async function recommendedDefaults() {
    const defaults = {
      use: "A bit of everything",
      policy: "Local first",
      resources: "Balanced (~50%)",
      voice: "No",
    }
    setAnswers(defaults)
    setIndex(Math.max(0, questions.length - 1))
    await buildPlan(defaults)
  }

  async function apply() {
    if (plan && !plan.disk.enough) {
      setError(`Free about ${plan.disk.shortfall_gb} GB first, or change the setup choices.`)
      return
    }
    setBusy(true)
    setError("")
    try {
      const result = await api<ApplyResponse>("/api/setup/interview/apply", {
        method: "POST",
        body: JSON.stringify({ answers }),
      })
      if (!result.ok) throw new Error("Jarvis could not apply the setup plan.")
      navigate("/", { replace: true, state: { setupComplete: true, downloadScript: result.download_script_path } })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function restartInterview() {
    setPlan(null)
    setIndex(0)
    setInput("")
  }

  if (!questions.length && !error) {
    return <div className="setup-conversation"><p className="lede">Jarvis is preparing setup…</p></div>
  }

  return (
    <div className="setup-conversation">
      <header className="setup-conversation-head">
        <span className="setup-kicker">JARVIS · FIRST RUN</span>
        <h1>{plan ? "This is what I’ll configure" : "A few questions. That’s it."}</h1>
        <p className="lede">
          {plan
            ? "You can change any of this later. Jarvis keeps the complicated controls out of the way until you need them."
            : "Answer normally, pick a shortcut, or use the microphone. I’ll detect the hardware and configure the rest."}
        </p>
      </header>

      {error && <div className="setup-inline-error">{error}</div>}

      {!plan && question && (
        <section className="setup-interview-card">
          <div className="setup-progress" aria-label={`Question ${index + 1} of ${questions.length}`}>
            {questions.map((item, i) => <span key={item.id} className={i <= index ? "active" : ""} />)}
          </div>

          <div className="setup-jarvis-line">
            <span className="setup-ai-dot" aria-hidden />
            <div>
              <small>Jarvis</small>
              <h2>{question.question}</h2>
              {question.help && <p>{question.help}</p>}
            </div>
          </div>

          <div className="setup-choice-grid">
            {(question.choices || []).map((choice) => (
              <button key={choice} type="button" onClick={() => answer(choice)} disabled={busy}>{choice}</button>
            ))}
          </div>

          <div className="setup-answer-box">
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter" && input.trim()) void answer(input) }}
              placeholder="Or just tell Jarvis…"
              autoFocus
            />
            {speechAvailable && (
              <button className={`setup-mic${listening ? " listening" : ""}`} type="button" onClick={startListening} disabled={busy || listening} title="Answer by voice">
                {listening ? "Listening…" : "Mic"}
              </button>
            )}
            <button type="button" className="btn" onClick={() => answer(input)} disabled={busy || !input.trim()}>Send</button>
          </div>

          <div className="setup-interview-actions">
            <button type="button" className="setup-link" onClick={speakQuestion}>Read question aloud</button>
            {index > 0 && <button type="button" className="setup-link" onClick={() => setIndex(index - 1)}>Back</button>}
            <button type="button" className="setup-link" onClick={recommendedDefaults} disabled={busy}>Use recommended defaults</button>
          </div>
        </section>
      )}

      {plan && (
        <section className="setup-plan-card">
          <div className="setup-plan-hardware">
            <span>Detected</span>
            <strong>{shortHardware(plan.hardware)}</strong>
          </div>

          <div className={`setup-space-verdict ${plan.disk.enough ? "ok" : "bad"}`}>
            <div>
              <small>Disk space</small>
              <strong>{plan.disk.enough ? "Enough space" : "Not enough space"}</strong>
              <p>{plan.disk.message}</p>
            </div>
            <dl>
              <dt>Free now</dt><dd>{fmtGb(plan.disk.free_gb)}</dd>
              <dt>Selected downloads</dt><dd>{fmtGb(plan.disk.required_download_gb)}</dd>
              <dt>Reserved after setup</dt><dd>{fmtGb(plan.disk.safety_reserve_gb)}</dd>
              {!plan.disk.enough && <><dt>Free this much more</dt><dd>{fmtGb(plan.disk.shortfall_gb)}</dd></>}
            </dl>
          </div>

          <div className="setup-plan-grid">
            <div>
              <h3>Configuration</h3>
              <dl>
                <dt>Routing</dt><dd>{plan.routing_policy.replaceAll("-", " ")}</dd>
                <dt>Resource use</dt><dd>{String(plan.answers.resources || "Balanced")}</dd>
                <dt>Voice</dt><dd>{plan.answers.voice_enabled ? "enabled" : "off for now"}</dd>
                <dt>Bootstrap</dt><dd>Ornith 1.5 9B Q4_K_M · local</dd>
              </dl>
            </div>
            <div>
              <h3>Runtime</h3>
              <dl>
                <dt>llama.cpp</dt><dd>Built in · default</dd>
                <dt>LM Studio</dt><dd>{plan.lm_studio.required ? (plan.lm_studio.installed ? "required · installed" : "required · Jarvis can install it") : "not required"}</dd>
                <dt>Phone</dt><dd>LAN + {plan.mobile.remote_access}</dd>
                <dt>Router port</dt><dd>{plan.mobile.router_forwarding_required ? "required" : "not required"}</dd>
              </dl>
              <p className="lede" style={{ marginTop: 10 }}>{plan.lm_studio.reason}</p>
            </div>
          </div>

          <h3 className="setup-model-title">Models</h3>
          <div className="setup-model-list">
            {plan.recommended_models.map((model) => (
              <article key={model.id} className={`setup-model-row${model.selected ? " selected" : ""}`}>
                <div>
                  <strong>{model.label}</strong>
                  <span>{model.role}</span>
                </div>
                <p>{model.reason}</p>
                <span className="setup-model-status">
                  {model.installed ? "Installed" : model.bundled ? "Included in distro" : model.status}
                  {model.estimated_disk_gb ? ` · ~${model.estimated_disk_gb} GB` : ""}
                </span>
              </article>
            ))}
          </div>

          <div className="setup-zero-config">
            <h3>What Jarvis prepares for you</h3>
            <ul>
              <li><code>data/setup/download-models.ps1</code> — installs only the models this interview selected, with another disk-space check before download.</li>
              <li><code>data/setup/install-lm-studio.ps1</code> — normally does nothing because LM Studio is not required; it becomes a zero-config installer if a future setup needs it.</li>
              <li><code>data/setup/configure-mobile-access.ps1</code> — private firewall + Tailscale path; public UPnP router forwarding only when explicitly requested.</li>
              <li><code>scripts/build-android-client.ps1</code> — can produce a one-time pre-paired Android APK; the Phone page remains installable as a PWA without Android build tools.</li>
            </ul>
          </div>

          {plan.download_models.length > 0 ? (
            <p className="setup-download-note">Jarvis selected {plan.download_models.length} model download{plan.download_models.length === 1 ? "" : "s"} in addition to the bundled bootstrap.</p>
          ) : (
            <p className="setup-download-note">No additional model download is required to start using Jarvis.</p>
          )}

          <div className="setup-plan-actions">
            <button type="button" className="btn secondary" onClick={restartInterview} disabled={busy}>Change answers</button>
            <button type="button" className="btn" onClick={apply} disabled={busy || !plan.disk.enough}>
              {busy ? "Configuring…" : plan.disk.enough ? "Configure Jarvis" : `Free ${fmtGb(plan.disk.shortfall_gb)} first`}
            </button>
          </div>
          <p className="setup-advanced-note">Advanced controls remain available after setup under Model, Swarm, Settings and System. Security passwords are configured separately and are never unlocked by onboarding.</p>
        </section>
      )}
    </div>
  )
}
