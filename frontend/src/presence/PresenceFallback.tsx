import type { PresenceSnapshot } from "./presenceTypes"

type PresenceFallbackProps = {
  snapshot: PresenceSnapshot
}

export function PresenceFallback({ snapshot }: PresenceFallbackProps) {
  return (
    <div className={`jarvis-presence-fallback phase-${snapshot.phase}`} role="img" aria-label={`Jarvis is ${snapshot.phase}`}>
      <span className="jarvis-presence-fallback-core" aria-hidden />
    </div>
  )
}
