Place `jarvis-backend.exe` (PyInstaller one-folder contents) here during Windows release builds.

The `jarvis-backend/` tree is a **build artifact**: extracted wheels and native deps (sklearn/libsvm, torch, transformers, …). It is listed in `.gitignore`.

Do **not** treat unfinished-work comments inside `_internal/` as Jarvis backlog items. Fix upstream or regenerate the sidecar; do not patch vendored C/Python in place.
