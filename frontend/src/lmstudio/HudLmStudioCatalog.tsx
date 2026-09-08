import { useEffect, useState } from "react"
import { getSelectedRuntimeProfileId } from "../api"
import { LmStudioCatalogPicker } from "./LmStudioCatalogPicker"

/** Compact HUD (cyan) LM Studio catalog for the health rail. */
export function HudLmStudioCatalog() {
  const [activeRuntimeId, setActiveRuntimeId] = useState(getSelectedRuntimeProfileId)

  useEffect(() => {
    const onStorage = () => setActiveRuntimeId(getSelectedRuntimeProfileId())
    window.addEventListener("storage", onStorage)
    return () => window.removeEventListener("storage", onStorage)
  }, [])

  return (
    <LmStudioCatalogPicker
      variant="hud"
      compact
      activeRuntimeId={activeRuntimeId}
      onSelected={(id) => setActiveRuntimeId(id)}
    />
  )
}
