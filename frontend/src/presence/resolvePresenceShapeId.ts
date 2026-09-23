/**
 * RFC-0138 shape precedence for the live orb cloud.
 * Suite (hex_aegis) wins, then active custom preset / preview, then named persona.
 */
export function resolvePresenceShapeId(
  suiteActive: boolean,
  activePresetShapeId: string | null | undefined,
  personaShapeId: string | null | undefined,
): string {
  if (suiteActive) return "hex_aegis"
  const preset = (activePresetShapeId || "").trim()
  if (preset) return preset
  const persona = (personaShapeId || "").trim()
  if (!persona || persona === "anzu") return "stormbird"
  return persona
}
