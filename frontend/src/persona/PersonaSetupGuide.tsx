import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { speakChatReply } from "../tts/chatTtsPlayer"
import { useSpeakChatReplies } from "../tts/chatTtsSettings"
import { type NamedPersonaId } from "./namedPersonas"
import {
  advancePersonaSetup,
  beginPersonaSetup,
  PERSONA_TOOL_PACKS,
  restartPersonaSetup,
  skipPersonaSetup,
  usePersonaSetup,
} from "./personaSetup"
import "./named-persona.css"

type Props = {
  personaId: NamedPersonaId
  personaLabel: string
  defaultOpen?: boolean
  onDismiss?: () => void
}

export function PersonaSetupGuide({ personaId, personaLabel, defaultOpen = true, onDismiss }: Props) {
  const navigate = useNavigate()
  const [speakChatReplies] = useSpeakChatReplies()
  const progress = usePersonaSetup(personaId)
  const [open, setOpen] = useState(defaultOpen)
  const spokenKey = useRef("")
  const pack = PERSONA_TOOL_PACKS[personaId]
  const currentStep = pack.steps[progress.stepIndex]

  useEffect(() => {
    if (!open || progress.status !== "in_progress" || !speakChatReplies) return
    const key = `${personaId}:${currentStep.id}`
    if (spokenKey.current === key) return
    spokenKey.current = key
    void speakChatReply(`${personaLabel} setup. ${currentStep.label}. ${currentStep.detail}`)
  }, [currentStep, open, personaId, personaLabel, progress.status, speakChatReplies])

  const guidance = progress.status === "complete"
    ? `${personaLabel}'s ${pack.title.toLowerCase()} pack is ready.`
    : progress.status === "skipped"
      ? `Setup is paused. Resume whenever you want; your place is saved.`
      : `${currentStep.label}. ${currentStep.detail}`

  function resume() {
    beginPersonaSetup(personaId)
    setOpen(true)
  }

  function dismiss() {
    setOpen(false)
    onDismiss?.()
  }

  return (
    <section className="persona-setup" aria-label={`${personaLabel} tool setup`}>
      <div className="persona-setup-heading">
        <div>
          <span className="persona-setup-kicker">{progress.status === "complete" ? "Tool pack ready" : "First-use tool pack"}</span>
          <strong>{pack.title}</strong>
        </div>
        <button type="button" className="named-persona-icon-btn" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide" : progress.status === "complete" ? "Review" : "Resume"}
        </button>
      </div>
      <p className="settings-note">{pack.summary}</p>
      <div className="persona-tool-tags" aria-label="Preconfigured tools">
        {pack.tools.map((tool) => <span key={tool}>{tool}</span>)}
      </div>
      {open && (
        <div className="persona-setup-body">
          <div className="persona-setup-message" role="status">
            <span>{personaLabel}</span>
            <p>{guidance}</p>
          </div>
          {progress.status === "in_progress" && (
            <>
              <div className="persona-setup-progress" aria-label={`Step ${progress.stepIndex + 1} of ${pack.steps.length}`}>
                {pack.steps.map((item, index) => (
                  <span key={item.id} className={index <= progress.stepIndex ? "active" : ""} />
                ))}
              </div>
              <p className="settings-note">Step {progress.stepIndex + 1} of {pack.steps.length}. Credentials stay in their integration screen.</p>
              <div className="persona-setup-actions">
                <button type="button" className="btn secondary" onClick={() => navigate(currentStep.route)}>Open {currentStep.label}</button>
                <button type="button" className="btn secondary" onClick={() => void speakChatReply(`${personaLabel} setup. ${guidance}`)}>Hear guide</button>
                <button type="button" className="btn secondary" onClick={() => navigate(`/?personaSetup=${personaId}`)}>Ask in chat</button>
                <button type="button" className="btn secondary" onClick={() => advancePersonaSetup(personaId)}>
                  {progress.stepIndex === pack.steps.length - 1 ? "Mark ready" : "Next step"}
                </button>
                <button type="button" className="btn secondary" onClick={() => { skipPersonaSetup(personaId); dismiss() }}>Skip for now</button>
              </div>
            </>
          )}
          {progress.status === "skipped" && (
            <div className="persona-setup-actions">
              <button type="button" className="btn secondary" onClick={resume}>Resume setup</button>
              <button type="button" className="btn secondary" onClick={() => navigate(`/?personaSetup=${personaId}`)}>Ask in chat</button>
            </div>
          )}
          {progress.status === "complete" && (
            <div className="persona-setup-actions">
              <button type="button" className="btn secondary" onClick={() => { restartPersonaSetup(personaId); setOpen(true) }}>Run setup again</button>
              <button type="button" className="btn secondary" onClick={() => navigate(`/?personaSetup=${personaId}`)}>Ask in chat</button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
