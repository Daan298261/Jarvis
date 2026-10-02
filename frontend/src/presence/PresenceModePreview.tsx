export type PresenceModePreviewId =
  | "classic"
  | "neural"
  | "humanoid"
  | "particle_bust"
  | "galaxy"
  | "hexstrike"

type PresenceModePreviewProps = {
  mode: PresenceModePreviewId
}

/** Deterministic swatch matching the live profile contract (RFC-0195 / RFC-0136). */
export function PresenceModePreview({ mode }: PresenceModePreviewProps) {
  return (
    <span
      className="jarvis-presence-mode-preview"
      data-presence-preview={mode}
      aria-hidden="true"
    />
  )
}
