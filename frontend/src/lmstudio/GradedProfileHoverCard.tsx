import type { LmStudioGradedProfile, LmStudioVramState } from "../api"

const AXIS_ROWS: { key: keyof LmStudioGradedProfile["axes"]; label: string; vramRow?: boolean }[] = [
  { key: "coding", label: "Coding" },
  { key: "writing", label: "Writing" },
  { key: "reasoning", label: "Reasoning" },
  { key: "speed_cost", label: "Speed / efficiency" },
  { key: "vram_fit", label: "Fit on this GPU", vramRow: true },
  { key: "instruction", label: "Agent / instruction following" },
  { key: "uncensored", label: "Restriction tolerance" },
]

function barBlocks(score: number): string {
  const filled = Math.max(0, Math.min(10, Math.round(score)))
  return `${"█".repeat(filled)}${"░".repeat(10 - filled)}`
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

function truncatePath(path: string, max = 42): string {
  if (path.length <= max) return path
  const tail = path.slice(-(max - 1))
  return `…${tail}`
}

function sortedAxes(profile: LmStudioGradedProfile) {
  return AXIS_ROWS.map((row) => ({ ...row, score: profile.axes[row.key] }))
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
  const axes = sortedAxes(profile)
  const strongest = [...axes].sort((a, b) => b.score - a.score).slice(0, 3)
  const weakest = [...axes].sort((a, b) => a.score - b.score).slice(0, 2)
  const roleList = roles(profile)

  return (
    <div className={`grade-hover-card${toneClass}${className ? ` ${className}` : ""}`} role="tooltip">
      <div className="grade-card-head">
        <span className="grade-card-title">{pinMark}{profile.display_name}</span>
        <span className="grade-card-overall">
          <strong>{tier(profile.overall)}</strong>
          <span> · {profile.overall.toFixed(1)}/10</span>
          <em className="grade-estimate-tag">estimated</em>
        </span>
      </div>

      <div className="grade-card-summary">
        <div>
          <small>Best at</small>
          <strong>{strongest.map((row) => row.label).join(" · ")}</strong>
        </div>
        <div>
          <small>Weakest at</small>
          <strong>{weakest.map((row) => row.label).join(" · ")}</strong>
        </div>
        <div>
          <small>Hardware fit</small>
          <strong>{vramHint(profile.vram_state, profile.weight_gb)}</strong>
        </div>
      </div>

      {roleList.length > 0 && (
        <div className="grade-role-chips" aria-label="Good Jarvis roles">
          {roleList.map((role) => <span key={role}>{role}</span>)}
        </div>
      )}

      <div className="grade-card-blurbs">
        <p className="grade-strength"><b>Strength:</b> {profile.strength}</p>
        <p className="grade-weakness"><b>Watch out:</b> {profile.weakness}</p>
      </div>

      <details className="grade-details">
        <summary>Detailed scores</summary>
        <div className="grade-card-axes">
          {axes.map(({ key, label, vramRow, score }) => {
            const vramClass = vramRow ? ` vram-${profile.vram_state}` : ""
            return (
              <div key={key} className={`grade-axis-row${vramClass}`}>
                <span className="grade-axis-label">{label}</span>
                <span className="grade-axis-bar" aria-hidden="true">{barBlocks(score)}</span>
                <span className="grade-axis-score">{score} · {tier(score)}</span>
              </div>
            )
          })}
        </div>
      </details>

      <div className="grade-card-foot">
        <span>{profile.weight_gb.toFixed(1)} GB · {profile.quantization} · {profile.id}</span>
        <span className="grade-card-path" title={profile.path}>{truncatePath(profile.path)}</span>
        {profile.source_notes ? <span className="grade-source-notes">Evidence: {profile.source_notes}</span> : null}
      </div>
      <p className="grade-provisional-foot">Published/estimated profile — local Jarvis measurements override this when available.</p>
    </div>
  )
}
