import { readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import ts from "typescript"

const stubs = {
  api: new URL("./hud-model-selector-render-api-stub.mjs", import.meta.url).href,
  router: new URL("./hud-model-selector-render-router-stub.mjs", import.meta.url).href,
  engineMode: new URL("./hud-model-selector-render-empty-stub.mjs", import.meta.url).href,
}

export async function resolve(specifier, context, nextResolve) {
  const fromHud = !!context.parentURL && context.parentURL.includes("/src/hud/")
  if (fromHud && (specifier === "../api" || specifier === "./api")) return { shortCircuit: true, url: stubs.api }
  if (specifier === "react-router-dom") return { shortCircuit: true, url: stubs.router }
  if (specifier === "../components/EngineModeControl") return { shortCircuit: true, url: stubs.engineMode }
  if (specifier.endsWith(".css")) return { shortCircuit: true, url: stubs.engineMode }
  const relative = specifier.startsWith("./") || specifier.startsWith("../")
  if (relative && !/\.(ts|tsx|js|mjs|json)$/.test(specifier)) {
    for (const ext of [".ts", ".tsx"]) {
      try { return await nextResolve(specifier + ext, context) } catch { /* try the next extension */ }
    }
  }
  return nextResolve(specifier, context)
}

export async function load(url, context, nextLoad) {
  if (!url.endsWith(".tsx")) return nextLoad(url, context)
  const source = await readFile(fileURLToPath(url), "utf8")
  const { outputText } = ts.transpileModule(source, {
    fileName: fileURLToPath(url),
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return { format: "module", source: outputText, shortCircuit: true }
}
