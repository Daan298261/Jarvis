import { register } from "node:module"
import { pathToFileURL } from "node:url"

register("./apply-runtime-profile-test-loader.mjs", pathToFileURL("./"))
