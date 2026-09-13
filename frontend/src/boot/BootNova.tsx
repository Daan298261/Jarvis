import { useEffect, useState, type ReactNode } from "react"
import { api } from "../api"
import "./bootNova.css"

export type SelfCheckItem = {
  id: string
  label: string
  status: "ready" | "starting" | "degraded" | "missing"
  detail: string
}

export type SelfCheckSnapshot = {
  ok: boolean
  overall: "ready" | "initializing" | "degraded" | "blocked"
  working_order: boolean
  headline: string
  checks: SelfCheckItem[]
}

const STORAGE_KEY = "jarvis.boot-check.v1"
const POLL_MS = 450
const MIN_MS = 2400
const READY_HOLD_MS = 1800
const MAX_MS = 14000

type BootNovaProps = {
  enabled: boolean
  children: ReactNode
}

function forceReplay(): boolean {
  try {
    return new URLSearchParams(window.location.search).has("boot")
  } catch {
    return false
  }
}

function readDone(): boolean {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === "done"
  } catch {
    return false
  }
}

function markDone(): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, "done")
  } catch {
    // ignore
  }
}

export function BootNova({ enabled, children }: BootNovaProps) {
  const [visible, setVisible] = useState(() => enabled && (forceReplay() || !readDone()))
  const [leaving, setLeaving] = useState(false)
  const [snapshot, setSnapshot] = useState<SelfCheckSnapshot | null>(null)
  const [phase, setPhase] = useState<"initializing" | "ready">("initializing")

  useEffect(() => {
    if (!visible) return
    const started = performance.now()
    let cancelled = false
    let timer: number | null = null

    const finish = (next: SelfCheckSnapshot | null) => {
      if (cancelled) return
      setSnapshot(next)
      setPhase("ready")
      window.setTimeout(() => {
        if (cancelled) return
        setLeaving(true)
        window.setTimeout(() => {
          if (cancelled) return
          markDone()
          setVisible(false)
        }, 700)
      }, READY_HOLD_MS)
    }

    const poll = async () => {
      let latest: SelfCheckSnapshot | null = null
      try {
        latest = await api<SelfCheckSnapshot>("/api/system/self-check")
        if (!cancelled) setSnapshot(latest)
      } catch {
        latest = null
      }
      const elapsed = performance.now() - started
      const complete = Boolean(latest && latest.working_order && latest.overall !== "initializing")
      if (complete && elapsed >= MIN_MS) {
        finish(latest)
        return
      }
      if (elapsed >= MAX_MS) {
        finish(latest)
        return
      }
      timer = window.setTimeout(() => { void poll() }, POLL_MS)
    }

    void poll()
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [visible])

  if (!visible) return <>{children}</>

  const checks = snapshot?.checks || PLACEHOLDER_CHECKS
  const ready = phase === "ready"

  return (
    <>
      {children}
      <div
        className={`boot-nova${leaving ? " leaving" : ""}${ready ? " ready" : ""}`}
        role="status"
        aria-live="polite"
      >
        <div className="boot-nova-vignette" aria-hidden />
        <div className="boot-nova-grid" aria-hidden />
        <div className="boot-nova-scan" aria-hidden />
        <div className="boot-nova-field" aria-hidden />
        <div className="boot-nova-stage">
          <div className="boot-nova-orb">
            <div className="boot-nova-aura" aria-hidden />
            <div className="boot-nova-orbit boot-nova-orbit-a" aria-hidden />
            <div className="boot-nova-orbit boot-nova-orbit-b" aria-hidden />
            <div className="boot-nova-orbit boot-nova-orbit-c" aria-hidden />
            <div className="boot-nova-radar" aria-hidden />
            <NovaGlyph ready={ready} />
            <div className="boot-nova-copy">
              <p className="boot-nova-kicker">Jarvis</p>
              <h1 className="boot-nova-title">
                {ready ? (
                  <>
                    All systems
                    <span>in working order</span>
                  </>
                ) : (
                  <>
                    <span className="boot-nova-colon">:</span>
                    Initializing
                    <span className="boot-nova-colon">:</span>
                  </>
                )}
              </h1>
            </div>
          </div>
          <ul className="boot-nova-checks">
            {checks.map((item, index) => (
              <li key={item.id} data-status={item.status} style={{ animationDelay: `${0.12 + index * 0.12}s` }}>
                <span className="boot-nova-dot" />
                <span>
                  <strong>{item.label}</strong>
                  <em>{item.detail}</em>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  )
}

const PLACEHOLDER_CHECKS: SelfCheckItem[] = [
  { id: "core", label: "Core systems", status: "starting", detail: "Contacting Jarvis" },
  { id: "inference", label: "Local inference", status: "starting", detail: "Checking the model" },
  { id: "household_voice", label: "Household voice", status: "starting", detail: "Preparing speech" },
  { id: "speech_recognition", label: "Speech recognition", status: "starting", detail: "Checking the microphone path" },
]

function tickMarks() {
  const marks = []
  for (let i = 0; i < 72; i += 1) {
    const major = i % 6 === 0
    const angle = (i * 5 * Math.PI) / 180
    const inner = major ? 248 : 256
    const outer = 268
    const cx = 320
    const cy = 320
    marks.push(
      <line
        key={i}
        className={major ? "boot-nova-tick major" : "boot-nova-tick"}
        x1={cx + Math.cos(angle) * inner}
        y1={cy + Math.sin(angle) * inner}
        x2={cx + Math.cos(angle) * outer}
        y2={cy + Math.sin(angle) * outer}
      />,
    )
  }
  return marks
}

function NovaGlyph({ ready }: { ready: boolean }) {
  return (
    <svg className="boot-nova-svg" viewBox="0 0 640 640" aria-hidden>
      <defs>
        <radialGradient id="bootNovaCore" cx="38%" cy="32%" r="58%">
          <stop offset="0%" stopColor="#f4fdff" stopOpacity="1" />
          <stop offset="18%" stopColor="#9be8ff" stopOpacity="0.95" />
          <stop offset="46%" stopColor="#67dcff" stopOpacity="0.55" />
          <stop offset="72%" stopColor="#d4a017" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#67dcff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="bootNovaHalo" cx="50%" cy="42%" r="58%">
          <stop offset="0%" stopColor="#67dcff" stopOpacity="0.32" />
          <stop offset="42%" stopColor="#d4a017" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#67dcff" stopOpacity="0" />
        </radialGradient>
        <filter id="bootNovaGlow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="8" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <circle cx="320" cy="320" r="292" fill="url(#bootNovaHalo)" className="boot-nova-ambient" />
      <g className="boot-nova-ticks">{tickMarks()}</g>
      <circle className="boot-nova-shock boot-nova-shock-0" cx="320" cy="320" r="118" />
      <circle className="boot-nova-shock boot-nova-shock-1" cx="320" cy="320" r="118" />
      <circle className="boot-nova-shock boot-nova-shock-2" cx="320" cy="320" r="118" />
      <circle className="boot-nova-shock boot-nova-shock-3" cx="320" cy="320" r="118" />
      <g className="boot-nova-spin-slow">
        <circle cx="320" cy="320" r="196" className="boot-nova-ring dashed" />
        <circle cx="320" cy="320" r="228" className="boot-nova-ring faint" />
      </g>
      <g className="boot-nova-spin-rev">
        <circle cx="320" cy="320" r="154" className="boot-nova-ring dashed tight" />
      </g>
      <circle cx="320" cy="320" r="118" className="boot-nova-ring solid" filter="url(#bootNovaGlow)" />
      <circle cx="320" cy="320" r="118" className="boot-nova-ring bright" />
      <g className="boot-nova-sparks">
        <circle cx="320" cy="202" r="7" className="boot-nova-spark" />
        <circle cx="438" cy="320" r="4" className="boot-nova-spark dim" />
        <circle cx="214" cy="368" r="3" className="boot-nova-spark dim" />
      </g>
      <circle cx="320" cy="320" r="86" fill="url(#bootNovaCore)" className="boot-nova-core" />
      <circle cx="304" cy="292" r="18" className="boot-nova-spec" />
      {ready && <circle cx="320" cy="320" r="118" className="boot-nova-flare" />}
    </svg>
  )
}
