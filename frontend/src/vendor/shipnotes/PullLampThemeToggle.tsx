import React, { useEffect, useRef } from "react"
import { ensureShipNotesScripts } from "./loadShipNotesScripts"

/** Ship Notes pull-lamp — toggles document data-theme for quick light/dark preview. */
export function PullLampThemeToggle() {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void ensureShipNotesScripts().then(() => {
      const host = hostRef.current
      if (!host || host.querySelector("pull-lamp")) return
      const lamp = document.createElement("pull-lamp")
      if (document.documentElement.dataset.theme === "light") {
        lamp.toggleAttribute("on", true)
      }
      lamp.addEventListener("themechange", (event: Event) => {
        const detail = (event as CustomEvent<{ theme: string }>).detail
        document.documentElement.dataset.theme = detail?.theme === "light" ? "light" : "dark"
      })
      host.appendChild(lamp)
    })
  }, [])

  return (
    <div style={{ marginTop: 12 }}>
      <p className="lede" style={{ margin: "0 0 8px" }}>
        Ship Notes pull lamp (theme preview)
      </p>
      <div ref={hostRef} style={{ maxWidth: 320 }} />
    </div>
  )
}
