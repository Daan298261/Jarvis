Recover local GGUF file discovery and registration from the abandoned installer-model branch. Scans run off the API event loop; registered models resolve through current profiles and appear in the model selector. Settings exposes Discover models on this PC and an explicit Add discovered models action.

Keep current installer defaults and voice startup behavior. Older experimental image backend placeholders are not reintroduced. Running-server discovery remains separate (#584).

Validation: 12 model discovery/profile tests passed; frontend build/lint and git diff --check passed. No model was loaded, downloaded, or switched during this recovery.
