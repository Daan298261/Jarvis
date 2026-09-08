import type { LmStudioGradedProfile, LmStudioVramState } from "../api"

const AXIS_ROWS: { key: keyof LmStudioGradedProfile["axes"]; label: string; vramRow?: boolean }[] = [
  { key: "coding", label: "Coding" },
  { key: "writing", label: "Writing" },
  { key: "reasoning", label: "Reasoning" },
  { key: "speed_cost", label: "Speed/Cost" },
  { key: "vram_fit", label: "VRAM fit", vramRow: true },
  { key: "instruction", label: "Instruction" },
  { key: "uncensored", label: "Uncensored" },
]

function barBlocks(score: number): string {
  const filled = Math.max(0, Math.min(10, Math.round(score)))
  return `${"█".repeat(filled)}${"░".repeat(10 - filled)}`
}

function vramHint(state: LmStudioVramState, weightGb: number): string {
  if (state === "hidden") return `⚠ ~${weightGb.toFixed(1)} GB`
  if (state === "warn") return `⚠ ~${weightGb.toFixed(1)} GB`
  return ""
}

function truncatePath(path: string, max = 42): string {
  if (path.length <= max) return path
  const tail = path.slice(-(max - 1))
  return `…${tail}`
}

export type GradedProfileHoverCardProps = {
  profile: LmStudioGradedProfile
  variant?: "classic" | "hud"
  className?: string
}

export function GradedProfileHoverCard({ profile, variant = "classic", className = "" }: GradedProfileHoverCardProps) {
  const toneClass = variant === "hud" ? " hud-grade-card" : ""
  const pinMark = profile.pinned ? "★ " : profile.favorite ? "♥ " : ""

  return (
    <div className={`grade-hover-card${toneClass}${className ? ` ${className}` : ""}`} role="tooltip">
      <div className="grade-card-head">
        <span className="grade-card-title">{pinMark}{profile.display_name}</span>
        <span className="grade-card-overall">
          Overall <strong>{profile.overall.toFixed(1)}</strong>
          <em className="grade-estimate-tag">est.</em>
        </span>
      </div>
      <div className="grade-card-axes">
        {AXIS_ROWS.map(({ key, label, vramRow }) => {
          const score = profile.axes[key]
          const vramClass = vramRow ? ` vram-${profile.vram_state}` : ""
          const hint = vramRow ? vramHint(profile.vram_state, profile.weight_gb) : ""
          return (
            <div key={key} className={`grade-axis-row${vramClass}`}>
              <span className="grade-axis-label">{label}</span>
              <span className="grade-axis-bar" aria-hidden="true">{barBlocks(score)}</span>
              <span className="grade-axis-score">{score}{hint ? `  ${hint}` : ""}</span>
            </div>
          )
        })}
      </div>
      <div className="grade-card-blurbs">
        <p className="grade-strength">+ {profile.strength}</p>
        <p className="grade-weakness">− {profile.weakness}</p>
      </div>
      <div className="grade-card-foot">
        <span>{profile.weight_gb.toFixed(1)} GB · {profile.quantization} · {profile.id}</span>
        <span className="grade-card-path" title={profile.path}>{truncatePath(profile.path)}</span>
        {profile.source_notes ? (
          <span className="grade-source-notes">{profile.source_notes}</span>
        ) : null}
      </div>
      <p className="grade-provisional-foot">Provisional estimate — not Jarvis-measured</p>
    </div>
  )
}
