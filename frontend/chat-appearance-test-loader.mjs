export { load } from "./hud-model-selector-render-test-loader.mjs"

const emptyStub = new URL("./hud-model-selector-render-empty-stub.mjs", import.meta.url).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier.endsWith(".css")) return { shortCircuit: true, url: emptyStub }
  // Image and model assets resolve to their URL string under Vite; a test only needs a string default export.
  if (/\.(png|jpe?g|webp|gif|svg|glb|gltf|hdr|mp3|wav|onnx)$/.test(specifier)) return { shortCircuit: true, url: "data:text/javascript,export default \"asset\"" }
  if (specifier.startsWith(".") && !/\.(ts|tsx|js|mjs|json)$/.test(specifier)) {
    for (const extension of [".ts", ".tsx"]) {
      try { return await nextResolve(specifier + extension, context) } catch { /* Try the next extension. */ }
    }
  }
  return nextResolve(specifier, context)
}
