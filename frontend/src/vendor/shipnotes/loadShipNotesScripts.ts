let loaded = false

export function ensureShipNotesScripts(): Promise<void> {
  if (loaded && customElements.get("voice-orb")) {
    return Promise.resolve()
  }
  const scripts = [
    "/vendor/shipnotes/voice-orb.js",
    "/vendor/shipnotes/signal-orb.js",
    "/vendor/shipnotes/project-stack.js",
    "/vendor/shipnotes/pull-lamp.js",
  ]
  return Promise.all(
    scripts.map(
      (src) =>
        new Promise<void>((resolve, reject) => {
          if (document.querySelector(`script[src="${src}"]`)) {
            resolve()
            return
          }
          const tag = document.createElement("script")
          tag.src = src
          tag.defer = true
          tag.onload = () => resolve()
          tag.onerror = () => reject(new Error(`Failed to load ${src}`))
          document.head.appendChild(tag)
        }),
    ),
  ).then(() => {
    loaded = true
  })
}
