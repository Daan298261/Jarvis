/** Owner-facing copy when a technical setup fault leaks into the HUD. */
export const SETUP_PROBLEM_WORKING =
  "There's a setup problem. Jarvis is working on a fix."

export function ownerFacingApiMessage(raw: string): string {
  const lower = (raw || "").toLowerCase()
  if (
    lower.includes("private key") ||
    lower.includes("authentication required") ||
    lower.includes("x-jarvis-key") ||
    lower.includes("authorization: bearer") ||
    lower.includes("lease signature") ||
    lower.includes("invalid_signature")
  ) {
    return SETUP_PROBLEM_WORKING
  }
  return raw
}

export function isAuthFailureMessage(raw: string): boolean {
  const lower = (raw || "").toLowerCase()
  return (
    raw === SETUP_PROBLEM_WORKING ||
    lower.includes("authentication required") ||
    lower.includes("private key") ||
    lower.includes("x-jarvis-key")
  )
}
