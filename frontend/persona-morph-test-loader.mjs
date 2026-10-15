/** Stubs activateNamedPersona's API, presentation, voice and persona-store deps for persona-morph-hook.test.mjs. */
const stubs = {
  "../api": "./persona-morph-test-stubs.mjs",
  "../presence/presentationSettings": "./persona-morph-test-stubs.mjs",
  "../tts/voiceProfiles": "./persona-morph-test-stubs.mjs",
  "./namedPersonas": "./persona-morph-test-stubs.mjs",
}

export async function resolve(specifier, context, nextResolve) {
  if (stubs[specifier] && context.parentURL?.includes("/src/persona/activateNamedPersona.ts")) {
    return { shortCircuit: true, url: new URL(stubs[specifier], import.meta.url).href }
  }
  const relative = specifier.startsWith("./") || specifier.startsWith("../")
  const hasExt = /\.(ts|js|mjs|json|css)$/.test(specifier)
  if (relative && !hasExt) {
    try {
      return await nextResolve(`${specifier}.ts`, context)
    } catch {
      return nextResolve(specifier, context)
    }
  }
  return nextResolve(specifier, context)
}
