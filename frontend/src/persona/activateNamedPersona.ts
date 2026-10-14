import { isApiError } from "../api"
import { readPresentationBootstrap, updatePresentation } from "../presence/presentationSettings"
import { mythicAvatarForSelection } from "../presence/mythicPersonaVariant"
import { installVoiceProfile } from "../tts/voiceProfiles"
import {
  awaitPersonaMorphWithTimeout,
  type PersonaMorphContext,
  type PersonaMorphHook,
} from "../presence/personaMorphHook"
import {
  PERSONA_LABELS,
  ROSTER_IDS,
  canonicalizePersonaId,
  currentActivePersonaId,
  selectNamedPersona,
  type NamedPersonaId,
  type NamedPersonaState,
} from "./namedPersonas"

export type ActivatePersonaOptions = {
  onProgress?: (message: string) => void
  /** Why the switch happened; owner-initiated activation is "manual" (RFC-0218 S3 passes "intent"). */
  reason?: PersonaMorphContext["reason"]
  /** Morph seam to run; defaults to onCloudToPersonaMorph. Lets tests observe the call. */
  morphHook?: PersonaMorphHook
}

function rosterId(raw: string | undefined | null): NamedPersonaId | undefined {
  const id = canonicalizePersonaId(raw || "")
  return ROSTER_IDS.find((personaId) => personaId === id)
}

/** Select a main persona; install its neural voice pack first when the server requires it. */
export async function activateNamedPersona(
  id: string,
  options: ActivatePersonaOptions = {},
): Promise<NamedPersonaState> {
  // A named persona owns the main figure as well as the voice. Apply the HUD
  // mode optimistically so the existing particle stage starts morphing on the
  // same click instead of leaving the generic humanoid on screen.
  const fromId = rosterId(currentActivePersonaId())
  const variant = mythicAvatarForSelection(readPresentationBootstrap().avatarId)
  const presenceUpdate = updatePresentation({
    shell: "hud",
    requestedPresence: "particle_bust",
    avatarId: variant,
  })
  const personaUpdate = activatePersonaVoice(id, options)
  // RFC-0218 S5: cloud → persona morph seam. Bounded by a timeout and never throws,
  // so it cannot block or fail activation. Layout stays "A" until S4 lands.
  // The morph only runs between two distinct roster personas: with no previously
  // active persona (first load, catalog not yet published) there is no figure to
  // morph from, and re-selecting the same persona is not a switch.
  const toId = rosterId(id)
  const morph = fromId && toId && fromId !== toId
    ? awaitPersonaMorphWithTimeout(fromId, toId, {
      reason: options.reason ?? "manual",
      layout: "A",
      variant,
    }, undefined, options.morphHook)
    : Promise.resolve()
  const [presenceResult, personaResult] = await Promise.allSettled([presenceUpdate, personaUpdate, morph])
  if (personaResult.status === "rejected") throw personaResult.reason
  if (presenceResult.status === "rejected") throw presenceResult.reason
  return personaResult.value
}

async function activatePersonaVoice(
  id: string,
  options: ActivatePersonaOptions,
): Promise<NamedPersonaState> {
  const onProgress = options.onProgress
  try {
    return await selectNamedPersona(id)
  } catch (err) {
    if (!isApiError(err) || err.status !== 409) throw err
    const detail = (err.body as { detail?: { error?: string; profile_id?: string } } | null)?.detail
    if (detail?.error !== "install_required" && detail?.error !== "tts_unavailable") throw err
    const profileId = detail.profile_id
    if (!profileId) throw err
    onProgress?.(`Downloading the neural voice for ${PERSONA_LABELS[id] || id}…`)
    const result = await installVoiceProfile(profileId)
    if (!result.installed) {
      throw new Error(result.detail || `Could not install ${profileId}.`)
    }
    return selectNamedPersona(id)
  }
}
