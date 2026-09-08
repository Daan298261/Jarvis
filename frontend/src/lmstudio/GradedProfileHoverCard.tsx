import type { LmStudioGradedProfile, LmStudioVramState } from "../api"
import "./model-flip-card.css"

type ScoreRow = { label: string; score: number; hint?: string }

function clamp(score: number): number {
  return Math.max(0, Math.min(10, Math.round(score * 10) / 10))
}

function tier(score: number): string {
  if (score >= 9) return "Excellent"
  if (score >= 8) return "Strong"
  if (score >= 7) return "Good"
  if (score >= 6) return "Capable"
  if (score >= 5) return "Basic"
  return "Limited"
}

function vramHint(state: LmStudioVramState, weightGb: number): string {
  if (state === "hidden") return `Heavy · ~${weightGb.toFixed(1)} GB weights`
  if (state === "warn") return `Tight · ~${weightGb.toFixed(1)} GB weights`
  return `Comfortable · ~${weightGb.toFixed(1)} GB weights`
}

function detailedScores(profile: LmStudioGradedProfile): ScoreRow[] {
  const a = profile.axes
  const intelligence = clamp(a.reasoning * 0.5 + a.instruction * 0.3 + a.coding * 0.2)
  return [
    { label: "Intelligence", score: intelligence, hint: "reasoning + instruction + coding composite" },
    { label: "Coding", score: clamp(a.coding) },
    { label: "Writing", score: clamp(a.writing) },
    { label: "Reasoning", score: clamp(a.reasoning) },
    { label: "Agent / tools", score: clamp(a.instruction) },
    { label: "Speed", score: clamp(a.speed_cost) },
    { label: "Pricing / value", score: clamp(a.speed_cost), hint: "10 = cheaper/more efficient locally" },
    { label: "Hardware fit", score: clamp(a.vram_fit) },
    { label: "Restriction tolerance", score: clamp(a.uncensored) },
  ]
}

function roles(profile: LmStudioGradedProfile): string[] {
  const a = profile.axes
  const out: string[] = []
  if (a.instruction >= 7.5 && a.speed_cost >= 6.5) out.push("Agent / tools")
  if (a.coding >= 7.5) out.push("Coding")
  if (a.reasoning >= 7.5) out.push("Hard reasoning")
  if (a.writing >= 7.5) out.push("Writing")
  if (a.uncensored >= 8) out.push("Low-refusal specialist")
  return out.slice(0, 4)
}

export type GradedProfileHoverCardProps = {
  profile: LmStudioGradedProfile
  variant?: "classic" | "hud"
  className?: string
}

export function GradedProfileHoverCard({ profile, variant = "classic", className = "" }: GradedProfileHoverCardProps) {
  const toneClass = variant === "hud" ? " hud-grade-card" : ""
  const pinMark = profile.pinned ? "★ " : profile.favorite ? "♥ " : ""
  const scores = detailedScores(profile)
  const strongest = [...scores].sort((a, b) => b.score - a.score).slice(0, 3)
  const weakest = [...scores].sort((a, b) => a.score - b.score).slice(0, 2)
  const roleList = roles(profile)

  return (
    <div className={`model-flip-card${toneClass}${className ? ` ${className}` : ""}`} role="tooltip">
      <div className="model-flip-inner">
        <section className="model-flip-face model-flip-front">
          <div className="grade-card-head">
            <span className="grade-card-title">{pinMark}{profile.display_name}</span>
            <span className="grade-card-overall">
              <strong>{tier(profile.overall)}</strong>
              <span> · {profile.overall.toFixed(1)}/10</span>
            </span>
          </div>

          <div className="flip-hero-score">
            <strong>{scores[0].score.toFixed(1)}</strong>
            <span>Intelligence / 10</span>
          </div>

          <div className="grade-card-summary">
            <div><small>Best at</small><strong>{strongest.map((row) => row.label).join(" · ")}</strong></div>
            <div><small>Weakest at</small><strong>{weakest.map((row) => row.label).join(" · ")}</strong></div>
            <div><small>Hardware fit</small><strong>{vramHint(profile.vram_state, profile.weight_gb)}</strong></div>
          </div>

          {roleList.length > 0 && <div className="grade-role-chips">{roleList.map((role) => <span key={role}>{role}</span>)}</div>}
          <p className="grade-strength"><b>Strength:</b> {profile.strength}</p>
          <p className="grade-weakness"><b>Watch out:</b> {profile.weakness}</p>
          <div className="flip-hint">Hover to flip · detailed performance →</div>
        </section>

        <section className="model-flip-face model-flip-back">
          <div className="flip-back-head">
            <div><strong>{profile.display_name}</strong><span>Detailed scorecard</span></div>
            <span>{profile.weight_gb.toFixed(1)} GB · {profile.quantization}</span>
          </div>
          <div className="flip-score-grid">
            {scores.map((row) => (
              <div className="flip-score-row" key={row.label} title={row.hint || row.label}>
                <span>{row.label}</span>
                <div className="flip-score-track"><i style={{ width: `${row.score * 10}%` }} /></div>
                <strong>{row.score.toFixed(1)}/10</strong>
              </div>
            ))}
          </div>
          <div className="flip-back-foot">
            <span>Overall {profile.overall.toFixed(1)}/10 · {tier(profile.overall)}</span>
            <span>{profile.source_notes || "Published/estimated profile"}</span>
            <small>Scores are estimates until Jarvis has enough local benchmark history to replace them.</small>
          </div>
        </section>
      </div>
    </div>
  )
}
