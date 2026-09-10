let supported: boolean | undefined

export function supportsHumanoidRuntime(): boolean {
  if (supported !== undefined) return supported
  if (typeof document === "undefined") return false
  try {
    const canvas = document.createElement("canvas")
    const context = canvas.getContext("webgl2") || canvas.getContext("webgl")
    supported = Boolean(context)
    context?.getExtension("WEBGL_lose_context")?.loseContext()
  } catch {
    supported = false
  }
  return supported
}
