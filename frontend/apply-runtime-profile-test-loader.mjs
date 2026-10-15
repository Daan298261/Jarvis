const apiStub = new URL("./apply-runtime-profile-api-stub.mjs", import.meta.url).href
const suiteStub = new URL("./apply-runtime-profile-hexstrike-suite-stub.mjs", import.meta.url).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier === "../api" || specifier === "./api") {
    return { shortCircuit: true, url: apiStub }
  }
  if (specifier === "./hexstrikeSuite") {
    return { shortCircuit: true, url: suiteStub }
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
