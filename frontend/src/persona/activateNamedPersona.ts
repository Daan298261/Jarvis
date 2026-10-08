import { isApiError } from "../api"
import { updatePresentation } from "../presence/presentationSettings"
import { MYTHIC_LIVE_B_AVATAR_ID } from "../presence/mythicPersonaVariant"
import { installVoiceProfile } from "../tts/voiceProfiles"
import { PERSONA_LABELS, selectNamedPersona, type NamedPersonaState } from "./namedPersonas"

export type ActivatePersonaOptions = {
  onProgress?: (message: string) => void
}

/** Select a main persona; install its neural voice pack first when the server requires it. */
export async function activateNamedPersona(
  id: string,
  options: ActivatePersonaOptions = {},
): Promise<NamedPersonaState> {
  // A named persona owns the main figure as well as the voice. Apply the HUD
  // mode optimistically so the existing particle stage starts morphing on the
  // same click instead of leaving the generic humanoid on screen.
  const presenceUpdate = updatePresentation({
    shell: "hud",
    requestedPresence: "particle_bust",
    avatarId: MYTHIC_LIVE_B_AVATAR_ID,
  })
  const personaUpdate = activatePersonaVoice(id, options)
  const [presenceResult, personaResult] = await Promise.allSettled([presenceUpdate, personaUpdate])
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
