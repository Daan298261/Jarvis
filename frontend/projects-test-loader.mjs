const stubUrl = new URL("./projects-api-stub.mjs", import.meta.url).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier === "./api") {
    return { shortCircuit: true, url: stubUrl }
  }
  return nextResolve(specifier, context)
}
