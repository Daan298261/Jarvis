export { load } from "./hud-model-selector-render-test-loader.mjs"

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith(".") && !/\.(ts|tsx|js|mjs|json)$/.test(specifier)) {
    for (const extension of [".ts", ".tsx"]) {
      try { return await nextResolve(specifier + extension, context) } catch { /* Try the next extension. */ }
    }
  }
  return nextResolve(specifier, context)
}
