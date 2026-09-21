# Local vendor overlay (gitignored)

`license-issuer/` is created by `installer/windows/ensure-vendor-issuer.ps1` and by
`build-installer.ps1 -Release`. It holds `issuer.key` / `issuer.pub`.

Never commit those files. Public clones start without them: household voice
chatbot only, no local GGUF until someone passes `-InstallLocalLLM` or drops
weights into `models/`.
