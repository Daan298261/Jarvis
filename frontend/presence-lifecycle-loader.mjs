/** Resolve extension-less relative imports so node can load the presence TS graph. */
export async function resolve(specifier, context, nextResolve) {
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
