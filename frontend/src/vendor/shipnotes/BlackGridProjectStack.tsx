import { useEffect, useRef } from "react"
import { ensureShipNotesScripts } from "./loadShipNotesScripts"

const PROJECTS = [
  {
    title: "HR Endless",
    tag: "VIDEO GEN",
    description: "MiniMax H3 long-form video with Gemma4 chunk prompts.",
    href: "/studio/blackgrid",
    accent: "#e879f9",
  },
  {
    title: "ComfyUI",
    tag: "NODE GRAPH",
    description: "Full graph editor, preview node, and save/load timeline.",
    href: "http://127.0.0.1:8188",
    accent: "#67dcff",
  },
  {
    title: "Jarvis Chat",
    tag: "ORCHESTRATOR",
    description: "Drive generation from tasks and blackgrid_studio tool calls.",
    href: "/",
    accent: "#7ee0b8",
  },
] as const

export function BlackGridProjectStack() {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void ensureShipNotesScripts().then(() => {
      const host = hostRef.current
      if (!host || host.querySelector("project-stack")) return
      const el = document.createElement("project-stack")
      const script = document.createElement("script")
      script.type = "application/json"
      script.textContent = JSON.stringify(PROJECTS)
      el.appendChild(script)
      host.appendChild(el)
    })
  }, [])

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <h2>Creative stack</h2>
      <p className="lede">Ship Notes project stack — quick links between studio surfaces.</p>
      <div ref={hostRef} style={{ maxWidth: 460 }} />
    </section>
  )
}
