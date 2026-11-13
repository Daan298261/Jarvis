export { load } from "./hud-model-selector-render-test-loader.mjs"

const emptyStub = new URL("./hud-model-selector-render-empty-stub.mjs", import.meta.url).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier.endsWith(".css")) return { shortCircuit: true, url: emptyStub }
  if (specifier.startsWith(".") && !/\.(ts|tsx|js|mjs|json)$/.test(specifier)) {
    for (const extension of [".ts", ".tsx"]) {
      try { return await nextResolve(specifier + extension, context) } catch { /* Try the next extension. */ }
    }
  }
  return nextResolve(specifier, context)
}
