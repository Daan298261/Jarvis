import { isApiError } from "../api"
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
