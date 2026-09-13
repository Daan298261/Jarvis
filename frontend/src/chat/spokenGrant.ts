export type SpokenGrantMode = "allow_once" | "allow_session" | "always" | "deny"

const DENY_RE = /\b(no|nope|nah|deny|denied|refuse|refused|cancel|stop|never|don'?t|dont)\b|do not|not now/i
const ALWAYS_RE = /\b(always|every time|from now on|remember this)\b/i
const SESSION_RE = /\b(this session|for this session|just this session|for now)\b/i
const ALLOW_RE = /\b(yes|yeah|yep|yup|allow|allowed|proceed|okay|ok|sure|certainly|affirmative)\b|go ahead|of course|i grant|grant(?:ed)? (?:it|permission|this)|you may/i

function cleanTranscript(transcript: string): string {
  return transcript
    .toLowerCase()
    .replace(/[^a-z0-9\s']+/g, " ")
    .replace(/\bdo you grant(?: it)?\b/g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

/** Map a short spoken reply to a permission grant. Returns null when unclear. */
export function interpretSpokenGrant(transcript: string): SpokenGrantMode | null {
  const cleaned = cleanTranscript(transcript)
  if (!cleaned) return null
  const denied = DENY_RE.test(cleaned)
  if (ALWAYS_RE.test(cleaned) && !denied) return "always"
  if (SESSION_RE.test(cleaned) && !denied) return "allow_session"
  if (denied) return "deny"
  if (ALLOW_RE.test(cleaned)) return "allow_once"
  return null
}

export function spokenGrantUnclearMessage(): string {
  return "I didn't catch that, sir. Say yes, always, or no."
}
