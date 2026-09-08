import { useEffect, useState } from "react"
import { getSelectedRuntimeProfileId } from "../api"
import { LmStudioCatalogPicker } from "./LmStudioCatalogPicker"

/** Classic (orange/black) LM Studio catalog block for the Model page. */
export function LmStudioCatalogClassicSection() {
  const [activeRuntimeId, setActiveRuntimeId] = useState(getSelectedRuntimeProfileId)

  useEffect(() => {
    const onStorage = () => setActiveRuntimeId(getSelectedRuntimeProfileId())
    window.addEventListener("storage", onStorage)
    return () => window.removeEventListener("storage", onStorage)
  }, [])

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <LmStudioCatalogPicker
        variant="classic"
        activeRuntimeId={activeRuntimeId}
        onSelected={(id) => setActiveRuntimeId(id)}
      />
    </div>
  )
}
