import React, { useState } from "react"
import { createRoot } from "react-dom/client"
import ApexOrb from "../src/vendor/apex-ui/ApexOrb"
import "../src/vendor/apex-ui/apex-orb.css"
import "./orb.css"

function Orb() {
  const [phase, setPhase] = useState<"idle" | "listening" | "thinking" | "speaking">("idle")
  ;(window as any).setJarvisPhase = (next: string) => {
    if (["idle", "listening", "thinking", "speaking"].includes(next)) setPhase(next as typeof phase)
  }
  return <ApexOrb state={phase} />
}
createRoot(document.getElementById("root")!).render(<Orb />)
