import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { api } from "../api"
import { IntegrationSetup } from "../components/IntegrationSetup"
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
  why: string
  limitations: string
  reason: string
}

type InterviewPlan = {
  version: number
  answers: Record<string, unknown>
  hardware: Record<string, unknown>
  recommended_models: PlannedModel[]
  download_models: PlannedModel[]
  keep_loaded: string[]
  routing_policy: string
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

export function SetupPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const isConnections = new URLSearchParams(location.search).get("step") === "integrations"
  const [questions, setQuestions] = useState<SetupQuestion[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [index, setIndex] = useState(0)
  const [input, setInput] = useState("")
  const [plan, setPlan] = useState<InterviewPlan | null>(null)
  const [interviewComplete, setInterviewComplete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const [error, setError] = useState("")
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const speechAvailable = useMemo(() => !!speechRecognitionFactory(), [])

  useEffect(() => {
    api<InterviewPayload>("/api/setup/interview")
      .then((payload) => {
        setInterviewComplete(payload.completed)
        if (payload.completed && !isConnections) {
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
      .catch((err) => {
        if (!isConnections) setError(err instanceof Error ? err.message : String(err))
      })
  }, [isConnections, navigate])

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
    setBusy(true)
    setError("")
    try {
      const result = await api<ApplyResponse>("/api/setup/interview/apply", {
        method: "POST",
        body: JSON.stringify({ answers }),
      })
      if (!result.ok) throw new Error("Jarvis could not apply the setup plan.")
      navigate("/setup?step=integrations", { replace: true })
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

  if (isConnections) {
    return (
      <div className="setup-conversation setup-connections">
        <header className="setup-conversation-head">
          <span className="setup-kicker">JARVIS · CONNECTIONS</span>
          <h1>Connect Gmail and WhatsApp</h1>
          <p className="lede">No terminal commands. Jarvis checks Gmail for you and shows the WhatsApp QR code here.</p>
        </header>
        {error && <div className="setup-inline-error">{error}</div>}
        <IntegrationSetup />
        <div className="setup-plan-actions setup-connections-actions">
          <button type="button" className="btn" onClick={() => navigate(interviewComplete ? "/" : "/setup", { replace: true })}>
            {interviewComplete ? "Finish and open Jarvis" : "Continue setup"}
          </button>
        </div>
        <p className="setup-advanced-note">Both connections are optional and can be changed later under Connections.</p>
      </div>
    )
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
              <button key={choice} type="button" onClick={() => answer(choice)} disabled={busy}>
                {choice}
              </button>
            ))}
          </div>

          <div className="setup-answer-box">
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && input.trim()) void answer(input)
              }}
              placeholder="Or just tell Jarvis…"
              autoFocus
            />
            {speechAvailable && (
              <button
                className={`setup-mic${listening ? " listening" : ""}`}
                type="button"
                onClick={startListening}
                disabled={busy || listening}
                title="Answer by voice"
              >
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

          <div className="setup-plan-grid">
            <div>
              <h3>Configuration</h3>
              <dl>
                <dt>Routing</dt><dd>{plan.routing_policy.replaceAll("-", " ")}</dd>
                <dt>Resource use</dt><dd>{String(plan.answers.resources || "Balanced")}</dd>
                <dt>Voice</dt><dd>{plan.answers.voice_enabled ? "enabled" : "off for now"}</dd>
                <dt>Bootstrap</dt><dd>Ornith 1.5 9B · local</dd>
              </dl>
            </div>
            <div>
              <h3>Why</h3>
              <ul>{plan.reasoning.map((reason) => <li key={reason}>{reason}</li>)}</ul>
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
                  {model.installed ? "Installed" : model.bundled ? "Included" : model.status}
                </span>
              </article>
            ))}
          </div>

          {plan.download_models.length > 0 ? (
            <p className="setup-download-note">
              Jarvis will also create <code>data/setup/download-models.ps1</code> for {plan.download_models.length} selected model{plan.download_models.length === 1 ? "" : "s"} that are not already present.
            </p>
          ) : (
            <p className="setup-download-note">No additional model download is required to start using Jarvis.</p>
          )}

          <div className="setup-plan-actions">
            <button type="button" className="btn secondary" onClick={restartInterview} disabled={busy}>Change answers</button>
            <button type="button" className="btn" onClick={apply} disabled={busy}>{busy ? "Configuring…" : "Configure Jarvis"}</button>
          </div>
          <p className="setup-advanced-note">
            Advanced controls remain available after setup under Model, Swarm, Settings and System. Security passwords are configured separately.
          </p>
        </section>
      )}
    </div>
  )
}
