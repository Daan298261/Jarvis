import { register } from "node:module"
import { pathToFileURL } from "node:url"

register("./hud-model-selector-render-test-loader.mjs", pathToFileURL("./"))
