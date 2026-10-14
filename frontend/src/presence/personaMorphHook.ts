import type { NamedPersonaId as PersonaId } from "../persona/namedPersonas"

/**
 * Cloud → persona morph seam. Astra fills the body.
 * Taco explicitly authorized this no-op body (2026-10-14) as the single
 * exception to the no-stub rule (RFC-0218). Do not add other stubs.
 */
export type PersonaMorphContext = {
  reason: "manual" | "intent"
  layout: "A" | "B" | "C"
  variant: string
}
export function onCloudToPersonaMorph(
  from: PersonaId,
  to: PersonaId,
  ctx: PersonaMorphContext,
): void | Promise<void> {
  // Parameters are the Astra contract; referenced only to satisfy noUnusedParameters.
  void from
  void to
  void ctx
}

export const PERSONA_MORPH_TIMEOUT_MS = 1500

export type PersonaMorphOutcome = "completed" | "timeout" | "error"

export type PersonaMorphHook = typeof onCloudToPersonaMorph

/**
 * Run the morph seam without ever blocking persona activation: resolves when the
 * hook settles or after `timeoutMs`, whichever is first. Never throws.
 */
export async function awaitPersonaMorphWithTimeout(
  from: PersonaId,
  to: PersonaId,
  ctx: PersonaMorphContext,
  timeoutMs: number = PERSONA_MORPH_TIMEOUT_MS,
  hook: PersonaMorphHook = onCloudToPersonaMorph,
): Promise<PersonaMorphOutcome> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    const run = Promise.resolve().then(() => hook(from, to, ctx)).then(() => "completed" as const)
    const deadline = new Promise<"timeout">((resolve) => {
      timer = setTimeout(() => resolve("timeout"), timeoutMs)
    })
    const outcome = await Promise.race([run, deadline])
    if (outcome === "timeout") console.warn(`persona morph ${from}→${to} exceeded ${timeoutMs}ms; continuing`)
    return outcome
  } catch (error) {
    console.warn(`persona morph ${from}→${to} failed; continuing`, error)
    return "error"
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
}
