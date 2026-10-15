/** Controllable stand-ins for activateNamedPersona's dependencies (tests only). */
export const stubState = { activeId: undefined, avatarId: "mythic_portrait_a", presentationUpdates: [], selected: [] }

export function resetStubs({ activeId, avatarId = "mythic_portrait_a" } = {}) {
  stubState.activeId = activeId
  stubState.avatarId = avatarId
  stubState.presentationUpdates = []
  stubState.selected = []
}

// ../api
export function isApiError() { return false }
// ../presence/presentationSettings
export function readPresentationBootstrap() { return { avatarId: stubState.avatarId } }
export async function updatePresentation(patch) { stubState.presentationUpdates.push(patch) }
// ../tts/voiceProfiles
export async function installVoiceProfile() { return { installed: true } }
// ./namedPersonas
export const ROSTER_IDS = [
  "anzu", "mestor", "nabu", "enki", "veles", "themis", "aegir",
  "bragi", "hermes", "heimdall", "eir", "maia", "vulcan", "umi",
]
export const PERSONA_LABELS = {}
export function canonicalizePersonaId(raw) { return String(raw).trim().toLowerCase() }
export function currentActivePersonaId() { return stubState.activeId }
export async function selectNamedPersona(id) {
  stubState.selected.push(id)
  stubState.activeId = id
  return { active: { id }, personas: [] }
}
